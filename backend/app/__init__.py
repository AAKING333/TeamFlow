from __future__ import annotations

import logging
import os

from flask import Flask, jsonify
from flask_cors import CORS

from .api import register_blueprints
from .config import get_config, validate_runtime_config
from .extensions import db, migrate
from .services.invitation_delivery import DevelopmentInvitationOutbox
from .services.resend_delivery import ResendDelivery
from .services.smtp_delivery import SmtpDelivery

logger = logging.getLogger(__name__)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def handle_not_found(_error):
        return (
            jsonify({"error": "not_found", "message": "The requested resource was not found."}),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return (
            jsonify(
                {
                    "error": "method_not_allowed",
                    "message": "The requested method is not allowed.",
                }
            ),
            405,
        )

    @app.errorhandler(500)
    def handle_internal_server_error(_error):
        return (
            jsonify(
                {
                    "error": "internal_server_error",
                    "message": "An internal server error occurred.",
                }
            ),
            500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Unhandled application exception: %s", type(error).__name__)
        return (
            jsonify({"error": "internal_server_error", "message": "An unexpected error occurred."}),
            500,
        )


def create_app(config_name: str | None = None) -> Flask:
    selected_config = (config_name or os.getenv("APP_CONFIG") or "development").lower()
    app = Flask(__name__)
    app.config.from_object(get_config(selected_config))
    app.config["APP_CONFIG"] = selected_config
    validate_runtime_config(selected_config, app.config)

    # Ensure Alembic sees all mapped tables when it reads db.metadata.
    from importlib import import_module

    import_module(".models", package=__name__)

    db.init_app(app)
    migrate.init_app(app, db)
    if selected_config == "testing" or (
        selected_config == "development"
        and app.config["INVITATION_EMAIL_PROVIDER"] == "development"
    ):
        app.extensions["invitation_delivery"] = DevelopmentInvitationOutbox()
    elif app.config["INVITATION_EMAIL_PROVIDER"] in {"resend", "smtp"}:
        from .config import InvitationEmailSettings

        settings = InvitationEmailSettings(
            provider=app.config["INVITATION_EMAIL_PROVIDER"],
            sender=app.config["INVITATION_EMAIL_FROM"],
            api_key=app.config["RESEND_API_KEY"],
            timeout_seconds=app.config["INVITATION_EMAIL_TIMEOUT_SECONDS"],
            smtp_host=app.config["SMTP_HOST"],
            smtp_port=app.config["SMTP_PORT"],
            smtp_security=app.config["SMTP_SECURITY"],
            smtp_username=app.config["SMTP_USERNAME"],
            smtp_password=app.config["SMTP_PASSWORD"],
        )
        if settings.provider == "smtp":
            app.extensions["invitation_delivery"] = SmtpDelivery(settings)
        else:
            app.extensions["invitation_delivery"] = ResendDelivery(settings)
    CORS(
        app,
        resources={r"/api/*": {"origins": [app.config["FRONTEND_ORIGIN"]]}},
        supports_credentials=True,
        allow_headers=["Content-Type", "X-CSRF-Token"],
        methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        vary_header=True,
    )
    register_blueprints(app)
    register_error_handlers(app)

    logger.info("Created TeamFlow application with configuration '%s'.", selected_config)
    return app
