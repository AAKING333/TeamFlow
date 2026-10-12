from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import User

auth_bp = Blueprint("auth", __name__)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024
CSRF_HEADER = "X-CSRF-Token"
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))


@auth_bp.before_request
def verify_csrf_token():
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return None

    expected_token = session.get("csrf_token")
    supplied_token = request.headers.get(CSRF_HEADER, "")
    if (
        not isinstance(expected_token, str)
        or not supplied_token
        or not secrets.compare_digest(expected_token, supplied_token)
    ):
        return (
            jsonify(
                {
                    "error": "csrf_token_invalid",
                    "message": "A valid CSRF token is required.",
                }
            ),
            403,
        )
    return None


def validation_error(fields: dict[str, str]):
    return (
        jsonify(
            {
                "error": "validation_error",
                "message": "Please correct the invalid fields.",
                "fields": fields,
            }
        ),
        400,
    )


def duplicate_email_response():
    return (
        jsonify(
            {
                "error": "email_already_registered",
                "message": "An account with this email already exists.",
                "fields": {"email": "This email is already registered."},
            }
        ),
        409,
    )


def is_email_unique_violation(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == "uq_users_email":
        return True
    return "UNIQUE constraint failed: users.email" in str(error.orig)


def user_response(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
    }


def authentication_error():
    return (
        jsonify(
            {
                "error": "authentication_failed",
                "message": "Invalid email or password.",
            }
        ),
        401,
    )


def require_authenticated_user(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any):
        user_id = session.get("user_id")
        version = session.get("session_version")
        issued_at = session.get("auth_issued_at")
        absolute_lifetime = current_app.config["AUTH_SESSION_ABSOLUTE_LIFETIME"].total_seconds()
        now = int(time.time())

        if (
            not isinstance(user_id, int)
            or isinstance(user_id, bool)
            or not isinstance(version, int)
            or isinstance(version, bool)
            or not isinstance(issued_at, int)
            or issued_at > now
            or now - issued_at > absolute_lifetime
        ):
            session.clear()
            return authentication_error()

        user = db.session.get(User, user_id)
        if user is None or user.session_version != version:
            session.clear()
            return authentication_error()

        g.current_user = user
        return view(*args, **kwargs)

    return wrapped


@auth_bp.get("/csrf")
def csrf_token():
    token = session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token

    response = jsonify({"csrf_token": token})
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_bp.post("/register")
def register():
    if not request.is_json:
        return validation_error({"body": "A JSON request body is required."})

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return validation_error({"body": "A valid JSON object is required."})

    fields: dict[str, str] = {}
    raw_name = payload.get("name")
    raw_email = payload.get("email")
    password = payload.get("password")

    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        fields["name"] = "A name is required."
    elif len(name) > 120:
        fields["name"] = "Name must be 120 characters or fewer."

    email_input = raw_email.strip() if isinstance(raw_email, str) else ""
    if not email_input:
        fields["email"] = "An email address is required."
    elif len(email_input) > 320 or not EMAIL_PATTERN.fullmatch(email_input):
        fields["email"] = "Enter a valid email address."

    password_value = password if isinstance(password, str) else ""
    if not isinstance(password, str) or not (
        MIN_PASSWORD_LENGTH <= len(password_value) <= MAX_PASSWORD_LENGTH
    ):
        fields["password"] = (
            f"Password must be between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters."
        )

    if fields:
        return validation_error(fields)

    try:
        email = User.normalize_email(email_input)
        existing_user = db.session.scalar(select(User).where(User.email == email))
        if existing_user is not None:
            return duplicate_email_response()

        user = User(name=name, email=email)
        user.set_password(password_value)
        db.session.add(user)
        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        if isinstance(error, IntegrityError) and is_email_unique_violation(error):
            return duplicate_email_response()
        raise

    return (
        jsonify(
            {
                "status": "created",
                "user": user_response(user),
            }
        ),
        201,
    )


@auth_bp.post("/login")
def login():
    if not request.is_json:
        return validation_error({"body": "A JSON request body is required."})

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return validation_error({"body": "A valid JSON object is required."})

    raw_email = payload.get("email")
    password = payload.get("password")
    email_input = raw_email.strip() if isinstance(raw_email, str) else ""
    fields: dict[str, str] = {}

    if not email_input:
        fields["email"] = "An email address is required."
    elif len(email_input) > 320 or not EMAIL_PATTERN.fullmatch(email_input):
        fields["email"] = "Enter a valid email address."

    if not isinstance(password, str) or not (
        MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH
    ):
        fields["password"] = (
            f"Password must be between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters."
        )
    if fields:
        return validation_error(fields)

    email = User.normalize_email(email_input)
    user = db.session.scalar(select(User).where(User.email == email))
    password_matches = (
        user.check_password(password)
        if user is not None
        else check_password_hash(DUMMY_PASSWORD_HASH, password)
    )
    if user is None or not password_matches:
        return authentication_error()

    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    session["session_version"] = user.session_version
    session["auth_issued_at"] = int(time.time())
    session["csrf_token"] = secrets.token_urlsafe(32)

    return jsonify({"status": "ok", "user": user_response(user)}), 200


@auth_bp.get("/me")
@require_authenticated_user
def current_user():
    return jsonify({"status": "ok", "user": user_response(g.current_user)}), 200


@auth_bp.post("/logout")
def logout():
    user_id = session.get("user_id")
    version = session.get("session_version")
    if isinstance(user_id, int) and not isinstance(user_id, bool):
        try:
            user = db.session.get(User, user_id)
            if user is not None and user.session_version == version:
                user.session_version += 1
                db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise

    session.clear()
    return jsonify({"status": "ok", "message": "Logged out."}), 200
