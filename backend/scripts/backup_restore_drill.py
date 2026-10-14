from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import (
    Notification,
    Project,
    Task,
    TaskActivity,
    TaskComment,
    User,
    Workspace,
    WorkspaceMembership,
)

DRILL_EMAIL = "teamflow-backup-restore-drill@example.invalid"
DRILL_WORKSPACE = "TeamFlow backup restore drill"
DRILL_PROJECT = "Backup restore project"
DRILL_TASK = "Backup restore task"
DRILL_COMMENT = "Synthetic backup restore verification comment."
DRILL_NOTIFICATION_KEY = "backup-restore-drill-v1"


def ensure_disposable_target(expected_database: str) -> None:
    if db.engine.url.get_backend_name() != "postgresql":
        raise RuntimeError("The backup/restore drill only runs against PostgreSQL.")
    if db.engine.url.database != expected_database:
        raise RuntimeError(
            f"The backup/restore drill requires the disposable {expected_database} database."
        )
    if db.engine.url.host not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("The backup/restore drill requires a loopback PostgreSQL host.")


def verify_migration_head() -> None:
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    config = Config(str(migrations / "alembic.ini"))
    config.set_main_option("script_location", str(migrations))
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())
    with db.engine.connect() as connection:
        current_heads = set(MigrationContext.configure(connection).get_current_heads())
    if not expected_heads or current_heads != expected_heads:
        raise RuntimeError(
            f"Restored database revisions {sorted(current_heads)} do not match "
            f"migration heads {sorted(expected_heads)}."
        )


def seed_records() -> None:
    if db.session.scalar(select(User.id).where(User.email == DRILL_EMAIL)) is not None:
        raise RuntimeError("The synthetic backup/restore marker already exists.")

    user = User(name="Backup Restore Drill", email=DRILL_EMAIL)
    user.set_password(secrets.token_urlsafe(32))
    workspace = Workspace(name=DRILL_WORKSPACE, owner=user)
    workspace.memberships.append(WorkspaceMembership(user=user, role="owner"))
    project = Project(name=DRILL_PROJECT, workspace=workspace)
    task = Task(
        title=DRILL_TASK,
        project=project,
        assignee=user,
        status="in_progress",
        priority="high",
    )
    task.comments.append(TaskComment(body=DRILL_COMMENT, author=user))
    task.activities.append(
        TaskActivity(
            workspace=workspace,
            project=project,
            actor=user,
            event_type="task_created",
            data={},
        )
    )
    task.notifications.append(
        Notification(
            recipient=user,
            notification_type="task_assigned",
            message="You were assigned to a backup restore drill task.",
            workspace=workspace,
            project=project,
            task=task,
            dedupe_key=DRILL_NOTIFICATION_KEY,
        )
    )

    db.session.add(user)
    db.session.add(workspace)
    db.session.commit()
    print("Seeded synthetic linked records in the disposable migration database.")


def verify_records() -> None:
    verify_migration_head()
    user = db.session.scalar(select(User).where(User.email == DRILL_EMAIL))
    if user is None:
        raise AssertionError("The restored synthetic user is missing.")
    workspace = db.session.scalar(select(Workspace).where(Workspace.name == DRILL_WORKSPACE))
    if workspace is None or workspace.owner_id != user.id:
        raise AssertionError("The restored workspace owner relationship is incorrect.")
    membership = db.session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.role == "owner",
        )
    )
    if membership is None:
        raise AssertionError("The restored workspace membership is missing.")
    project = db.session.scalar(
        select(Project).where(
            Project.workspace_id == workspace.id,
            Project.name == DRILL_PROJECT,
        )
    )
    if project is None:
        raise AssertionError("The restored project relationship is incorrect.")
    task = db.session.scalar(
        select(Task).where(Task.project_id == project.id, Task.title == DRILL_TASK)
    )
    if task is None or task.assignee_id != user.id:
        raise AssertionError("The restored task or assignee relationship is incorrect.")
    comment = db.session.scalar(
        select(TaskComment).where(
            TaskComment.task_id == task.id,
            TaskComment.author_id == user.id,
            TaskComment.body == DRILL_COMMENT,
        )
    )
    if comment is None:
        raise AssertionError("The restored task comment relationship is missing.")
    activity = db.session.scalar(
        select(TaskActivity).where(
            TaskActivity.task_id == task.id,
            TaskActivity.actor_id == user.id,
            TaskActivity.event_type == "task_created",
        )
    )
    if activity is None:
        raise AssertionError("The restored task activity relationship is missing.")
    notification = db.session.scalar(
        select(Notification).where(
            Notification.recipient_id == user.id,
            Notification.workspace_id == workspace.id,
            Notification.project_id == project.id,
            Notification.task_id == task.id,
            Notification.dedupe_key == DRILL_NOTIFICATION_KEY,
        )
    )
    if notification is None:
        raise AssertionError("The restored notification relationships are incorrect.")

    for record in (user, workspace, project, task, comment, activity, notification):
        created_at = record.created_at
        if (
            not isinstance(created_at, datetime)
            or created_at.tzinfo is None
            or created_at.utcoffset() != UTC.utcoffset(created_at)
        ):
            raise AssertionError("A restored creation timestamp is not UTC-aware.")
    print(
        "Verified migration head and synthetic user, workspace membership, "
        "project, task, comment, activity, and notification relationships."
    )


def main() -> None:
    import sys

    if len(sys.argv) != 2 or sys.argv[1] not in {"seed", "verify"}:
        raise SystemExit("Usage: python scripts/backup_restore_drill.py [seed|verify]")
    if (config_name := os.environ.get("APP_CONFIG")) != "development":
        raise RuntimeError(f"The drill requires APP_CONFIG=development, not {config_name!r}.")

    app = create_app("development")
    with app.app_context():
        if sys.argv[1] == "seed":
            ensure_disposable_target("teamflow_migration_check")
            seed_records()
        else:
            ensure_disposable_target("teamflow_backup_restore_check")
            verify_records()


if __name__ == "__main__":
    main()
