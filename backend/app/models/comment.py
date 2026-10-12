from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from ..extensions import db
from .user import utc_now

if TYPE_CHECKING:
    from .task import Task
    from .user import User


class TaskComment(db.Model):
    __tablename__ = "task_comments"
    __table_args__ = (
        CheckConstraint("length(trim(body)) > 0", name="ck_task_comments_body_nonempty"),
        CheckConstraint("length(body) <= 4000", name="ck_task_comments_body_length"),
        Index("ix_task_comments_task_created", "task_id", "created_at"),
        Index("ix_task_comments_author_id", "author_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    task: Mapped[Task] = relationship("Task", back_populates="comments")
    author: Mapped[User] = relationship("User", back_populates="task_comments")

    @validates("body")
    def _validate_body(self, _key: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Comment body must be a string.")
        body = value.strip()
        if not body or len(body) > 4000:
            raise ValueError("Comment body must be between 1 and 4000 characters.")
        return body
