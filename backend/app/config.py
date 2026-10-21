from __future__ import annotations

import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from email.utils import getaddresses, parseaddr
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

BASE_DIR = Path(__file__).resolve().parents[1]


def should_load_dotenv(environ: Mapping[str, str]) -> bool:
    """backend/.env is a development convenience; tests and E2E must never read it."""
    if environ.get("FLASK_SKIP_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return environ.get("APP_CONFIG", "").strip().lower() != "testing"


if should_load_dotenv(os.environ):
    # utf-8-sig tolerates the BOM that some Windows editors add; real environment
    # variables always win over values in the file (override=False).
    load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")

INVITATION_EMAIL_PROVIDERS = {"development", "resend", "smtp"}
RESEND_API_KEY_MAX_LENGTH = 2048
PLACEHOLDER_EMAIL_VALUES = {
    "replace-with-a-resend-api-key",
    "your-resend-api-key",
    "re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
}
PLACEHOLDER_SENDER_VALUES = {
    "no-reply@example.invalid",
    "no-reply@your-verified-domain.example",
    "your-address@gmail.com",
}
SENDER_ADDRESS_PATTERN = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")

SMTP_DEFAULT_HOST = "smtp.gmail.com"
SMTP_DEFAULT_PORT = 587
SMTP_SECURITY_MODES = {"starttls", "ssl"}
SMTP_DEFAULT_SECURITY_BY_PORT = {587: "starttls", 465: "ssl"}
SMTP_HOST_MAX_LENGTH = 253
SMTP_USERNAME_MAX_LENGTH = 320
SMTP_PASSWORD_MAX_LENGTH = 256
SMTP_HOST_PATTERN = re.compile(
    r"^[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?"
    r"(?:\.[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?)*$"
)
PLACEHOLDER_SMTP_USERNAME_VALUES = {"your-address@gmail.com", "your-gmail-address@gmail.com"}
PLACEHOLDER_SMTP_PASSWORD_VALUES = {
    "replace-with-a-gmail-app-password",
    "your-gmail-app-password",
    "xxxxxxxxxxxxxxxx",
}


@dataclass(frozen=True)
class InvitationEmailSettings:
    provider: str
    sender: str
    api_key: str = field(repr=False)
    timeout_seconds: int
    smtp_host: str = ""
    smtp_port: int = 0
    smtp_security: str = ""
    smtp_username: str = ""
    smtp_password: str = field(default="", repr=False)


def _has_ascii_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _raw_setting(app_config: dict, name: str) -> str:
    value = app_config.get(name, "")
    return "" if value is None else str(value)


def _validate_smtp_sender(sender: str) -> None:
    # The SMTP envelope sender is the single address inside INVITATION_EMAIL_FROM.
    addresses = getaddresses([sender])
    parsed_sender = parseaddr(sender)[1]
    if len(addresses) != 1 or addresses[0][1] != parsed_sender or not parsed_sender.isascii():
        raise RuntimeError("INVITATION_EMAIL_FROM must be a valid verified sender.")


def _validate_smtp_settings(app_config: dict) -> dict[str, str | int]:
    raw_host = _raw_setting(app_config, "SMTP_HOST")
    raw_port = _raw_setting(app_config, "SMTP_PORT")
    raw_security = _raw_setting(app_config, "SMTP_SECURITY")
    raw_username = _raw_setting(app_config, "SMTP_USERNAME")
    raw_password = _raw_setting(app_config, "SMTP_PASSWORD")
    for value in (raw_host, raw_port, raw_security, raw_username, raw_password):
        if _has_ascii_control(value):
            raise RuntimeError("SMTP settings must not contain control characters.")

    host = raw_host.strip() or SMTP_DEFAULT_HOST
    if len(host) > SMTP_HOST_MAX_LENGTH or not SMTP_HOST_PATTERN.fullmatch(host):
        raise RuntimeError("SMTP_HOST must be a valid hostname.")

    port_text = raw_port.strip() or str(SMTP_DEFAULT_PORT)
    if not (port_text.isascii() and port_text.isdigit()) or not 1 <= int(port_text) <= 65535:
        raise RuntimeError("SMTP_PORT must be an integer from 1 to 65535.")
    port = int(port_text)

    security = raw_security.strip().lower() or SMTP_DEFAULT_SECURITY_BY_PORT.get(port, "")
    if security not in SMTP_SECURITY_MODES:
        raise RuntimeError("SMTP_SECURITY must be starttls or ssl.")
    if SMTP_DEFAULT_SECURITY_BY_PORT.get(port, security) != security:
        raise RuntimeError("SMTP_PORT and SMTP_SECURITY are not a valid combination.")

    username = raw_username.strip()
    if (
        not username
        or len(username) > SMTP_USERNAME_MAX_LENGTH
        or not username.isascii()
        or any(character.isspace() for character in username)
    ):
        raise RuntimeError("SMTP_USERNAME must be configured for the smtp provider.")
    if username.casefold() in PLACEHOLDER_SMTP_USERNAME_VALUES:
        raise RuntimeError("SMTP_USERNAME must not use the example placeholder.")

    # Gmail shows app passwords in space-separated groups; the spaces are not part of it.
    password = raw_password.replace(" ", "")
    if not password or len(password) > SMTP_PASSWORD_MAX_LENGTH or not password.isascii():
        raise RuntimeError("SMTP_PASSWORD must be configured for the smtp provider.")
    if password.casefold() in PLACEHOLDER_SMTP_PASSWORD_VALUES or password.casefold().startswith(
        "replace-with"
    ):
        raise RuntimeError("SMTP_PASSWORD must not use the example placeholder.")

    return {
        "smtp_host": host,
        "smtp_port": port,
        "smtp_security": security,
        "smtp_username": username,
        "smtp_password": password,
    }


def get_invitation_email_settings(config_name: str, app_config: dict) -> InvitationEmailSettings:
    provider = str(app_config.get("INVITATION_EMAIL_PROVIDER", "development")).strip().lower()
    if provider not in INVITATION_EMAIL_PROVIDERS:
        raise RuntimeError("INVITATION_EMAIL_PROVIDER must be development, resend, or smtp.")

    raw_sender = _raw_setting(app_config, "INVITATION_EMAIL_FROM")
    sender = raw_sender.strip()
    api_key = str(app_config.get("RESEND_API_KEY", "")).strip()
    raw_timeout = app_config.get("INVITATION_EMAIL_TIMEOUT_SECONDS", "10")
    try:
        timeout_seconds = int(raw_timeout)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "INVITATION_EMAIL_TIMEOUT_SECONDS must be an integer from 1 to 30."
        ) from error
    if timeout_seconds < 1 or timeout_seconds > 30:
        raise RuntimeError("INVITATION_EMAIL_TIMEOUT_SECONDS must be an integer from 1 to 30.")

    smtp_settings: dict[str, str | int] = {}
    if config_name != "testing" and provider in {"resend", "smtp"}:
        if provider == "smtp" and _has_ascii_control(raw_sender):
            raise RuntimeError("INVITATION_EMAIL_FROM must be a valid verified sender.")
        if not sender or len(sender) > 320 or _has_ascii_control(sender):
            raise RuntimeError("INVITATION_EMAIL_FROM must be a valid verified sender.")
        parsed_sender = parseaddr(sender)[1]
        if (
            not parsed_sender
            or not SENDER_ADDRESS_PATTERN.fullmatch(parsed_sender)
            or parsed_sender.casefold() in PLACEHOLDER_SENDER_VALUES
        ):
            raise RuntimeError("INVITATION_EMAIL_FROM must be a valid verified sender.")
        if provider == "smtp":
            _validate_smtp_sender(sender)
            smtp_settings = _validate_smtp_settings(app_config)
            api_key = ""
        else:
            if not api_key or len(api_key) > RESEND_API_KEY_MAX_LENGTH:
                raise RuntimeError("RESEND_API_KEY must be configured for the resend provider.")
            if _has_ascii_control(api_key) or api_key in PLACEHOLDER_EMAIL_VALUES:
                raise RuntimeError("RESEND_API_KEY must be a valid server-side provider key.")

    return InvitationEmailSettings(
        provider=provider,
        sender=sender,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        **smtp_settings,
    )


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///teamflow.db")
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    INVITATION_EMAIL_PROVIDER = os.getenv("INVITATION_EMAIL_PROVIDER", "development")
    INVITATION_EMAIL_FROM = os.getenv("INVITATION_EMAIL_FROM", "")
    RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = os.getenv("SMTP_PORT", "")
    SMTP_SECURITY = os.getenv("SMTP_SECURITY", "")
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    INVITATION_EMAIL_TIMEOUT_SECONDS = os.getenv("INVITATION_EMAIL_TIMEOUT_SECONDS", "10")
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
    # Tests always use the in-memory outbox and ignore any mail settings in the
    # process environment or in a developer's backend/.env.
    INVITATION_EMAIL_PROVIDER = "development"
    INVITATION_EMAIL_FROM = ""
    RESEND_API_KEY = ""
    SMTP_HOST = ""
    SMTP_PORT = ""
    SMTP_SECURITY = ""
    SMTP_USERNAME = ""
    SMTP_PASSWORD = ""
    INVITATION_EMAIL_TIMEOUT_SECONDS = "10"


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

    settings = get_invitation_email_settings(config_name, app_config)
    if config_name == "production" and settings.provider not in {"resend", "smtp"}:
        raise RuntimeError(
            "Production requires INVITATION_EMAIL_PROVIDER=resend "
            "or INVITATION_EMAIL_PROVIDER=smtp."
        )
    app_config["INVITATION_EMAIL_PROVIDER"] = settings.provider
    app_config["INVITATION_EMAIL_FROM"] = settings.sender
    app_config["RESEND_API_KEY"] = settings.api_key
    app_config["SMTP_HOST"] = settings.smtp_host
    app_config["SMTP_PORT"] = settings.smtp_port
    app_config["SMTP_SECURITY"] = settings.smtp_security
    app_config["SMTP_USERNAME"] = settings.smtp_username
    app_config["SMTP_PASSWORD"] = settings.smtp_password
    app_config["INVITATION_EMAIL_TIMEOUT_SECONDS"] = settings.timeout_seconds
