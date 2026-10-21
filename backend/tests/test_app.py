from __future__ import annotations

import os

import pytest

from app import create_app
from app.config import Config, ProductionConfig


def test_app_factory_creates_an_application():
    application = create_app("testing")

    assert application is not None
    assert application.config["TESTING"] is True
    assert application.config["APP_CONFIG"] == "testing"


def test_testing_configuration_is_loaded():
    application = create_app("testing")

    assert application.config["ENV"] == "testing"
    assert application.config["SQLALCHEMY_DATABASE_URI"] == os.getenv(
        "TEST_DATABASE_URL", "sqlite:///:memory:"
    )


def test_app_factory_uses_app_config_environment(monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "testing")

    application = create_app()

    assert application.config["APP_CONFIG"] == "testing"


def test_app_factory_rejects_unknown_configuration():
    with pytest.raises(ValueError, match="Unknown application configuration"):
        create_app("unknown")


def test_production_session_cookie_and_secret_settings(monkeypatch):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "s" * 40)
    monkeypatch.setattr(ProductionConfig, "INVITATION_EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(
        ProductionConfig, "INVITATION_EMAIL_FROM", "TeamFlow <no-reply@app.example.test>"
    )
    monkeypatch.setattr(ProductionConfig, "RESEND_API_KEY", "re_valid_test_key")
    monkeypatch.setattr(
        ProductionConfig,
        "SQLALCHEMY_DATABASE_URI",
        "postgresql+psycopg://teamflow@localhost/teamflow_prod",
    )
    monkeypatch.setattr(ProductionConfig, "FRONTEND_ORIGIN", "https://app.example.test")
    monkeypatch.setattr(ProductionConfig, "INVITATION_EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(
        ProductionConfig, "INVITATION_EMAIL_FROM", "TeamFlow <no-reply@app.example.test>"
    )
    monkeypatch.setattr(ProductionConfig, "RESEND_API_KEY", "re_valid_test_key")
    monkeypatch.setattr(ProductionConfig, "INVITATION_EMAIL_TIMEOUT_SECONDS", "10")
    monkeypatch.setattr(ProductionConfig, "DEBUG", False)

    application = create_app("production")

    assert application.config["SESSION_COOKIE_SECURE"] is True
    assert application.config["SESSION_COOKIE_HTTPONLY"] is True
    assert application.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert application.config["PERMANENT_SESSION_LIFETIME"].total_seconds() == 1800


def test_production_rejects_missing_or_short_secret(monkeypatch):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "short")
    monkeypatch.setattr(ProductionConfig, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

    with pytest.raises(RuntimeError, match="at least 32 characters"):
        create_app("production")


@pytest.mark.parametrize("provider", [None, "development"])
def test_production_requires_resend_provider(monkeypatch, provider):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "s" * 40)
    if provider is None:
        monkeypatch.delattr(Config, "INVITATION_EMAIL_PROVIDER")
    else:
        monkeypatch.setattr(ProductionConfig, "INVITATION_EMAIL_PROVIDER", provider)
    monkeypatch.setattr(
        ProductionConfig,
        "SQLALCHEMY_DATABASE_URI",
        "postgresql+psycopg://teamflow@localhost/teamflow_prod",
    )
    monkeypatch.setattr(ProductionConfig, "FRONTEND_ORIGIN", "https://app.example.test")
    monkeypatch.setattr(ProductionConfig, "DEBUG", False)

    with pytest.raises(RuntimeError, match="INVITATION_EMAIL_PROVIDER=resend"):
        create_app("production")


def test_production_requires_explicit_database_url_without_sqlite_fallback(monkeypatch):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "s" * 40)
    monkeypatch.setattr(ProductionConfig, "INVITATION_EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(
        ProductionConfig, "INVITATION_EMAIL_FROM", "TeamFlow <no-reply@app.example.test>"
    )
    monkeypatch.setattr(ProductionConfig, "RESEND_API_KEY", "re_valid_test_key")
    monkeypatch.setattr(ProductionConfig, "SQLALCHEMY_DATABASE_URI", "")
    monkeypatch.setattr(ProductionConfig, "DEBUG", False)

    with pytest.raises(RuntimeError, match="requires DATABASE_URL"):
        create_app("production")


@pytest.mark.parametrize(
    ("database_url", "frontend_origin", "message"),
    [
        ("sqlite:///teamflow.db", "https://app.example.test", "requires PostgreSQL"),
        (
            "postgresql+psycopg://teamflow@localhost/teamflow_prod",
            "http://app.example.test",
            "must use HTTPS",
        ),
        (
            "postgresql+psycopg://teamflow@localhost/teamflow_prod",
            "https://app.example.test/path",
            "specific trusted origin",
        ),
    ],
)
def test_production_rejects_unsafe_database_or_frontend_origin(
    monkeypatch, database_url, frontend_origin, message
):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "s" * 40)
    monkeypatch.setattr(ProductionConfig, "INVITATION_EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(
        ProductionConfig, "INVITATION_EMAIL_FROM", "TeamFlow <no-reply@app.example.test>"
    )
    monkeypatch.setattr(ProductionConfig, "RESEND_API_KEY", "re_valid_test_key")
    monkeypatch.setattr(ProductionConfig, "SQLALCHEMY_DATABASE_URI", database_url)
    monkeypatch.setattr(ProductionConfig, "FRONTEND_ORIGIN", frontend_origin)
    monkeypatch.setattr(ProductionConfig, "DEBUG", False)

    with pytest.raises(RuntimeError, match=message):
        create_app("production")
