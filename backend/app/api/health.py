from __future__ import annotations

import logging

from flask import Blueprint, jsonify
from sqlalchemy import text

from ..extensions import db

logger = logging.getLogger(__name__)
health_bp = Blueprint("health", __name__)


@health_bp.get("")
@health_bp.get("/")
def health() -> tuple[dict, int]:
    return jsonify({"status": "ok", "service": "TeamFlow API"}), 200


@health_bp.get("/ready")
def health_ready() -> tuple[dict, int]:
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Database readiness check failed.")
        return (
            jsonify(
                {
                    "status": "error",
                    "service": "TeamFlow API",
                    "error": "database_unavailable",
                    "message": "Database is unavailable.",
                }
            ),
            503,
        )

    return (
        jsonify(
            {
                "status": "ok",
                "service": "TeamFlow API",
                "checks": {"database": "ready"},
            }
        ),
        200,
    )
