from __future__ import annotations

import logging
import time
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.models import User

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
LOGOUT_URL = "/api/v1/auth/logout"
CSRF_URL = "/api/v1/auth/csrf"
TEST_PASSWORD = "correct-horse-8"


def csrf_headers(client):
    token_response = client.get(CSRF_URL)
    assert token_response.status_code == 200
    return {"X-CSRF-Token": token_response.get_json()["csrf_token"]}


def register_user(client, email="ada@example.com"):
    response = client.post(
        REGISTER_URL,
        json={"name": "Ada Lovelace", "email": email, "password": TEST_PASSWORD},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201
    return response.get_json()["user"]


def login_user(client, email="ada@example.com", password=TEST_PASSWORD):
    return client.post(
        LOGIN_URL,
        json={"email": email, "password": password},
        headers=csrf_headers(client),
    )


def test_registration_creates_user_with_hashed_password(client):
    response = client.post(
        REGISTER_URL,
        json={
            "name": " Ada Lovelace ",
            "email": " ADA@example.com ",
            "password": TEST_PASSWORD,
        },
        headers=csrf_headers(client),
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["status"] == "created"
    assert payload["user"]["name"] == "Ada Lovelace"
    assert payload["user"]["email"] == "ada@example.com"
    assert "password" not in payload["user"]
    assert "password_hash" not in payload["user"]

    user = db.session.scalar(db.select(User).where(User.email == "ada@example.com"))
    assert user is not None
    assert user.check_password(TEST_PASSWORD)
    assert user.password_hash != TEST_PASSWORD


@pytest.mark.parametrize(
    ("payload", "expected_fields"),
    [
        ({}, {"name", "email", "password"}),
        (
            {"name": " ", "email": "invalid", "password": "short"},
            {"name", "email", "password"},
        ),
        (
            {"name": "A" * 121, "email": "valid@example.com", "password": "long-enough"},
            {"name"},
        ),
    ],
)
def test_registration_rejects_invalid_fields(client, payload, expected_fields):
    response = client.post(REGISTER_URL, json=payload, headers=csrf_headers(client))

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "validation_error"
    assert set(body["fields"]) == expected_fields


def test_registration_requires_json(client):
    response = client.post(
        REGISTER_URL,
        data="not-json",
        content_type="text/plain",
        headers=csrf_headers(client),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_registration_requires_valid_csrf_token(client):
    response = client.post(
        REGISTER_URL,
        json={"name": "Ada", "email": "ada@example.com", "password": TEST_PASSWORD},
        headers={"X-CSRF-Token": "incorrect-token"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_token_invalid"


def test_registration_rejects_duplicate_normalized_email(client):
    register_user(client, "Ada@example.com")
    second_response = client.post(
        REGISTER_URL,
        json={
            "name": "Ada",
            "email": " ada@EXAMPLE.com ",
            "password": TEST_PASSWORD,
        },
        headers=csrf_headers(client),
    )

    assert second_response.status_code == 409
    body = second_response.get_json()
    assert body["error"] == "email_already_registered"
    assert body["fields"] == {"email": "This email is already registered."}


def test_registration_database_failure_rolls_back_and_returns_safe_error(
    client, monkeypatch, caplog
):
    caplog.set_level(logging.ERROR)
    rollback = Mock(wraps=db.session.rollback)

    def fail_query(*_args, **_kwargs):
        raise OperationalError("SELECT users", {}, RuntimeError("sensitive database detail"))

    monkeypatch.setattr(db.session, "scalar", fail_query)
    monkeypatch.setattr(db.session, "rollback", rollback)
    response = client.post(
        REGISTER_URL,
        json={"name": "Ada", "email": "ada@example.com", "password": TEST_PASSWORD},
        headers=csrf_headers(client),
    )

    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert "sensitive database detail" not in body
    assert "SELECT users" not in body
    assert "Traceback" not in body
    assert rollback.called
    assert "OperationalError" in caplog.text


def test_login_succeeds_and_returns_only_safe_user_data(client):
    registered = register_user(client)
    response = login_user(client)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["user"]["id"] == registered["id"]
    assert payload["user"]["email"] == "ada@example.com"
    assert "password" not in payload["user"]
    assert "password_hash" not in payload["user"]


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("ada@example.com", "incorrect-password"),
        ("unknown@example.com", TEST_PASSWORD),
    ],
)
def test_login_uses_same_generic_error_for_invalid_credentials(client, email, password):
    register_user(client)

    response = login_user(client, email=email, password=password)

    assert response.status_code == 401
    assert response.get_json() == {
        "error": "authentication_failed",
        "message": "Invalid email or password.",
    }


@pytest.mark.parametrize(
    ("payload", "expected_fields"),
    [
        ({}, {"email", "password"}),
        ({"email": "not-an-email", "password": TEST_PASSWORD}, {"email"}),
        ({"email": "ada@example.com", "password": ""}, {"password"}),
        ({"email": 42, "password": TEST_PASSWORD}, {"email"}),
    ],
)
def test_login_rejects_malformed_requests(client, payload, expected_fields):
    response = client.post(LOGIN_URL, json=payload, headers=csrf_headers(client))

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "validation_error"
    assert set(body["fields"]) == expected_fields


def test_login_requires_json(client):
    response = client.post(
        LOGIN_URL,
        data="invalid",
        content_type="text/plain",
        headers=csrf_headers(client),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_current_user_rejects_anonymous_access(client):
    response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_failed"


def test_current_user_returns_authenticated_profile(client):
    registered = register_user(client)
    assert login_user(client).status_code == 200

    response = client.get(ME_URL)

    assert response.status_code == 200
    assert response.get_json()["user"]["id"] == registered["id"]
    assert response.get_json()["user"]["email"] == "ada@example.com"
    assert "password_hash" not in response.get_data(as_text=True)


def test_current_user_ignores_another_users_identifier(client):
    first_user = register_user(client, "first@example.com")
    register_user(client, "second@example.com")
    assert login_user(client, "first@example.com").status_code == 200

    response = client.get(f"{ME_URL}?user_id=2")

    assert response.status_code == 200
    assert response.get_json()["user"]["id"] == first_user["id"]


def test_expired_authentication_session_is_rejected(client):
    user_payload = register_user(client)
    with client.session_transaction() as test_session:
        test_session["user_id"] = user_payload["id"]
        test_session["session_version"] = 0
        test_session["auth_issued_at"] = int(time.time()) - 13 * 60 * 60

    response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_failed"


def test_logout_requires_csrf_token_and_invalidates_existing_cookie(client):
    register_user(client)
    pre_login_csrf = csrf_headers(client)["X-CSRF-Token"]
    assert login_user(client).status_code == 200
    old_cookie = client.get_cookie("session")
    assert old_cookie is not None

    invalid_csrf_response = client.post(LOGOUT_URL, headers={"X-CSRF-Token": pre_login_csrf})
    assert invalid_csrf_response.status_code == 403
    assert client.get(ME_URL).status_code == 200

    logout_response = client.post(LOGOUT_URL, headers=csrf_headers(client))
    assert logout_response.status_code == 200
    assert logout_response.get_json() == {"status": "ok", "message": "Logged out."}
    assert client.get(ME_URL).status_code == 401

    client.set_cookie("session", old_cookie.value)
    stale_cookie_response = client.get(ME_URL)
    assert stale_cookie_response.status_code == 401


def test_logout_revokes_all_sessions_for_the_user(client, app):
    register_user(client)
    second_client = app.test_client()
    assert login_user(client).status_code == 200
    assert login_user(second_client).status_code == 200

    logout_response = client.post(LOGOUT_URL, headers=csrf_headers(client))
    other_session_response = second_client.get(ME_URL)

    assert logout_response.status_code == 200
    assert other_session_response.status_code == 401


def test_cors_allows_only_configured_frontend_origin(client):
    allowed = client.get(CSRF_URL, headers={"Origin": "http://localhost:5173"})
    denied = client.get(CSRF_URL, headers={"Origin": "https://untrusted.example"})

    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert allowed.headers["Access-Control-Allow-Credentials"] == "true"
    assert "Access-Control-Allow-Origin" not in denied.headers
