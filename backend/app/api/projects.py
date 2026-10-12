from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Project
from .auth import require_authenticated_user, verify_csrf_token
from .workspaces import (
    current_membership,
    format_utc,
    rollback_and_raise,
    validation_error,
    workspace_error,
    workspace_not_found,
)

projects_bp = Blueprint("projects", __name__)
MAX_PROJECT_NAME_LENGTH = 120
MAX_PROJECT_DESCRIPTION_LENGTH = 2000
ALLOWED_PROJECT_FIELDS = {"name", "description"}


@projects_bp.before_request
def protect_project_mutations():
    return verify_csrf_token()


def project_response(project: Project) -> dict[str, int | str | None]:
    return {
        "id": project.id,
        "workspace_id": project.workspace_id,
        "name": project.name,
        "description": project.description,
        "created_at": format_utc(project.created_at),
        "updated_at": format_utc(project.updated_at),
    }


def parse_project_fields(
    *, partial: bool
) -> tuple[dict[str, str | None] | None, dict[str, str] | None]:
    if not request.is_json:
        return None, {"body": "A JSON request body is required."}

    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, {"body": "A valid JSON object is required."}

    fields: dict[str, str] = {}
    for key in payload.keys() - ALLOWED_PROJECT_FIELDS:
        fields[key] = "This field is not allowed."

    if not partial and "name" not in payload:
        fields["name"] = "A project name is required."
    if partial and not payload:
        fields["body"] = "At least one project field is required."

    values: dict[str, str | None] = {}
    if "name" in payload:
        raw_name = payload["name"]
        if not isinstance(raw_name, str) or not raw_name.strip():
            fields["name"] = "A project name is required."
        elif len(raw_name.strip()) > MAX_PROJECT_NAME_LENGTH:
            fields["name"] = f"Project name must be {MAX_PROJECT_NAME_LENGTH} characters or fewer."
        else:
            values["name"] = raw_name.strip()

    if "description" in payload:
        raw_description = payload["description"]
        if raw_description is not None and not isinstance(raw_description, str):
            fields["description"] = "Project description must be a string or null."
        elif isinstance(raw_description, str) and len(raw_description.strip()) > (
            MAX_PROJECT_DESCRIPTION_LENGTH
        ):
            fields["description"] = (
                f"Project description must be {MAX_PROJECT_DESCRIPTION_LENGTH} characters or fewer."
            )
        else:
            values["description"] = (
                raw_description.strip() or None if isinstance(raw_description, str) else None
            )

    if fields:
        return None, fields
    return values, None


def project_not_found():
    return workspace_error("project_not_found", "The project was not found.", 404)


def find_project(workspace_id: int, project_id: int) -> Project | None:
    return db.session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
    )


def require_project_admin(membership):
    if membership.role not in {"owner", "admin"}:
        return workspace_error(
            "permission_denied",
            "Workspace owners or admins are required for this project operation.",
            403,
        )
    return None


@projects_bp.post("/<int:workspace_id>/projects")
@require_authenticated_user
def create_project(workspace_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    permission_error = require_project_admin(membership)
    if permission_error is not None:
        return permission_error

    values, errors = parse_project_fields(partial=False)
    if errors is not None:
        return validation_error(errors)

    project = Project(workspace_id=workspace_id, **values)
    db.session.add(project)
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"project": project_response(project)}), 201


@projects_bp.get("/<int:workspace_id>/projects")
@require_authenticated_user
def list_projects(workspace_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()

    projects = db.session.scalars(
        select(Project)
        .where(Project.workspace_id == workspace_id)
        .order_by(Project.name, Project.id)
    ).all()
    return jsonify({"projects": [project_response(project) for project in projects]})


@projects_bp.get("/<int:workspace_id>/projects/<int:project_id>")
@require_authenticated_user
def get_project(workspace_id: int, project_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    project = find_project(workspace_id, project_id)
    if project is None:
        return project_not_found()
    return jsonify({"project": project_response(project)})


@projects_bp.patch("/<int:workspace_id>/projects/<int:project_id>")
@require_authenticated_user
def update_project(workspace_id: int, project_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    permission_error = require_project_admin(membership)
    if permission_error is not None:
        return permission_error

    project = find_project(workspace_id, project_id)
    if project is None:
        return project_not_found()

    values, errors = parse_project_fields(partial=True)
    if errors is not None:
        return validation_error(errors)

    for field, value in values.items():
        setattr(project, field, value)
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"project": project_response(project)})


@projects_bp.delete("/<int:workspace_id>/projects/<int:project_id>")
@require_authenticated_user
def delete_project(workspace_id: int, project_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    permission_error = require_project_admin(membership)
    if permission_error is not None:
        return permission_error

    project = find_project(workspace_id, project_id)
    if project is None:
        return project_not_found()

    db.session.delete(project)
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"status": "ok", "message": "Project deleted."})
