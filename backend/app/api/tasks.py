from __future__ import annotations

from datetime import date
from typing import Any

from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Project, Task, TaskActivity, User, WorkspaceMembership
from .auth import require_authenticated_user, verify_csrf_token
from .notifications import record_assignment_notification
from .projects import find_project
from .workspaces import (
    current_membership,
    format_utc,
    rollback_and_raise,
    validation_error,
    workspace_error,
    workspace_not_found,
)

tasks_bp = Blueprint("tasks", __name__)
MAX_TASK_TITLE_LENGTH = 200
MAX_TASK_DESCRIPTION_LENGTH = 2000
ALLOWED_TASK_FIELDS = {
    "title",
    "description",
    "status",
    "priority",
    "due_date",
    "assignee_id",
}


@tasks_bp.before_request
def protect_task_mutations():
    return verify_csrf_token()


def task_response(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "assignee_id": task.assignee_id,
        "assignee": (
            {"id": task.assignee.id, "name": task.assignee.name} if task.assignee else None
        ),
        "created_at": format_utc(task.created_at),
        "updated_at": format_utc(task.updated_at),
    }


def parse_task_fields(*, partial: bool) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if not request.is_json:
        return None, {"body": "A JSON request body is required."}

    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, {"body": "A valid JSON object is required."}

    errors: dict[str, str] = {
        key: "This field is not allowed." for key in payload.keys() - ALLOWED_TASK_FIELDS
    }
    if not partial and "title" not in payload:
        errors["title"] = "A task title is required."
    if partial and not payload:
        errors["body"] = "At least one task field is required."

    values: dict[str, Any] = {}
    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or not title.strip():
            errors["title"] = "A task title is required."
        elif len(title.strip()) > MAX_TASK_TITLE_LENGTH:
            errors["title"] = f"Task title must be {MAX_TASK_TITLE_LENGTH} characters or fewer."
        else:
            values["title"] = title.strip()

    if "description" in payload:
        description = payload["description"]
        if description is not None and not isinstance(description, str):
            errors["description"] = "Task description must be a string or null."
        elif isinstance(description, str) and len(description.strip()) > (
            MAX_TASK_DESCRIPTION_LENGTH
        ):
            errors["description"] = (
                f"Task description must be {MAX_TASK_DESCRIPTION_LENGTH} characters or fewer."
            )
        else:
            values["description"] = (
                description.strip() or None if isinstance(description, str) else None
            )

    if "status" in payload:
        status = payload["status"]
        if not isinstance(status, str) or status not in Task.STATUSES:
            errors["status"] = "Choose todo, in_progress, or done."
        else:
            values["status"] = status

    if "priority" in payload:
        priority = payload["priority"]
        if not isinstance(priority, str) or priority not in Task.PRIORITIES:
            errors["priority"] = "Choose low, medium, or high."
        else:
            values["priority"] = priority

    if "due_date" in payload:
        due_date = payload["due_date"]
        if due_date is None or due_date == "":
            values["due_date"] = None
        elif not isinstance(due_date, str):
            errors["due_date"] = "Due date must use YYYY-MM-DD format."
        else:
            try:
                values["due_date"] = date.fromisoformat(due_date)
            except ValueError:
                errors["due_date"] = "Due date must use YYYY-MM-DD format."

    if "assignee_id" in payload:
        assignee_id = payload["assignee_id"]
        if assignee_id is None:
            values["assignee_id"] = None
        elif not isinstance(assignee_id, int) or isinstance(assignee_id, bool) or assignee_id < 1:
            errors["assignee_id"] = "Select a valid workspace member."
        else:
            values["assignee_id"] = assignee_id

    if errors:
        return None, errors
    return values, None


def task_not_found():
    return workspace_error("task_not_found", "The task was not found.", 404)


def find_task(project_id: int, task_id: int) -> Task | None:
    return db.session.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))


def workspace_assignees(workspace_id: int) -> list[dict[str, int | str]]:
    rows = db.session.execute(
        select(User.id, User.name)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(User.name, User.id)
    ).all()
    return [{"id": user_id, "name": name} for user_id, name in rows]


def validate_assignee(values: dict[str, Any], workspace_id: int) -> dict[str, str] | None:
    assignee_id = values.get("assignee_id")
    if assignee_id is None:
        return None
    membership_id = db.session.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == assignee_id,
        )
    )
    if membership_id is None:
        return {"assignee_id": "Select a user who belongs to this workspace."}
    return None


def resolve_project(
    workspace_id: int, project_id: int
) -> tuple[Project | None, Response | tuple[Response, int] | None]:
    if current_membership(workspace_id) is None:
        return None, workspace_not_found()
    project = find_project(workspace_id, project_id)
    if project is None:
        return None, workspace_error("project_not_found", "The project was not found.", 404)
    return project, None


def record_activity(
    *,
    workspace_id: int,
    project_id: int,
    task: Task,
    actor_id: int,
    event_type: str,
    data: dict[str, Any],
) -> TaskActivity:
    activity = TaskActivity(
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task.id,
        actor_id=actor_id,
        event_type=event_type,
        data=data,
    )
    db.session.add(activity)
    db.session.flush()
    return activity


