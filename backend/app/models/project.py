from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from ..extensions import db
from .user import utc_now
from .workspace import Workspace

if TYPE_CHECKING:
    from .notification import Notification
    from .task import Task
    from .task_activity import TaskActivity


class Project(db.Model):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_projects_name_nonempty"),
        CheckConstraint(
            "description IS NULL OR length(description) <= 2000",
            name="ck_projects_description_length",
        ),
        Index("ix_projects_workspace_id", "workspace_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
    tasks: Mapped[list[Task]] = relationship(
        "Task",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    activities: Mapped[list[TaskActivity]] = relationship(
        "TaskActivity",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    notifications: Mapped[list[Notification]] = relationship(
        "Notification",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    @validates("name")
    def _validate_name(self, _key: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Project name must be a string.")
        name = value.strip()
        if not name or len(name) > 120:
            raise ValueError("Project name must be between 1 and 120 characters.")
        return name

    @validates("description")
    def _validate_description(self, _key: str, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Project description must be a string.")
        description = value.strip()
        if len(description) > 2000:
            raise ValueError("Project description must be 2000 characters or fewer.")
        return description or None
