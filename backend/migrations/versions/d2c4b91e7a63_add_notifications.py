"""Add persistent in-app notifications.

Revision ID: d2c4b91e7a63
Revises: b7f30d2a8c41
Create Date: 2026-10-12 10:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "d2c4b91e7a63"
down_revision = "b7f30d2a8c41"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("notification_type", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=240), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "notification_type IN ('task_assigned', 'task_comment')",
            name="ck_notifications_type",
        ),
        sa.CheckConstraint("length(trim(message)) > 0", name="ck_notifications_message_nonempty"),
        sa.CheckConstraint("length(message) <= 240", name="ck_notifications_message_length"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_id", "created_at", "id"],
    )
    op.create_index(
        "ix_notifications_workspace_recipient",
        "notifications",
        ["workspace_id", "recipient_id"],
    )
    op.create_index(
        "uq_notifications_recipient_dedupe_key",
        "notifications",
        ["recipient_id", "dedupe_key"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_notifications_recipient_dedupe_key", table_name="notifications")
    op.drop_index("ix_notifications_workspace_recipient", table_name="notifications")
    op.drop_index("ix_notifications_recipient_created", table_name="notifications")
    op.drop_table("notifications")
