from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..extensions import db
from ..models import Notification, User, WorkspaceInvitation, WorkspaceMembership
from ..services.invitation_delivery import (
    DeliveryMisconfigured,
    DeliveryRejected,
    DeliveryResult,
    DeliveryUnknown,
    DevelopmentInvitationOutbox,
    InvitationDelivery,
)
from ..services.invitation_email import build_invitation_email
from .auth import EMAIL_PATTERN, require_authenticated_user, verify_csrf_token
from .workspaces import (
    current_membership,
    format_utc,
    rollback_and_raise,
    validation_error,
    workspace_error,
    workspace_not_found,
)

workspace_memberships_bp = Blueprint("workspace_memberships", __name__)
invitation_accept_bp = Blueprint("invitation_accept", __name__)
INVITATION_LIFETIME = timedelta(days=7)
ALLOWED_INVITATION_FIELDS = {"email", "role"}


@workspace_memberships_bp.before_request
@invitation_accept_bp.before_request
def protect_membership_mutations():
    return verify_csrf_token()


def invitation_response(invitation: WorkspaceInvitation) -> dict[str, Any]:
    return {
        "id": invitation.id,
        "workspace_id": invitation.workspace_id,
        "email": invitation.email,
        "role": invitation.role,
        "inviter": (
            {"id": invitation.inviter.id, "name": invitation.inviter.name}
            if invitation.inviter
            else None
        ),
        "status": invitation.status,
        "delivery_status": invitation.delivery_status,
        "created_at": format_utc(invitation.created_at),
        "expires_at": format_utc(invitation.expires_at),
    }


