from __future__ import annotations

import hashlib
import logging
from smtplib import (
    SMTPAuthenticationError,
    SMTPDataError,
    SMTPRecipientsRefused,
    SMTPServerDisconnected,
)
from urllib.parse import parse_qs, urlparse

import pytest
from smtp_fakes import (
    TEST_SMTP_PASSWORD,
    TEST_SMTP_PASSWORD_STRIPPED,
    FakeSmtpHarness,
    smtp_settings,
)

from app.extensions import db
from app.models import User, Workspace, WorkspaceInvitation, WorkspaceMembership

BASE = "/api/v1"
WORKSPACES = f"{BASE}/workspaces"
TEST_PASSWORD = "workspace-password-8"
INVITEE = "invitee@example.test"


def csrf_headers(client):
    response = client.get(f"{BASE}/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.get_json()["csrf_token"]}


def create_user(email: str) -> User:
    user = User(name=email.split("@")[0], email=email)
    user.set_password(TEST_PASSWORD)
    db.session.add(user)
    db.session.flush()
    return user


def login(client, email: str) -> None:
    response = client.post(
        f"{BASE}/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200


@pytest.fixture(autouse=True)
def smtp_logger_enabled(monkeypatch):
    # migrations/env.py calls logging.config.fileConfig(), which disables every logger
    # created before it ran. Re-enable ours so log assertions work in any test order.
    monkeypatch.setattr(logging.getLogger("app.services.smtp_delivery"), "disabled", False)


@pytest.fixture()
def owner_session(client):
    owner = create_user("owner@example.test")
    workspace = Workspace(name="Smtp Members", owner=owner)
    workspace.memberships.append(WorkspaceMembership(user=owner, role="owner"))
    db.session.add(workspace)
    db.session.commit()
    login(client, owner.email)
    return workspace


def use_smtp(app, **errors):
    harness = FakeSmtpHarness(**errors)
    app.extensions["invitation_delivery"] = harness.delivery(smtp_settings())
    return harness


def invite(client, workspace, email=INVITEE):
    return client.post(
        f"{WORKSPACES}/{workspace.id}/invitations",
        json={"email": email, "role": "member"},
        headers=csrf_headers(client),
    )


def resend(client, workspace, invitation_id):
    return client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/resend",
        headers=csrf_headers(client),
    )


def token_of(harness: FakeSmtpHarness, index: int = -1) -> str:
    message = harness.servers[index].sent_message
    body = message.get_body(("plain",)).get_content()
    url = next(part for part in body.split() if part.startswith("http"))
    return parse_qs(urlparse(url).query)["token"][0]


def test_create_invitation_is_accepted_by_the_smtp_server(client, app, owner_session, caplog):
    caplog.set_level(logging.DEBUG)
    harness = use_smtp(app)

    response = invite(client, owner_session)

    assert response.status_code == 201
    body = response.get_json()
    assert body["delivery_status"] == "accepted"
    assert body["invitation"]["delivery_status"] == "accepted"
    assert "inbox delivery is not guaranteed" in body["message"]
    assert "delivered" not in body["message"].lower()
    assert "token" not in body["invitation"] and "token_hash" not in body["invitation"]
    invitation = db.session.get(WorkspaceInvitation, body["invitation"]["id"])
    assert invitation.delivery_status == "accepted"

    assert harness.event_names() == [
        "connect",
        "starttls",
        "login",
        "send_message",
        "quit",
        "close",
    ]
    token = token_of(harness)
    assert hashlib.sha256(token.encode()).hexdigest() == invitation.token_hash
    sent = harness.servers[0].sent_message
    assert sent["To"] == INVITEE
    assert harness.servers[0].envelope[1] == [INVITEE]
    assert (
        f"http://localhost:5173/accept-invitation?token={token}"
        in sent.get_body(("plain",)).get_content()
    )
    # The token and the link must never appear in the HTTP response or in logs.
    assert token not in response.get_data(as_text=True)
    for secret in (token, TEST_SMTP_PASSWORD, TEST_SMTP_PASSWORD_STRIPPED, INVITEE):
        assert secret not in caplog.text


def test_authentication_failure_returns_the_rejected_contract_with_a_safe_message(
    client, app, owner_session, caplog
):
    caplog.set_level(logging.DEBUG)
    harness = use_smtp(
        app,
        login=SMTPAuthenticationError(
            535, f"5.7.8 bad credentials {TEST_SMTP_PASSWORD_STRIPPED}".encode()
        ),
    )

    response = invite(client, owner_session)

    assert response.status_code == 502
    body = response.get_json()
    assert body["error"] == "invitation_delivery_rejected"
    assert body["delivery_status"] == "rejected"
    assert body["reason"] == "misconfigured"
    assert "misconfigured" in body["message"]
    assert body["invitation"]["delivery_status"] == "rejected"
    raw = response.get_data(as_text=True)
    for secret in (TEST_SMTP_PASSWORD, TEST_SMTP_PASSWORD_STRIPPED, "5.7.8"):
        assert secret not in raw
        assert secret not in caplog.text
    assert INVITEE not in caplog.text
    assert "send_message" not in harness.event_names()
    assert "category=authentication" in caplog.text
    persisted = db.session.scalar(
        db.select(WorkspaceInvitation).where(WorkspaceInvitation.email == INVITEE)
    )
    assert persisted is not None and persisted.delivery_status == "rejected"


def test_recipient_refusal_returns_the_plain_rejected_contract(client, app, owner_session):
    use_smtp(app, send=SMTPRecipientsRefused({INVITEE: (550, b"5.1.1 no such user")}))

    response = invite(client, owner_session)

    assert response.status_code == 502
    body = response.get_json()
    assert body["error"] == "invitation_delivery_rejected"
    assert body["delivery_status"] == "rejected"
    assert "reason" not in body
    assert "misconfigured" not in body["message"]
    assert "no such user" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "errors",
    [
        {"send": SMTPDataError(451, b"4.3.0 try again later")},
        {"send": SMTPRecipientsRefused({INVITEE: (450, b"4.2.1 busy")})},
        {"send": SMTPServerDisconnected("Connection unexpectedly closed")},
        {"connect": TimeoutError("timed out")},
        {"connect": ConnectionRefusedError("refused")},
        {"login": SMTPAuthenticationError(454, b"4.7.0 temporary")},
        {"send": RuntimeError("unexpected")},
    ],
    ids=[
        "4xx-data",
        "4xx-recipient",
        "disconnect",
        "timeout",
        "connection",
        "4xx-auth",
        "unexpected",
    ],
)
def test_transient_and_unexpected_failures_return_the_unconfirmed_contract(
    client, app, owner_session, errors
):
    use_smtp(app, **errors)

    response = invite(client, owner_session)

    assert response.status_code == 503
    body = response.get_json()
    assert body["error"] == "invitation_delivery_unavailable"
    assert body["delivery_status"] == "unknown"
    assert body["invitation"]["delivery_status"] == "unknown"
    assert "reason" not in body


