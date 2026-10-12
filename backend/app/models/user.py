from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db

if TYPE_CHECKING:
    from .comment import TaskComment
    from .invitation import WorkspaceInvitation
    from .notification import Notification
    from .task import Task
    from .task_activity import TaskActivity
    from .workspace import Workspace, WorkspaceMembership


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    session_version: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    memberships: Mapped[list[WorkspaceMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sent_invitations: Mapped[list[WorkspaceInvitation]] = relationship(back_populates="inviter")
    owned_workspaces: Mapped[list[Workspace]] = relationship(
        back_populates="owner", foreign_keys="Workspace.owner_id"
    )
    assigned_tasks: Mapped[list[Task]] = relationship("Task", back_populates="assignee")
    task_comments: Mapped[list[TaskComment]] = relationship(
        "TaskComment",
        back_populates="author",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    task_activities: Mapped[list[TaskActivity]] = relationship(
        "TaskActivity",
        back_populates="actor",
        passive_deletes=True,
    )
    notifications: Mapped[list[Notification]] = relationship(
        "Notification",
        back_populates="recipient",
        cascade="all, delete-orphan",
    )

    @staticmethod
    def normalize_email(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Email must be a string.")
        return value.strip().casefold()

    @validates("email")
    def _normalize_email(self, _key: str, value: str) -> str:
        return self.normalize_email(value)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
