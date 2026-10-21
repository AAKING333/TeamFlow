"""Add invitation email delivery outcome.

Revision ID: f0a1b2c3d4e5
Revises: d2c4b91e7a63
Create Date: 2026-10-20 13:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "d2c4b91e7a63"
branch_labels = None
depends_on = None

DELIVERY_CHECK = "ck_workspace_invitations_delivery_status"
INVITATION_INDEXES = (
    (
        "uq_workspace_invitations_pending_email",
        ["workspace_id", "email"],
        True,
        "status = 'pending'",
    ),
    ("ix_workspace_invitations_workspace_status", ["workspace_id", "status"], False, None),
    ("ix_workspace_invitations_inviter_id", ["inviter_id"], False, None),
)


def _drop_invitation_indexes() -> None:
    for index_name, _columns, _unique, _where in INVITATION_INDEXES:
        op.drop_index(index_name, table_name="workspace_invitations")


def _create_invitation_indexes() -> None:
    for index_name, columns, unique, where in INVITATION_INDEXES:
        kwargs = {"unique": unique}
        if where is not None:
            kwargs["sqlite_where"] = sa.text(where)
            kwargs["postgresql_where"] = sa.text(where)
        op.create_index(index_name, "workspace_invitations", columns, **kwargs)


def upgrade():
    if op.get_bind().dialect.name == "sqlite":
        _drop_invitation_indexes()
        with op.batch_alter_table("workspace_invitations", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "delivery_status",
                    sa.String(length=20),
                    nullable=False,
                    server_default=sa.text("'unknown'"),
                )
            )
            batch_op.create_check_constraint(
                DELIVERY_CHECK,
                "delivery_status IN ("
                "'pending', 'accepted', 'rejected', 'unknown', 'development_outbox'"
                ")",
            )
        _create_invitation_indexes()
        return

    op.add_column(
        "workspace_invitations",
        sa.Column(
            "delivery_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    op.create_check_constraint(
        DELIVERY_CHECK,
        "workspace_invitations",
        "delivery_status IN ('pending', 'accepted', 'rejected', 'unknown', 'development_outbox')",
    )


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        _drop_invitation_indexes()
        with op.batch_alter_table("workspace_invitations", recreate="always") as batch_op:
            batch_op.drop_constraint(DELIVERY_CHECK, type_="check")
            batch_op.drop_column("delivery_status")
        _create_invitation_indexes()
        return

    op.drop_constraint(DELIVERY_CHECK, "workspace_invitations", type_="check")
    op.drop_column("workspace_invitations", "delivery_status")
