from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.inspection import inspect

EXPECTED_REVISION = "f0a1b2c3d4e5"
EXPECTED_DATABASE = "teamflow_migration_check"


def test_migrated_postgres_schema_matches_release_expectations():
    database_url = os.getenv("MIGRATION_DATABASE_URL")
    if not database_url:
        pytest.skip("MIGRATION_DATABASE_URL is only configured in PostgreSQL CI.")

    try:
        url = make_url(database_url)
    except ArgumentError as error:
        pytest.fail(f"MIGRATION_DATABASE_URL is invalid: {error}")
    if url.get_backend_name() != "postgresql" or url.database != EXPECTED_DATABASE:
        pytest.fail(
            "MIGRATION_DATABASE_URL must target the dedicated teamflow_migration_check "
            "PostgreSQL database."
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            server_version = connection.scalar(text("SELECT version()"))
            assert isinstance(server_version, str) and "PostgreSQL 16" in server_version
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                EXPECTED_REVISION
            )

        inspector = inspect(engine)
        notifications_fks = {
            (foreign_key["constrained_columns"][0], foreign_key["options"].get("ondelete"))
            for foreign_key in inspector.get_foreign_keys("notifications")
        }
        assert notifications_fks == {
            ("recipient_id", "CASCADE"),
            ("workspace_id", "CASCADE"),
            ("project_id", "CASCADE"),
            ("task_id", "CASCADE"),
        }
        notification_indexes = {index["name"] for index in inspector.get_indexes("notifications")}
        assert {
            "ix_notifications_recipient_created",
            "ix_notifications_workspace_recipient",
            "uq_notifications_recipient_dedupe_key",
        } <= notification_indexes

        invitation_indexes = {
            index["name"] for index in inspector.get_indexes("workspace_invitations")
        }
        assert "uq_workspace_invitations_pending_email" in invitation_indexes
        invitation_columns = {
            column["name"]: column for column in inspector.get_columns("workspace_invitations")
        }
        assert invitation_columns["delivery_status"]["nullable"] is False
        assert invitation_columns["delivery_status"]["default"] == "'unknown'::character varying"
        invitation_checks = {
            check["name"] for check in inspector.get_check_constraints("workspace_invitations")
        }
        assert "ck_workspace_invitations_delivery_status" in invitation_checks

        activity_task_fk = next(
            foreign_key
            for foreign_key in inspector.get_foreign_keys("task_activities")
            if foreign_key["constrained_columns"] == ["task_id"]
        )
        assert activity_task_fk["options"].get("ondelete") == "SET NULL"
        activity_columns = {
            column["name"]: column for column in inspector.get_columns("task_activities")
        }
        assert activity_columns["task_id"]["nullable"] is True

        timestamp_columns = (
            ("users", "created_at"),
            ("workspaces", "created_at"),
            ("tasks", "created_at"),
            ("task_comments", "created_at"),
            ("task_activities", "created_at"),
            ("workspace_invitations", "expires_at"),
            ("notifications", "created_at"),
            ("notifications", "read_at"),
        )
        for table_name, column_name in timestamp_columns:
            column = next(
                column
                for column in inspector.get_columns(table_name)
                if column["name"] == column_name
            )
            assert column["type"].timezone is True, (table_name, column_name)
    finally:
        engine.dispose()
