from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import TaskActivity, TaskComment
from .auth import require_authenticated_user, verify_csrf_token
from .notifications import create_notification
from .tasks import find_task, resolve_project, task_not_found
from .workspaces import (
    current_membership,
    format_utc,
    rollback_and_raise,
    validation_error,
    workspace_error,
    workspace_not_found,
)

discussion_bp = Blueprint("task_discussion", __name__)
MAX_COMMENT_LENGTH = 4000
MAX_ACTIVITY_PAGE_SIZE = 100
DEFAULT_ACTIVITY_PAGE_SIZE = 50


@discussion_bp.before_request
def protect_discussion_mutations():
    return verify_csrf_token()


def comment_not_found():
    return workspace_error("comment_not_found", "The comment was not found.", 404)


def comment_response(comment: TaskComment, *, can_manage: bool) -> dict[str, Any]:
    return {
        "id": comment.id,
        "task_id": comment.task_id,
        "author": {"id": comment.author.id, "name": comment.author.name},
        "can_manage": can_manage,
        "body": comment.body,
        "created_at": format_utc(comment.created_at),
        "updated_at": format_utc(comment.updated_at),
    }


def parse_comment_body(*, partial: bool) -> tuple[str | None, dict[str, str] | None]:
    if not request.is_json:
        return None, {"body": "A JSON request body is required."}
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, {"body": "A valid JSON object is required."}
    errors = {key: "This field is not allowed." for key in payload.keys() - {"body"}}
    if not partial and "body" not in payload:
        errors["body"] = "A comment body is required."
    if partial and not payload:
        errors["body"] = "A comment body is required."

    raw_body = payload.get("body")
    if "body" in payload:
        if not isinstance(raw_body, str) or not raw_body.strip():
            errors["body"] = "A comment body is required."
        elif len(raw_body.strip()) > MAX_COMMENT_LENGTH:
            errors["body"] = f"Comment body must be {MAX_COMMENT_LENGTH} characters or fewer."
    if errors:
        return None, errors
    return raw_body.strip(), None


def find_comment(task_id: int, comment_id: int) -> TaskComment | None:
    return db.session.scalar(
        select(TaskComment)
        .options(joinedload(TaskComment.author))
        .where(TaskComment.task_id == task_id, TaskComment.id == comment_id)
    )


def may_moderate(membership, comment: TaskComment) -> bool:
    return comment.author_id == g.current_user.id or membership.role in {"owner", "admin"}


@discussion_bp.get("/<int:workspace_id>/projects/<int:project_id>/tasks/<int:task_id>/comments")
@require_authenticated_user
def list_task_comments(workspace_id: int, project_id: int, task_id: int):
    project, error = resolve_project(workspace_id, project_id)
    if error is not None:
        return error
    task = find_task(project.id, task_id)
    if task is None:
        return task_not_found()
    comments = db.session.scalars(
        select(TaskComment)
        .options(joinedload(TaskComment.author))
        .where(TaskComment.task_id == task.id)
        .order_by(TaskComment.created_at, TaskComment.id)
    ).all()
    membership = current_membership(workspace_id)
    can_moderate = membership.role in {"owner", "admin"}
    return jsonify(
        {
            "comments": [
                comment_response(
                    comment,
                    can_manage=can_moderate or comment.author_id == g.current_user.id,
                )
                for comment in comments
            ]
        }
    )


@discussion_bp.post("/<int:workspace_id>/projects/<int:project_id>/tasks/<int:task_id>/comments")
@require_authenticated_user
def create_task_comment(workspace_id: int, project_id: int, task_id: int):
    project, error = resolve_project(workspace_id, project_id)
    if error is not None:
        return error
    task = find_task(project.id, task_id)
    if task is None:
        return task_not_found()
    body, errors = parse_comment_body(partial=False)
    if errors is not None:
        return validation_error(errors)

    comment = TaskComment(task_id=task.id, author_id=g.current_user.id, body=body)
    db.session.add(comment)
    try:
        db.session.flush()
        if task.assignee_id is not None and task.assignee_id != g.current_user.id:
            create_notification(
                recipient_id=task.assignee_id,
                notification_type="task_comment",
                message="A new comment was added to a task assigned to you.",
                workspace_id=workspace_id,
                project_id=project.id,
                task_id=task.id,
                dedupe_key=f"task-comment:{comment.id}:{task.assignee_id}",
            )
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"comment": comment_response(comment, can_manage=True)}), 201