def test_resend_after_a_failure_rotates_the_token_and_succeeds(client, app, owner_session):
    failing = use_smtp(app, send=SMTPDataError(451, b"4.3.0 try again later"))
    created = invite(client, owner_session)
    assert created.status_code == 503
    invitation_id = created.get_json()["invitation"]["id"]
    first_hash = db.session.get(WorkspaceInvitation, invitation_id).token_hash
    first_token = token_of(failing)

    working = use_smtp(app)
    resent = resend(client, owner_session, invitation_id)

    assert resent.status_code == 200
    body = resent.get_json()
    assert body["delivery_status"] == "accepted"
    assert "resent" in body["message"]
    invitation = db.session.get(WorkspaceInvitation, invitation_id)
    assert invitation.delivery_status == "accepted"
    assert invitation.token_hash != first_hash
    assert token_of(working) != first_token
    assert hashlib.sha256(token_of(working).encode()).hexdigest() == invitation.token_hash


def test_resend_reports_a_misconfigured_server_with_the_same_safe_contract(
    client, app, owner_session
):
    use_smtp(app)
    created = invite(client, owner_session)
    invitation_id = created.get_json()["invitation"]["id"]

    use_smtp(app, login=SMTPAuthenticationError(535, b"5.7.8 nope"))
    resent = resend(client, owner_session, invitation_id)

    assert resent.status_code == 502
    body = resent.get_json()
    assert body["error"] == "invitation_delivery_rejected"
    assert body["reason"] == "misconfigured"
    assert db.session.get(WorkspaceInvitation, invitation_id).delivery_status == "rejected"


def test_listing_shows_the_recorded_smtp_delivery_status(client, app, owner_session):
    use_smtp(app)
    invite(client, owner_session)

    listed = client.get(f"{WORKSPACES}/{owner_session.id}/invitations")

    assert listed.status_code == 200
    assert [item["delivery_status"] for item in listed.get_json()["invitations"]] == ["accepted"]
