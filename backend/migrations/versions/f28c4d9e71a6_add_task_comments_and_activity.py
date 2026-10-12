"""Add task comments and retained task activity

Revision ID: f28c4d9e71a6
Revises: e71a9c3d5f20
Create Date: 2026-10-11 23:56:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f28c4d9e71a6"
down_revision = "e71a9c3d5f20"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(body)) > 0",
            name="ck_task_comments_body_nonempty",
        ),
        sa.CheckConstraint(
            "length(body) <= 4000",
            name="ck_task_comments_body_length",
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_comments_task_created",
        "task_comments",
        ["task_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_task_comments_author_id", "task_comments", ["author_id"], unique=False)

    op.create_table(
        "task_activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('task_created', 'task_title_changed', "
            "'task_description_changed', 'task_status_changed', "
            "'task_priority_changed', 'task_assignee_changed', "
            "'task_due_date_changed', 'task_deleted')",
            name="ck_task_activities_event_type",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_activities_project_created",
        "task_activities",
        ["project_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_task_activities_task_created",
        "task_activities",
        ["task_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_task_activities_workspace_id",
        "task_activities",
        ["workspace_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_task_activities_workspace_id", table_name="task_activities")
    op.drop_index("ix_task_activities_task_created", table_name="task_activities")
    op.drop_index("ix_task_activities_project_created", table_name="task_activities")
    op.drop_table("task_activities")
    op.drop_index("ix_task_comments_author_id", table_name="task_comments")
    op.drop_index("ix_task_comments_task_created", table_name="task_comments")
    op.drop_table("task_comments")
