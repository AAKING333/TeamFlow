from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///teamflow.db")
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    SESSION_REFRESH_EACH_REQUEST = True
    AUTH_SESSION_ABSOLUTE_LIFETIME = timedelta(hours=12)


class DevelopmentConfig(Config):
    DEBUG = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
    ENV = "development"


class TestingConfig(Config):
    SECRET_KEY = "teamflow-test-only-signing-key-not-for-deployment"
    DEBUG = False
    TESTING = True
    ENV = "testing"
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")


class ProductionConfig(Config):
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    DEBUG = False
    ENV = "production"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "")
    SESSION_COOKIE_SECURE = True


def get_config(config_name: str) -> type[Config]:
    mapping = {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "production": ProductionConfig,
    }
    config = mapping.get(config_name.lower())
    if config is None:
        raise ValueError(f"Unknown application configuration: {config_name}")
    return config


def validate_runtime_config(config_name: str, app_config: dict) -> None:
    frontend_origin = app_config.get("FRONTEND_ORIGIN", "")
    try:
        parsed_origin = urlsplit(frontend_origin)
        valid_origin = (
            parsed_origin.scheme in {"http", "https"}
            and bool(parsed_origin.netloc)
            and parsed_origin.username is None
            and parsed_origin.password is None
            and parsed_origin.path in {"", "/"}
            and not parsed_origin.query
            and not parsed_origin.fragment
            and parsed_origin.hostname is not None
            and parsed_origin.port != 0
        )
    except (AttributeError, ValueError):
        valid_origin = False
        parsed_origin = None

    if not valid_origin:
        raise RuntimeError("FRONTEND_ORIGIN must be a specific trusted origin.")

    if config_name == "production":
        secret_key = app_config.get("SECRET_KEY", "")
        if len(secret_key) < 32:
            raise RuntimeError("Production requires a SECRET_KEY of at least 32 characters.")
        if secret_key == "replace-with-a-local-random-secret":
            raise RuntimeError("Production SECRET_KEY must not use the example placeholder.")
        database_url = app_config.get("SQLALCHEMY_DATABASE_URI", "")
        if not database_url:
            raise RuntimeError("Production requires DATABASE_URL to be configured.")
        try:
            database_backend = make_url(database_url).get_backend_name()
        except ArgumentError as error:
            raise RuntimeError("Production requires a valid PostgreSQL DATABASE_URL.") from error
        if database_backend != "postgresql":
            raise RuntimeError("Production requires PostgreSQL in DATABASE_URL.")
        if parsed_origin is None or parsed_origin.scheme != "https":
            raise RuntimeError("Production FRONTEND_ORIGIN must use HTTPS.")
        if app_config.get("DEBUG"):
            raise RuntimeError("Debug mode must be disabled in production.")
