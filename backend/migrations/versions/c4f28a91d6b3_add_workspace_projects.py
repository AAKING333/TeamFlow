"""Add workspace projects

Revision ID: c4f28a91d6b3
Revises: 8d12c4ab6f90
Create Date: 2026-10-11 20:10:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c4f28a91d6b3"
down_revision = "8d12c4ab6f90"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_projects_name_nonempty"),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 2000",
            name="ck_projects_description_length",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"], unique=False)


def downgrade():
    op.drop_index("ix_projects_workspace_id", table_name="projects")
    op.drop_table("projects")