def _unauthorized_workspace_role(workspace_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return None, workspace_not_found()
    if membership.role not in {"owner", "admin"}:
        return membership, workspace_error(
            "permission_denied", "Workspace administrator access is required.", 403
        )
    return membership, None


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _invitation_unavailable(status: int = 410):
    return workspace_error(
        "invitation_unavailable",
        "This invitation is expired, revoked, or has already been used.",
        status,
    )


def _delivery_error(
    code: str,
    message: str,
    status: int,
    delivery_status: str,
    invitation: WorkspaceInvitation | None = None,
    reason: str | None = None,
):
    body: dict[str, Any] = {
        "error": code,
        "message": message,
        "delivery_status": delivery_status,
    }
    if reason is not None:
        body["reason"] = reason
    if invitation is not None:
        body["invitation"] = invitation_response(invitation)
    return jsonify(body), status


def _deliver_and_record(
    invitation: WorkspaceInvitation,
    raw_token: str,
    delivery: InvitationDelivery,
) -> tuple[str, WorkspaceInvitation | None, bool]:
    misconfigured = False
    try:
        invitation_url = (
            f"{current_app.config['FRONTEND_ORIGIN'].rstrip('/')}/accept-invitation?"
            f"{urlencode({'token': raw_token})}"
        )
        message = build_invitation_email(
            invitation_id=invitation.id,
            recipient_email=invitation.email,
            workspace_name=invitation.workspace.name,
            inviter_name=invitation.inviter.name if invitation.inviter else None,
            role=invitation.role,
            expires_at=invitation.expires_at,
            invitation_url=invitation_url,
        )
        result = delivery.deliver(message)
        delivery_status = result.status if isinstance(result, DeliveryResult) else "unknown"
        if delivery_status not in {"accepted", "development_outbox"}:
            delivery_status = "unknown"
    except DeliveryRejected as error:
        delivery_status = "rejected"
        misconfigured = isinstance(error, DeliveryMisconfigured)
    except DeliveryUnknown:
        delivery_status = "unknown"
    except Exception:
        delivery_status = "unknown"

    try:
        outcome = db.session.execute(
            update(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.id == invitation.id,
                WorkspaceInvitation.token_hash == _token_digest(raw_token),
                WorkspaceInvitation.status == "pending",
            )
            .values(delivery_status=delivery_status)
        )
        if outcome.rowcount != 1:
            db.session.rollback()
            return "superseded", None, False
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return "outcome_failed", None, False

    current = db.session.scalar(
        select(WorkspaceInvitation).where(WorkspaceInvitation.id == invitation.id)
    )
    return delivery_status, current, misconfigured


def _delivery_response(
    invitation: WorkspaceInvitation,
    delivery_status: str,
    operation: str,
    http_status: int,
    misconfigured: bool = False,
):
    if delivery_status == "accepted":
        return (
            jsonify(
                {
                    "invitation": invitation_response(invitation),
                    "delivery_status": delivery_status,
                    "message": (
                        f"Invitation {operation}. The email provider accepted the message "
                        "for processing; inbox delivery is not guaranteed."
                    ),
                }
            ),
            http_status,
        )
    if delivery_status == "development_outbox":
        return (
            jsonify(
                {
                    "invitation": invitation_response(invitation),
                    "delivery_status": delivery_status,
                    "message": (
                        f"Invitation {operation}. No email was sent; use the local "
                        "development outbox to retrieve the link."
                    ),
                }
            ),
            http_status,
        )
    if delivery_status == "rejected" and misconfigured:
        return _delivery_error(
            "invitation_delivery_rejected",
            "Invitation email delivery is misconfigured on the server; no successful "
            "delivery was recorded. Ask the server administrator to check the email settings.",
            502,
            delivery_status,
            invitation,
            reason="misconfigured",
        )
    if delivery_status == "rejected":
        return _delivery_error(
            "invitation_delivery_rejected",
            "The email provider rejected this invitation; no successful delivery was recorded.",
            502,
            delivery_status,
            invitation,
        )
    return _delivery_error(
        "invitation_delivery_unavailable",
        "Invitation email delivery was not confirmed. Retry the invitation or revoke it.",
        503,
        "unknown",
        invitation,
    )


def _complete_delivery(
    invitation: WorkspaceInvitation,
    raw_token: str,
    delivery: InvitationDelivery,
    operation: str,
    http_status: int,
):
    delivery_status, current, misconfigured = _deliver_and_record(invitation, raw_token, delivery)
    if delivery_status == "superseded":
        return _delivery_error(
            "invitation_delivery_superseded",
            "This invitation changed before delivery completed. Refresh and try again.",
            409,
            "unknown",
        )
    if delivery_status == "outcome_failed" or current is None:
        return _delivery_error(
            "invitation_delivery_unavailable",
            "Invitation delivery could not be confirmed. Refresh and retry the invitation.",
            503,
            "unknown",
        )
    return _delivery_response(current, delivery_status, operation, http_status, misconfigured)


@workspace_memberships_bp.post("/<int:workspace_id>/invitations")
@require_authenticated_user
def create_invitation(workspace_id: int):
    membership, error = _unauthorized_workspace_role(workspace_id)
    if error is not None:
        return error
    delivery: InvitationDelivery | None = current_app.extensions.get("invitation_delivery")
    if delivery is None:
        return workspace_error(
            "invitation_delivery_unconfigured",
            "Invitation delivery is not configured; no invitation was created.",
            503,
        )

    if not request.is_json:
        return validation_error({"body": "A JSON request body is required."})
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return validation_error({"body": "A valid JSON object is required."})

    errors = {
        key: "This field is not allowed." for key in payload.keys() - ALLOWED_INVITATION_FIELDS
    }
    raw_email = payload.get("email")
    if not isinstance(raw_email, str) or not raw_email.strip():
        errors["email"] = "An email address is required."
        email = ""
    else:
        email = User.normalize_email(raw_email)
        if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
            errors["email"] = "Enter a valid email address."

    role = payload.get("role", "member")
    if not isinstance(role, str) or role not in {"admin", "member"}:
        errors["role"] = "Choose admin or member."
    elif role == "admin" and membership.role != "owner":
        return workspace_error(
            "permission_denied", "Only the workspace owner may invite an admin.", 403
        )
    if errors:
        return validation_error(errors)

    existing_member = db.session.scalar(
        select(WorkspaceMembership)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            User.email == email,
        )
    )
    if existing_member is not None:
        return workspace_error(
            "already_workspace_member", "This account is already a workspace member.", 409
        )

    pending = db.session.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.email == email,
            WorkspaceInvitation.status == "pending",
        )
    )
    now = datetime.now(UTC)
    if pending is not None:
        if _utc(pending.expires_at) > now:
            return workspace_error(
                "invitation_already_pending",
                "A pending invitation already exists for this email.",
                409,
            )
        pending.status = "expired"

    token = secrets.token_urlsafe(32)
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        email=email,
        role=role,
        token_hash=_token_digest(token),
        expires_at=now + INVITATION_LIFETIME,
        inviter_id=g.current_user.id,
        status="pending",
        delivery_status="pending",
    )
    db.session.add(invitation)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        duplicate_pending = db.session.scalar(
            select(WorkspaceInvitation.id).where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.email == email,
                WorkspaceInvitation.status == "pending",
            )
        )
        if duplicate_pending is not None:
            return workspace_error(
                "invitation_already_pending",
                "A pending invitation already exists for this email.",
                409,
            )
        raise error
    except SQLAlchemyError as error:
        rollback_and_raise(error)

    return _complete_delivery(invitation, token, delivery, "created", 201)


