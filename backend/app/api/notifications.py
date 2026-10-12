from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Notification, Task, TaskActivity, WorkspaceMembership
from .auth import require_authenticated_user, verify_csrf_token
from .workspaces import format_utc, rollback_and_raise, validation_error, workspace_error

notifications_bp = Blueprint("notifications", __name__)
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_OFFSET = 1_000_000


def create_notification(
    *,
    recipient_id: int,
    notification_type: str,
    message: str,
    workspace_id: int,
    project_id: int,
    task_id: int,
    dedupe_key: str,
) -> None:
    if recipient_id == g.current_user.id:
        return
    if (
        db.session.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == recipient_id,
            )
        )
        is None
    ):
        return
    db.session.add(
        Notification(
            recipient_id=recipient_id,
            notification_type=notification_type,
            message=message,
            payload={},
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
            dedupe_key=dedupe_key,
        )
    )


def record_assignment_notification(
    *,
    task: Task,
    workspace_id: int,
    activity: TaskActivity,
) -> None:
    if task.assignee_id is None:
        return
    create_notification(
        recipient_id=task.assignee_id,
        notification_type="task_assigned",
        message="You were assigned to a task.",
        workspace_id=workspace_id,
        project_id=task.project_id,
        task_id=task.id,
        dedupe_key=f"task-assigned:{activity.id}:{task.assignee_id}",
    )


def notification_response(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "type": notification.notification_type,
        "message": notification.message,
        "payload": {},
        "workspace_id": notification.workspace_id,
        "project_id": notification.project_id,
        "task_id": notification.task_id,
        "created_at": format_utc(notification.created_at),
        "read_at": (format_utc(notification.read_at) if notification.read_at is not None else None),
    }


def accessible_notifications():
    member_workspace_ids = select(WorkspaceMembership.workspace_id).where(
        WorkspaceMembership.user_id == g.current_user.id
    )
    return Notification.recipient_id == g.current_user.id, Notification.workspace_id.in_(
        member_workspace_ids
    )


def unread_count() -> int:
    own_notifications, accessible_workspaces = accessible_notifications()
    return (
        db.session.scalar(
            select(func.count(Notification.id)).where(
                own_notifications,
                accessible_workspaces,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )


@notifications_bp.before_request
def protect_notification_mutations():
    return verify_csrf_token()


@notifications_bp.get("")
@require_authenticated_user
def list_notifications():
    errors = {}
    allowed_query = {"limit", "offset"}
    if request.args.keys() - allowed_query:
        errors["query"] = "Only limit and offset are supported."
    for key in allowed_query:
        if len(request.args.getlist(key)) > 1:
            errors[key] = "Provide this value only once."
    limit = DEFAULT_PAGE_SIZE
    offset = 0
    if "limit" in request.args:
        raw_limit = request.args["limit"]
        if not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= MAX_PAGE_SIZE:
            errors["limit"] = f"Choose a page size from 1 to {MAX_PAGE_SIZE}."
        else:
            limit = int(raw_limit)
    if "offset" in request.args:
        raw_offset = request.args["offset"]
        if not raw_offset.isdecimal() or int(raw_offset) > MAX_OFFSET:
            errors["offset"] = f"Choose an offset from 0 to {MAX_OFFSET}."
        else:
            offset = int(raw_offset)
    if errors:
        return validation_error(errors)

    own_notifications, accessible_workspaces = accessible_notifications()
    notifications = db.session.scalars(
        select(Notification)
        .where(own_notifications, accessible_workspaces)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return jsonify(
        {
            "notifications": [notification_response(item) for item in notifications],
            "unread_count": unread_count(),
            "limit": limit,
            "offset": offset,
        }
    )


@notifications_bp.get("/unread-count")
@require_authenticated_user
def get_unread_count():
    return jsonify({"unread_count": unread_count()})


@notifications_bp.post("/<int:notification_id>/read")
@require_authenticated_user
def mark_notification_read(notification_id: int):
    own_notifications, accessible_workspaces = accessible_notifications()
    notification = db.session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            own_notifications,
            accessible_workspaces,
        )
    )
    if notification is None:
        return workspace_error("notification_not_found", "The notification was not found.", 404)
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        try:
            db.session.commit()
        except SQLAlchemyError as error:
            rollback_and_raise(error)
    return jsonify(
        {
            "notification": notification_response(notification),
            "unread_count": unread_count(),
        }
    )


@notifications_bp.post("/read-all")
@require_authenticated_user
def mark_all_notifications_read():
    own_notifications, accessible_workspaces = accessible_notifications()
    try:
        db.session.execute(
            update(Notification)
            .where(
                own_notifications,
                accessible_workspaces,
                Notification.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
        )
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"status": "ok", "unread_count": 0})
