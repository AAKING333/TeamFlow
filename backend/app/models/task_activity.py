from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from ..extensions import db

if TYPE_CHECKING:
    from .project import Project
    from .task import Task
    from .user import User
    from .workspace import Workspace


class TaskActivity(db.Model):
    __tablename__ = "task_activities"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('task_created', 'task_title_changed', "
            "'task_description_changed', 'task_status_changed', "
            "'task_priority_changed', 'task_assignee_changed', "
            "'task_due_date_changed', 'task_deleted')",
            name="ck_task_activities_event_type",
        ),
        Index("ix_task_activities_project_created", "project_id", "created_at", "id"),
        Index("ix_task_activities_task_created", "task_id", "created_at", "id"),
        Index("ix_task_activities_workspace_id", "workspace_id"),
    )

    EVENT_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "task_created",
            "task_title_changed",
            "task_description_changed",
            "task_status_changed",
            "task_priority_changed",
            "task_assignee_changed",
            "task_due_date_changed",
            "task_deleted",
        }
    )
    STATUS_VALUES: ClassVar[frozenset[str]] = frozenset({"todo", "in_progress", "done"})
    PRIORITY_VALUES: ClassVar[frozenset[str]] = frozenset({"low", "medium", "high"})

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="activities")
    project: Mapped[Project] = relationship("Project", back_populates="activities")
    task: Mapped[Task | None] = relationship("Task", back_populates="activities")
    actor: Mapped[User | None] = relationship("User", back_populates="task_activities")

    @validates("event_type")
    def _validate_event_type(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or value not in self.EVENT_TYPES:
            raise ValueError("Unsupported task activity event type.")
        return value

    @validates("data")
    def _validate_data(self, _key: str, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Task activity data must be an object.")
        event_type = getattr(self, "event_type", None)
        if event_type is None:
            raise ValueError("Set an event type before activity data.")

        if event_type in {"task_created", "task_deleted"}:
            if event_type == "task_deleted":
                title = value.get("task_title")
                if (
                    set(value) != {"task_title"}
                    or not isinstance(title, str)
                    or not title.strip()
                    or len(title) > 200
                ):
                    raise ValueError("Deleted task activity requires a bounded task title.")
            elif value:
                raise ValueError("Task creation activity cannot include arbitrary data.")
            return value

        if event_type in {"task_title_changed", "task_description_changed"}:
            if (
                set(value) != {"changed"}
                or type(value["changed"]) is not bool
                or not value["changed"]
            ):
                raise ValueError("Task text activity data must only mark the field changed.")
        elif event_type == "task_status_changed":
            if (
                set(value) != {"from", "to"}
                or not isinstance(value["from"], str)
                or not isinstance(value["to"], str)
                or value["from"] not in self.STATUS_VALUES
                or value["to"] not in self.STATUS_VALUES
            ):
                raise ValueError("Task status activity requires valid from and to values.")
        elif event_type == "task_priority_changed":
            if (
                set(value) != {"from", "to"}
                or not isinstance(value["from"], str)
                or not isinstance(value["to"], str)
                or value["from"] not in self.PRIORITY_VALUES
                or value["to"] not in self.PRIORITY_VALUES
            ):
                raise ValueError("Task priority activity requires valid from and to values.")
        elif event_type == "task_assignee_changed":
            if set(value) != {"assigned"} or type(value["assigned"]) is not bool:
                raise ValueError("Task assignee activity only records whether it is assigned.")
        elif event_type == "task_due_date_changed":
            if set(value) != {"from", "to"}:
                raise ValueError("Task due date activity requires YYYY-MM-DD values or null.")
            if any(
                item is not None and not isinstance(item, str)
                for item in (value["from"], value["to"])
            ):
                raise ValueError("Task due date activity requires YYYY-MM-DD values or null.")
            try:
                if any(
                    item is not None and date.fromisoformat(item).isoformat() != item
                    for item in (value["from"], value["to"])
                ):
                    raise ValueError
            except ValueError:
                raise ValueError("Task due date activity requires YYYY-MM-DD values or null.")
        return value