@workspace_memberships_bp.post("/<int:workspace_id>/invitations/<int:invitation_id>/resend")
@require_authenticated_user
def resend_invitation(workspace_id: int, invitation_id: int):
    membership, error = _unauthorized_workspace_role(workspace_id)
    if error is not None:
        return error
    delivery: InvitationDelivery | None = current_app.extensions.get("invitation_delivery")
    if delivery is None:
        return workspace_error(
            "invitation_delivery_unconfigured",
            "Invitation delivery is not configured; no resend was attempted.",
            503,
        )
    if request.get_data(cache=True):
        return validation_error({"body": "The resend request body must be empty."})

    invitation = db.session.scalar(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if invitation is None:
        return workspace_error("invitation_not_found", "The invitation was not found.", 404)
    if membership.role == "admin" and invitation.role != "member":
        return workspace_error(
            "permission_denied", "Only the workspace owner may resend an admin invitation.", 403
        )
    now = datetime.now(UTC)
    if invitation.status != "pending" or _utc(invitation.expires_at) <= now:
        if invitation.status == "pending":
            invitation.status = "expired"
            try:
                db.session.commit()
            except SQLAlchemyError as error:
                rollback_and_raise(error)
        return _invitation_unavailable()

    token = secrets.token_urlsafe(32)
    invitation.token_hash = _token_digest(token)
    invitation.expires_at = now + INVITATION_LIFETIME
    invitation.delivery_status = "pending"
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)

    return _complete_delivery(invitation, token, delivery, "resent", 200)


@workspace_memberships_bp.get("/<int:workspace_id>/invitations")
@require_authenticated_user
def list_invitations(workspace_id: int):
    _, error = _unauthorized_workspace_role(workspace_id)
    if error is not None:
        return error

    invitations = db.session.scalars(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.status == "pending",
            WorkspaceInvitation.expires_at > datetime.now(UTC),
        )
        .order_by(WorkspaceInvitation.created_at.desc(), WorkspaceInvitation.id.desc())
    ).all()
    return jsonify({"invitations": [invitation_response(item) for item in invitations]})


@workspace_memberships_bp.delete("/<int:workspace_id>/invitations/<int:invitation_id>")
@require_authenticated_user
def revoke_invitation(workspace_id: int, invitation_id: int):
    membership, error = _unauthorized_workspace_role(workspace_id)
    if error is not None:
        return error
    invitation = db.session.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == workspace_id,
        )
    )
    if invitation is None:
        return workspace_error("invitation_not_found", "The invitation was not found.", 404)
    if invitation.status != "pending" or _utc(invitation.expires_at) <= datetime.now(UTC):
        invitation.status = "expired" if invitation.status == "pending" else invitation.status
        if invitation.status == "expired":
            try:
                db.session.commit()
            except SQLAlchemyError as error:
                rollback_and_raise(error)
        return _invitation_unavailable()
    if membership.role == "admin" and invitation.role != "member":
        return workspace_error(
            "permission_denied", "Only the workspace owner may revoke an admin invitation.", 403
        )

    invitation.status = "revoked"
    invitation.revoked_at = datetime.now(UTC)
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"status": "ok", "message": "Invitation revoked."})


@workspace_memberships_bp.get(
    "/<int:workspace_id>/invitations/<int:invitation_id>/development-link"
)
@require_authenticated_user
def retrieve_development_invitation_link(workspace_id: int, invitation_id: int):
    if current_app.config.get("APP_CONFIG") != "development":
        return workspace_error("not_found", "The requested resource was not found.", 404)

    membership, error = _unauthorized_workspace_role(workspace_id)
    if error is not None:
        return error
    invitation = db.session.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.status == "pending",
        )
    )
    if invitation is None or _utc(invitation.expires_at) <= datetime.now(UTC):
        return workspace_error(
            "development_link_unavailable",
            "The local invitation link is unavailable or expired.",
            404,
        )
    if membership.role == "admin" and invitation.role != "member":
        return workspace_error(
            "permission_denied", "Only the workspace owner may retrieve this link.", 403
        )
    delivery = current_app.extensions.get("invitation_delivery")
    invitation_url = (
        delivery.take(invitation.id) if isinstance(delivery, DevelopmentInvitationOutbox) else None
    )
    if invitation_url is None:
        return workspace_error(
            "development_link_unavailable",
            "The local invitation link was already retrieved or is unavailable.",
            404,
        )

    response = jsonify({"invitation_url": invitation_url})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@invitation_accept_bp.post("/accept")