@discussion_bp.patch(
    "/<int:workspace_id>/projects/<int:project_id>/tasks/<int:task_id>/comments/<int:comment_id>"
)
@require_authenticated_user
def update_task_comment(workspace_id: int, project_id: int, task_id: int, comment_id: int):
    project, error = resolve_project(workspace_id, project_id)
    if error is not None:
        return error
    task = find_task(project.id, task_id)
    if task is None:
        return task_not_found()
    comment = find_comment(task.id, comment_id)
    if comment is None:
        return comment_not_found()
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    if not may_moderate(membership, comment):
        return workspace_error(
            "permission_denied",
            "Only the comment author or a workspace admin can edit this comment.",
            403,
        )

    body, errors = parse_comment_body(partial=True)
    if errors is not None:
        return validation_error(errors)
    comment.body = body
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"comment": comment_response(comment, can_manage=True)})


@discussion_bp.delete(
    "/<int:workspace_id>/projects/<int:project_id>/tasks/<int:task_id>/comments/<int:comment_id>"
)
@require_authenticated_user
def delete_task_comment(workspace_id: int, project_id: int, task_id: int, comment_id: int):
    project, error = resolve_project(workspace_id, project_id)
    if error is not None:
        return error
    task = find_task(project.id, task_id)
    if task is None:
        return task_not_found()
    comment = find_comment(task.id, comment_id)
    if comment is None:
        return comment_not_found()
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    if not may_moderate(membership, comment):
        return workspace_error(
            "permission_denied",
            "Only the comment author or a workspace admin can delete this comment.",
            403,
        )

    db.session.delete(comment)
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"status": "ok", "message": "Comment deleted."})


@discussion_bp.get("/<int:workspace_id>/projects/<int:project_id>/activity")
@require_authenticated_user
def list_project_activity(workspace_id: int, project_id: int):
    project, error = resolve_project(workspace_id, project_id)
    if error is not None:
        return error

    errors = {}
    allowed = {"task_id", "limit", "offset"}
    if request.args.keys() - allowed:
        errors["query"] = "Only task_id, limit, and offset are supported."
    for key in allowed:
        if len(request.args.getlist(key)) > 1:
            errors[key] = "Provide this parameter only once."

    task_id = None
    if "task_id" in request.args:
        raw_task_id = request.args["task_id"]
        try:
            task_id = int(raw_task_id)
            if task_id < 1:
                raise ValueError
        except ValueError:
            errors["task_id"] = "Task ID must be a positive integer."
        if task_id is not None and find_task(project.id, task_id) is None:
            return task_not_found()

    try:
        limit = int(request.args.get("limit", DEFAULT_ACTIVITY_PAGE_SIZE))
        offset = int(request.args.get("offset", 0))
        if not 1 <= limit <= MAX_ACTIVITY_PAGE_SIZE:
            errors["limit"] = f"Limit must be between 1 and {MAX_ACTIVITY_PAGE_SIZE}."
        if not 0 <= offset <= 100000:
            errors["offset"] = "Offset must be between 0 and 100000."
    except ValueError:
        limit, offset = DEFAULT_ACTIVITY_PAGE_SIZE, 0
        errors["limit"] = "Limit and offset must be integers."

    if errors:
        return validation_error(errors)

    query = (
        select(TaskActivity)
        .options(joinedload(TaskActivity.actor))
        .where(
            TaskActivity.workspace_id == workspace_id,
            TaskActivity.project_id == project.id,
        )
    )
    if task_id is not None:
        query = query.where(TaskActivity.task_id == task_id)
    activities = db.session.scalars(
        query.order_by(TaskActivity.created_at.desc(), TaskActivity.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return jsonify(
        {
            "activities": [
                {
                    "id": activity.id,
                    "workspace_id": activity.workspace_id,
                    "project_id": activity.project_id,
                    "task_id": activity.task_id,
                    "actor": (
                        {"id": activity.actor.id, "name": activity.actor.name}
                        if activity.actor
                        else None
                    ),
                    "event_type": activity.event_type,
                    "data": activity.data,
                    "created_at": format_utc(activity.created_at),
                }
                for activity in activities
            ],
            "limit": limit,
            "offset": offset,
        }
    )
