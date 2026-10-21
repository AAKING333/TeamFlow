from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def migration_config() -> Config:
    config = Config(str(BACKEND_ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return config


def test_sqlite_delivery_migration_round_trips_schema_and_rows():
    application = create_app("testing")
    with application.app_context():
        command.upgrade(migration_config(), "head")
        inspector = inspect(application.extensions["sqlalchemy"].engine)
        columns = {
            column["name"]: column for column in inspector.get_columns("workspace_invitations")
        }
        assert columns["delivery_status"]["nullable"] is False
        assert columns["delivery_status"]["default"] == "'unknown'"
        assert {index["name"] for index in inspector.get_indexes("workspace_invitations")} == {
            "uq_workspace_invitations_pending_email",
            "ix_workspace_invitations_workspace_status",
            "ix_workspace_invitations_inviter_id",
        }
        assert {
            foreign_key["constrained_columns"][0]
            for foreign_key in inspector.get_foreign_keys("workspace_invitations")
        } == {"workspace_id", "inviter_id"}
        assert {
            check["name"] for check in inspector.get_check_constraints("workspace_invitations")
        } >= {
            "ck_workspace_invitations_role",
            "ck_workspace_invitations_status",
            "ck_workspace_invitations_delivery_status",
        }
        with application.extensions["sqlalchemy"].engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(name, email, password_hash, session_version, created_at, updated_at) "
                    "VALUES ('Owner', 'owner@example.test', 'hash', 0, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO workspaces (name, owner_id, created_at, updated_at) "
                    "VALUES ('Research', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO workspace_invitations "
                    "(workspace_id, email, role, token_hash, expires_at, inviter_id, "
                    "created_at, status) "
                    "VALUES (1, 'new@example.test', 'member', 'hash-token', CURRENT_TIMESTAMP, 1, "
                    "CURRENT_TIMESTAMP, 'pending')"
                )
            )
            assert (
                connection.scalar(
                    text("SELECT delivery_status FROM workspace_invitations WHERE id = 1")
                )
                == "unknown"
            )

        command.downgrade(migration_config(), "d2c4b91e7a63")
        inspector = inspect(application.extensions["sqlalchemy"].engine)
        assert "delivery_status" not in {
            column["name"] for column in inspector.get_columns("workspace_invitations")
        }
        with application.extensions["sqlalchemy"].engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT email FROM workspace_invitations WHERE id = 1"))
                == "new@example.test"
            )
        command.upgrade(migration_config(), "head")
        inspector = inspect(application.extensions["sqlalchemy"].engine)
        assert "delivery_status" in {
            column["name"] for column in inspector.get_columns("workspace_invitations")
        }
        with application.extensions["sqlalchemy"].engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT delivery_status FROM workspace_invitations WHERE id = 1")
                )
                == "unknown"
            )
