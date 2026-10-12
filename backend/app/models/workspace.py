from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from ..extensions import db
from .user import User, utc_now

if TYPE_CHECKING:
    from .invitation import WorkspaceInvitation
    from .notification import Notification
    from .project import Project
    from .task_activity import TaskActivity


class Workspace(db.Model):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_workspaces_name_nonempty"),
        Index("ix_workspaces_owner_id", "owner_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    owner: Mapped[User] = relationship(back_populates="owned_workspaces", foreign_keys=[owner_id])
    memberships: Mapped[list[WorkspaceMembership]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    invitations: Mapped[list[WorkspaceInvitation]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    projects: Mapped[list[Project]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    activities: Mapped[list[TaskActivity]] = relationship(
        "TaskActivity",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    notifications: Mapped[list[Notification]] = relationship(
        "Notification",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )

    @validates("name")
    def _validate_name(self, _key: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Workspace name must be a string.")
        name = value.strip()
        if not name or len(name) > 120:
            raise ValueError("Workspace name must be between 1 and 120 characters.")
        return name


class WorkspaceMembership(db.Model):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="ck_workspace_memberships_role",
        ),
        UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_memberships_workspace_user",
        ),
        Index("ix_workspace_memberships_user_id", "user_id"),
        Index(
            "uq_workspace_memberships_single_owner",
            "workspace_id",
            unique=True,
            sqlite_where=text("role = 'owner'"),
            postgresql_where=text("role = 'owner'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