@tasks_bp.get("/<int:workspace_id>/projects/<int:project_id>/tasks")
@require_authenticated_user
def list_tasks(workspace_id: int, project_id: int):
    project, error = resolve_project(workspace_id, project_id)
    if error is not None:
        return error

    errors = {}
    status = request.args.get("status")
    priority = request.args.get("priority")
    if len(request.args.getlist("status")) > 1 or (
        status is not None and status not in Task.STATUSES
    ):
        errors["status"] = "Choose todo, in_progress, or done."
    if len(request.args.getlist("priority")) > 1 or (
        priority is not None and priority not in Task.PRIORITIES
    ):
        errors["priority"] = "Choose low, medium, or high."
    if request.args.keys() - {"status", "priority"}:
        errors["query"] = "Only status and priority filters are supported."
    if errors:
        return validation_error(errors)

    query = select(Task).where(Task.project_id == project.id)
    if status is not None:
        query = query.where(Task.status == status)
    if priority is not None:
        query = query.where(Task.priority == priority)
    tasks = db.session.scalars(query.order_by(Task.created_at, Task.id)).all()
    return jsonify(
        {
            "tasks": [task_response(task) for task in tasks],
            "assignees": workspace_assignees(workspace_id),
        }
    )


@tasks_bp.post("/<int:workspace_id>/projects/<int:project_id>/tasks")
@require_authenticated_user
def create_task(workspace_id: int, project_id: int):
    project, error = resolve_project(workspace_id, project_id)
    if error is not None:
        return error

    values, errors = parse_task_fields(partial=False)
    if errors is not None:
        return validation_error(errors)
    assignee_errors = validate_assignee(values, workspace_id)
    if assignee_errors is not None:
        return validation_error(assignee_errors)

    task = Task(project_id=project.id, **values)
    db.session.add(task)
    try:
        db.session.flush()
        activity = record_activity(
            workspace_id=workspace_id,
            project_id=project.id,
            task=task,
            actor_id=g.current_user.id,
            event_type="task_created",
            data={},
        )
        if task.assignee_id is not None:
            record_assignment_notification(
                task=task,
                workspace_id=workspace_id,
                activity=activity,
            )
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"task": task_response(task)}), 201


@tasks_bp.get("/<int:workspace_id>/projects/<int:project_id>/tasks/<int:task_id>")
@require_authenticated_user
def get_task(workspace_id: int, project_id: int, task_id: int):
    project, error = resolve_project(workspace_id, project_id)
    if error is not None:
        return error
    task = find_task(project.id, task_id)
    if task is None:
        return task_not_found()
    return jsonify({"task": task_response(task)})


@tasks_bp.patch("/<int:workspace_id>/projects/<int:project_id>/tasks/<int:task_id>")
@require_authenticated_user
def update_task(workspace_id: int, project_id: int, task_id: int):
    project, error = resolve_project(workspace_id, project_id)
    if error is not None:
        return error
    task = find_task(project.id, task_id)
    if task is None:
        return task_not_found()

    values, errors = parse_task_fields(partial=True)
    if errors is not None:
        return validation_error(errors)
    assignee_errors = validate_assignee(values, workspace_id)
    if assignee_errors is not None:
        return validation_error(assignee_errors)

    activity_events = {
        "title": ("task_title_changed", lambda _old, _new: {"changed": True}),
        "description": ("task_description_changed", lambda _old, _new: {"changed": True}),
        "status": ("task_status_changed", lambda old, new: {"from": old, "to": new}),
        "priority": ("task_priority_changed", lambda old, new: {"from": old, "to": new}),
        "assignee_id": ("task_assignee_changed", lambda _old, new: {"assigned": new is not None}),
        "due_date": (
            "task_due_date_changed",
            lambda old, new: {
                "from": old.isoformat() if old else None,
                "to": new.isoformat() if new else None,
            },
        ),
    }
    changes = []
    for field, value in values.items():
        old_value = getattr(task, field)
        if old_value != value:
            event_type, event_data = activity_events[field]
            changes.append((event_type, event_data(old_value, value)))
        setattr(task, field, value)
    try:
        for event_type, data in changes:
            activity = record_activity(
                workspace_id=workspace_id,
                project_id=project.id,
                task=task,
                actor_id=g.current_user.id,
                event_type=event_type,
                data=data,
            )
            if event_type == "task_assignee_changed" and task.assignee_id is not None:
                record_assignment_notification(
                    task=task,
                    workspace_id=workspace_id,
                    activity=activity,
                )
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"task": task_response(task)})


@tasks_bp.delete("/<int:workspace_id>/projects/<int:project_id>/tasks/<int:task_id>")
@require_authenticated_user
def delete_task(workspace_id: int, project_id: int, task_id: int):
    membership = current_membership(workspace_id)
    if membership is None:
        return workspace_not_found()
    project = find_project(workspace_id, project_id)
    if project is None:
        return workspace_error("project_not_found", "The project was not found.", 404)
    task = find_task(project.id, task_id)
    if task is None:
        return task_not_found()
    if membership.role not in {"owner", "admin"}:
        return workspace_error(
            "permission_denied",
            "Workspace owners or admins are required to delete tasks.",
            403,
        )

    try:
        record_activity(
            workspace_id=workspace_id,
            project_id=project.id,
            task=task,
            actor_id=g.current_user.id,
            event_type="task_deleted",
            data={"task_title": task.title},
        )
        db.session.delete(task)
        db.session.commit()
    except SQLAlchemyError as error:
        rollback_and_raise(error)
    return jsonify({"status": "ok", "message": "Task deleted."})