@require_authenticated_user
def accept_invitation():
    if not request.is_json:
        return validation_error({"body": "A JSON request body is required."})
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"token"}:
        return validation_error({"token": "A valid invitation token is required."})
    token = payload.get("token")
    if not isinstance(token, str) or not (32 <= len(token) <= 128):
        return validation_error({"token": "A valid invitation token is required."})

    invitation = db.session.scalar(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.token_hash == _token_digest(token))
        .with_for_update()
    )
    if invitation is None:
        return workspace_error("invitation_not_found", "The invitation was not found.", 404)
    if invitation.status != "pending":
        return _invitation_unavailable()
    now = datetime.now(UTC)
    if _utc(invitation.expires_at) <= now:
        invitation.status = "expired"
        try:
            db.session.commit()
        except SQLAlchemyError as error:
            rollback_and_raise(error)
        return _invitation_unavailable()
    if User.normalize_email(g.current_user.email) != invitation.email:
        return workspace_error(
            "invitation_email_mismatch",
            "This invitation belongs to a different account. Sign in with the invited email.",
            403,
        )

    existing = db.session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == invitation.workspace_id,
            WorkspaceMembership.user_id == g.current_user.id,
        )
    )
    if existing is None:
        db.session.add(
            WorkspaceMembership(
                workspace_id=invitation.workspace_id,
                user_id=g.current_user.id,
                role=invitation.role,
            )
        )
    invitation.status = "accepted"
    invitation.accepted_at = now
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        current = db.session.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.token_hash == _token_digest(token)
            )
        )
        if current is not None and current.status != "pending":
            return _invitation_unavailable()
        raise
    except SQLAlchemyError as error:
        rollback_and_raise(error)

    return jsonify(
        {
            "status": "ok",
            "message": "You are now a member of the workspace.",
            "workspace_id": invitation.workspace_id,
        }
    )


@workspace_memberships_bp.patch("/<int:workspace_id>/members/<int:user_id>")
@require_authenticated_user
def change_workspace_member_role(workspace_id: int, user_id: int):
    actor = current_membership(workspace_id)
    if actor is None:
        return workspace_not_found()
    if actor.role != "owner":
        return workspace_error(
            "permission_denied", "Only the workspace owner may change member roles.", 403
        )
    if not request.is_json:
        return validation_error({"body": "A JSON request body is required."})
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"role"}:
        return validation_error({"role": "Choose admin or member."})
    role = payload.get("role")
    if not isinstance(role, str) or role not in {"admin", "member"}:
        return validation_error({"role": "Choose admin or member."})
    if user_id == g.current_user.id:
        return workspace_error(
            "permission_denied", "You cannot change your own workspace role.", 403
        )

    target = db.session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    if target is None or target.role == "owner":
        return workspace_error("member_not_found", "The workspace member was not found.", 404)
    target.role = role
    try:
        db.session.execute(
            WorkspaceInvitation.__table__.update()
            .where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.email == target.user.email,
                WorkspaceInvitation.status == "pending",
            )
            .values(status="revoked", revoked_at=datetime.now(UTC))
        )
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify(
        {
            "member": {
                "user_id": target.user_id,
                "name": target.user.name,
                "email": target.user.email,
                "role": target.role,
            }
        }
    )


@workspace_memberships_bp.delete("/<int:workspace_id>/members/<int:user_id>")
@require_authenticated_user
def remove_workspace_member(workspace_id: int, user_id: int):
    actor = current_membership(workspace_id)
    if actor is None:
        return workspace_not_found()
    if actor.role not in {"owner", "admin"}:
        return workspace_error(
            "permission_denied", "Workspace administrator access is required.", 403
        )
    target = db.session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    if target is None or target.role == "owner":
        return workspace_error("member_not_found", "The workspace member was not found.", 404)
    if user_id == g.current_user.id:
        return workspace_error(
            "permission_denied", "Use the leave-workspace action to remove yourself.", 403
        )
    if actor.role == "admin" and target.role != "member":
        return workspace_error("permission_denied", "Admins may remove regular members only.", 403)
    target_email = target.user.email
    db.session.delete(target)
    try:
        db.session.execute(
            delete(Notification).where(
                Notification.workspace_id == workspace_id,
                Notification.recipient_id == user_id,
            )
        )
        db.session.execute(
            WorkspaceInvitation.__table__.update()
            .where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.email == target_email,
                WorkspaceInvitation.status == "pending",
            )
            .values(status="revoked", revoked_at=datetime.now(UTC))
        )
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"status": "ok", "message": "Workspace member removed."})


@workspace_memberships_bp.post("/<int:workspace_id>/leave")
@require_authenticated_user
def leave_workspace(workspace_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    if membership.role == "owner":
        return workspace_error(
            "owner_transfer_required",
            "Transfer workspace ownership before leaving.",
            409,
        )
    email = g.current_user.email
    db.session.delete(membership)
    try:
        db.session.execute(
            delete(Notification).where(
                Notification.workspace_id == workspace_id,
                Notification.recipient_id == g.current_user.id,
            )
        )
        db.session.execute(
            WorkspaceInvitation.__table__.update()
            .where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.email == email,
                WorkspaceInvitation.status == "pending",
            )
            .values(status="revoked", revoked_at=datetime.now(UTC))
        )
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"status": "ok", "message": "You left the workspace."})
