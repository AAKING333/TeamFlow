from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from ..extensions import db
from .user import utc_now

if TYPE_CHECKING:
    from .comment import TaskComment
    from .notification import Notification
    from .project import Project
    from .task_activity import TaskActivity
    from .user import User


class Task(db.Model):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="ck_tasks_title_nonempty"),
        CheckConstraint("length(title) <= 200", name="ck_tasks_title_length"),
        CheckConstraint(
            "description IS NULL OR length(description) <= 2000",
            name="ck_tasks_description_length",
        ),
        CheckConstraint(
            "status IN ('todo', 'in_progress', 'done')",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="ck_tasks_priority",
        ),
        Index("ix_tasks_project_id", "project_id"),
        Index("ix_tasks_assignee_id", "assignee_id"),
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_project_priority", "project_id", "priority"),
    )

    STATUSES: ClassVar[frozenset[str]] = frozenset({"todo", "in_progress", "done"})
    PRIORITIES: ClassVar[frozenset[str]] = frozenset({"low", "medium", "high"})

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    project: Mapped[Project] = relationship("Project", back_populates="tasks")
    assignee: Mapped[User | None] = relationship("User", back_populates="assigned_tasks")
    comments: Mapped[list[TaskComment]] = relationship(
        "TaskComment",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    activities: Mapped[list[TaskActivity]] = relationship(
        "TaskActivity",
        back_populates="task",
    )
    notifications: Mapped[list[Notification]] = relationship(
        "Notification",
        back_populates="task",
        cascade="all, delete-orphan",
    )

    @validates("title")
    def _validate_title(self, _key: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Task title must be a string.")
        title = value.strip()
        if not title or len(title) > 200:
            raise ValueError("Task title must be between 1 and 200 characters.")
        return title

    @validates("description")
    def _validate_description(self, _key: str, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Task description must be a string.")
        description = value.strip()
        if len(description) > 2000:
            raise ValueError("Task description must be 2000 characters or fewer.")
        return description or None

    @validates("status")
    def _validate_status(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or value not in self.STATUSES:
            raise ValueError("Task status must be todo, in_progress, or done.")
        return value

    @validates("priority")
    def _validate_priority(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or value not in self.PRIORITIES:
            raise ValueError("Task priority must be low, medium, or high.")
        return value

    @validates("due_date")
    def _validate_due_date(self, _key: str, value: date | None) -> date | None:
        if value is not None and (not isinstance(value, date) or isinstance(value, datetime)):
            raise ValueError("Task due date must be a calendar date.")
        return value
