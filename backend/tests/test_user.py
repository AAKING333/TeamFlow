from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import User


def test_user_normalizes_email_and_sets_timestamps(app):
    user = User(name="Ada Lovelace", email=" ADA@Example.com ")
    user.set_password("correct-horse-8")

    with app.app_context():
        db.session.add(user)
        db.session.commit()

        assert user.email == "ada@example.com"
        assert user.id is not None
        assert user.created_at is not None
        assert user.updated_at is not None
        assert user.session_version == 0


def test_user_password_helpers_store_only_a_hash(app):
    user = User(name="Ada Lovelace", email="ada@example.com")
    user.set_password("correct-horse-8")

    assert user.password_hash != "correct-horse-8"
    assert user.check_password("correct-horse-8")
    assert not user.check_password("incorrect-password")


def test_database_enforces_normalized_email_uniqueness(app):
    first_user = User(name="Ada", email="Ada@example.com")
    second_user = User(name="Another Ada", email=" ada@EXAMPLE.com ")
    first_user.set_password("correct-horse-8")
    second_user.set_password("correct-horse-8")

    with app.app_context():
        db.session.add(first_user)
        db.session.commit()
        db.session.add(second_user)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_database_schema_matches_user_model(app):
    with app.app_context():
        inspector = inspect(db.engine)
        columns = {column["name"]: column for column in inspector.get_columns("users")}

        assert set(columns) == {
            "id",
            "name",
            "email",
            "password_hash",
            "created_at",
            "updated_at",
            "session_version",
        }
        assert columns["name"]["nullable"] is False
        assert columns["name"]["type"].length == 120
        assert columns["email"]["nullable"] is False
        assert columns["email"]["type"].length == 320
        assert columns["password_hash"]["nullable"] is False
        assert columns["password_hash"]["type"].length == 256
        assert columns["session_version"]["nullable"] is False
        assert columns["session_version"]["default"] is not None
        assert columns["created_at"]["nullable"] is False
        assert columns["updated_at"]["nullable"] is False
        assert inspector.get_pk_constraint("users")["constrained_columns"] == ["id"]
        assert any(
            constraint["name"] == "uq_users_email"
            for constraint in inspector.get_unique_constraints("users")
        )
        assert inspector.get_foreign_keys("users") == []
        assert all(index.get("duplicates_constraint") for index in inspector.get_indexes("users"))

        if db.engine.dialect.name == "postgresql":
            assert columns["created_at"]["type"].timezone is True
            assert columns["updated_at"]["type"].timezone is True

            before_insert = datetime.now(UTC)
            user = User(name="UTC Check", email="utc-check@example.test")
            user.set_password("correct-horse-8")
            db.session.add(user)
            db.session.commit()

            created_at_utc = user.created_at.astimezone(UTC)
            updated_at_utc = user.updated_at.astimezone(UTC)
            assert user.created_at.tzinfo is not None
            assert user.updated_at.tzinfo is not None
            assert before_insert <= created_at_utc <= datetime.now(UTC)
            assert before_insert <= updated_at_utc <= datetime.now(UTC)
