from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from ..extensions import db
from .user import utc_now

if TYPE_CHECKING:
    from .project import Project
    from .task import Task
    from .user import User
    from .workspace import Workspace


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "notification_type IN ('task_assigned', 'task_comment')",
            name="ck_notifications_type",
        ),
        CheckConstraint("length(trim(message)) > 0", name="ck_notifications_message_nonempty"),
        CheckConstraint("length(message) <= 240", name="ck_notifications_message_length"),
        Index("ix_notifications_recipient_created", "recipient_id", "created_at", "id"),
        Index("ix_notifications_workspace_recipient", "workspace_id", "recipient_id"),
        Index(
            "uq_notifications_recipient_dedupe_key",
            "recipient_id",
            "dedupe_key",
            unique=True,
        ),
    )

    TYPES: ClassVar[frozenset[str]] = frozenset({"task_assigned", "task_comment"})

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    notification_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(240), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    recipient: Mapped[User] = relationship("User", back_populates="notifications")
    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="notifications")
    project: Mapped[Project | None] = relationship("Project", back_populates="notifications")
    task: Mapped[Task | None] = relationship("Task", back_populates="notifications")

    @validates("notification_type")
    def _validate_type(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or value not in self.TYPES:
            raise ValueError("Unsupported notification type.")
        return value

    @validates("message")
    def _validate_message(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 240:
            raise ValueError("Notification messages must contain 1-240 characters.")
        return value.strip()

    @validates("payload")
    def _validate_payload(self, _key: str, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or value:
            raise ValueError("Notification payloads may not contain arbitrary data.")
        return value
