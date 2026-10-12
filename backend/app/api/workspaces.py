from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import User, Workspace, WorkspaceMembership
from .auth import require_authenticated_user, verify_csrf_token

workspaces_bp = Blueprint("workspaces", __name__)
MAX_WORKSPACE_NAME_LENGTH = 120


@workspaces_bp.before_request
def protect_workspace_mutations():
    return verify_csrf_token()


def workspace_error(error: str, message: str, status: int):
    return jsonify({"error": error, "message": message}), status


def workspace_not_found():
    return workspace_error("workspace_not_found", "The workspace was not found.", 404)


def workspace_response(workspace: Workspace, role: str) -> dict[str, int | str]:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "owner_id": workspace.owner_id,
        "role": role,
        "created_at": format_utc(workspace.created_at),
        "updated_at": format_utc(workspace.updated_at),
    }


def format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def current_membership(workspace_id: int) -> WorkspaceMembership | None:
    return db.session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == g.current_user.id,
        )
    )


def parse_name():
    if not request.is_json:
        return None, {"body": "A JSON request body is required."}

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, {"body": "A valid JSON object is required."}

    raw_name = payload.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        return None, {"name": "A workspace name is required."}

    name = raw_name.strip()
    if len(name) > MAX_WORKSPACE_NAME_LENGTH:
        return None, {
            "name": f"Workspace name must be {MAX_WORKSPACE_NAME_LENGTH} characters or fewer."
        }
    return name, None


def validation_error(fields: dict[str, str]):
    return (
        jsonify(
            {
                "error": "validation_error",
                "message": "Please correct the invalid fields.",
                "fields": fields,
            }
        ),
        400,
    )


def rollback_and_raise(error: SQLAlchemyError) -> None:
    db.session.rollback()
    raise error


@workspaces_bp.post("")
@require_authenticated_user
def create_workspace():
    name, errors = parse_name()
    if errors is not None:
        return validation_error(errors)

    workspace = Workspace(name=name, owner=g.current_user)
    owner_membership = WorkspaceMembership(user=g.current_user, role="owner")
    workspace.memberships.append(owner_membership)
    db.session.add(workspace)
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)

    return jsonify({"workspace": workspace_response(workspace, "owner")}), 201


@workspaces_bp.get("")
@require_authenticated_user
def list_workspaces():
    memberships = db.session.scalars(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == g.current_user.id)
        .join(Workspace)
        .order_by(Workspace.name, Workspace.id)
    ).all()
    return jsonify(
        {
            "workspaces": [
                workspace_response(membership.workspace, membership.role)
                for membership in memberships
            ]
        }
    )


@workspaces_bp.get("/<int:workspace_id>")
@require_authenticated_user
def get_workspace(workspace_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    return jsonify({"workspace": workspace_response(membership.workspace, membership.role)})


@workspaces_bp.patch("/<int:workspace_id>")
@require_authenticated_user
def update_workspace(workspace_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    if membership.role not in {"owner", "admin"}:
        return workspace_error("permission_denied", "You cannot update this workspace.", 403)

    name, errors = parse_name()
    if errors is not None:
        return validation_error(errors)

    workspace = membership.workspace
    workspace.name = name
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"workspace": workspace_response(workspace, membership.role)})


@workspaces_bp.get("/<int:workspace_id>/members")
@require_authenticated_user
def list_workspace_members(workspace_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()

    members = db.session.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(User.name, User.id)
    ).all()
    return jsonify(
        {
            "members": [
                {
                    "user_id": user.id,
                    "name": user.name,
                    "role": member.role,
                    **({"email": user.email} if membership.role in {"owner", "admin"} else {}),
                }
                for member, user in members
            ]
        }
    )


@workspaces_bp.post("/<int:workspace_id>/transfer-ownership")
@require_authenticated_user
def transfer_workspace_ownership(workspace_id: int):
    owner_membership = current_membership(workspace_id)
    if owner_membership is None:
        return workspace_not_found()
    if owner_membership.role != "owner":
        return workspace_error(
            "permission_denied", "Only the workspace owner can transfer ownership.", 403
        )

    payload: Any = request.get_json(silent=True) if request.is_json else None
    target_user_id = payload.get("user_id") if isinstance(payload, dict) else None
    if (
        not isinstance(target_user_id, int)
        or isinstance(target_user_id, bool)
        or target_user_id == g.current_user.id
    ):
        return validation_error({"user_id": "Select another existing workspace member."})

    target_membership = db.session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == target_user_id,
        )
    )
    if target_membership is None:
        return validation_error({"user_id": "Select an existing workspace member."})

    workspace = owner_membership.workspace
    owner_membership.role = "admin"
    try:
        db.session.flush()
        target_membership.role = "owner"
        workspace.owner_id = target_user_id
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)

    return jsonify({"workspace": workspace_response(workspace, "admin")})


@workspaces_bp.delete("/<int:workspace_id>")
@require_authenticated_user
def delete_workspace(workspace_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    if membership.role != "owner":
        return workspace_error(
            "permission_denied", "Only the workspace owner can delete this workspace.", 403
        )

    workspace = membership.workspace
    db.session.delete(workspace)
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)

    return jsonify({"status": "ok", "message": "Workspace deleted."})
