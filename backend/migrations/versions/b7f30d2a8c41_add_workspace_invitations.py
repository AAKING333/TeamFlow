"""Add secure workspace invitations.

Revision ID: b7f30d2a8c41
Revises: f28c4d9e71a6
Create Date: 2026-10-12 09:45:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "b7f30d2a8c41"
down_revision = "f28c4d9e71a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inviter_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin', 'member')",
            name="ck_workspace_invitations_role",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="ck_workspace_invitations_status",
        ),
        sa.ForeignKeyConstraint(["inviter_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invitations_token_hash"),
    )
    op.create_index(
        "uq_workspace_invitations_pending_email",
        "workspace_invitations",
        ["workspace_id", "email"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_workspace_invitations_workspace_status",
        "workspace_invitations",
        ["workspace_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_invitations_inviter_id",
        "workspace_invitations",
        ["inviter_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_workspace_invitations_inviter_id", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_workspace_status", table_name="workspace_invitations")
    op.drop_index("uq_workspace_invitations_pending_email", table_name="workspace_invitations")
    op.drop_table("workspace_invitations")
