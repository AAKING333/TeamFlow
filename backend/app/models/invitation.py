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
    from .workspace import Workspace


class WorkspaceInvitation(db.Model):
    __tablename__ = "workspace_invitations"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'member')", name="ck_workspace_invitations_role"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="ck_workspace_invitations_status",
        ),
        UniqueConstraint("token_hash", name="uq_workspace_invitations_token_hash"),
        Index(
            "uq_workspace_invitations_pending_email",
            "workspace_id",
            "email",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_workspace_invitations_workspace_status", "workspace_id", "status"),
        Index("ix_workspace_invitations_inviter_id", "inviter_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inviter_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="invitations")
    inviter: Mapped[User | None] = relationship("User", back_populates="sent_invitations")

    @validates("email")
    def _normalize_email(self, _key: str, value: str) -> str:
        return User.normalize_email(value)

    @validates("role")
    def _validate_role(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or value not in {"admin", "member"}:
            raise ValueError("Invitations cannot grant owner privileges.")
        return value

    @validates("status")
    def _validate_status(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or value not in {
            "pending",
            "accepted",
            "revoked",
            "expired",
        }:
            raise ValueError("Unsupported invitation status.")
        return value
