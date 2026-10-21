from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from urllib.error import HTTPError
from urllib.parse import urlencode

import pytest

from app.config import get_invitation_email_settings
from app.services.invitation_delivery import (
    DeliveryRejected,
    DeliveryUnknown,
    DevelopmentInvitationOutbox,
)
from app.services.invitation_email import build_invitation_email
from app.services.resend_delivery import (
    MAX_RESPONSE_BYTES,
    RESEND_ENDPOINT,
    ResendDelivery,
)


class FakeResponse:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body
        self.closed = False

    def read(self, _limit: int) -> bytes:
        return self._body

    def close(self) -> None:
        self.closed = True


def settings(**overrides):
    values = {
        "INVITATION_EMAIL_PROVIDER": "resend",
        "INVITATION_EMAIL_FROM": "TeamFlow <no-reply@app.example.test>",
        "RESEND_API_KEY": "re_structurally_valid_test_key",
        "INVITATION_EMAIL_TIMEOUT_SECONDS": "7",
    }
    values.update(overrides)
    return get_invitation_email_settings("production", values)


def message():
    return build_invitation_email(
        invitation_id=9,
        recipient_email="invitee@example.test",
        workspace_name="Research <North>",
        inviter_name="Owner & Lead",
        role="member",
        expires_at=datetime(2026, 1, 3, 14, 5, tzinfo=UTC),
        invitation_url=(
            "https://app.example.test/accept-invitation?"
            f"{urlencode({'token': token_urlsafe(32)})}&x=1"
        ),
    )


def test_email_builder_escapes_context_and_keeps_expiry_and_fallback_url():
    invitation = message()

    assert "Research &lt;North&gt;" in invitation.html
    assert "Owner &amp; Lead" in invitation.html
    assert "January 3, 2026 at 14:05 UTC" in invitation.html
    assert "https://app.example.test/accept-invitation?token=" in invitation.html
    assert "Research <North>" not in invitation.html
    assert "January 3, 2026 at 14:05 UTC" in invitation.text
    assert invitation.invitation_url in invitation.text
    assert "not expecting this invitation" in invitation.text


def test_email_builder_rejects_unsupported_roles():
    with pytest.raises(ValueError):
        build_invitation_email(
            invitation_id=1,
            recipient_email="invitee@example.test",
            workspace_name="Research",
            inviter_name=None,
            role="owner",
            expires_at=datetime.now(UTC) + timedelta(days=1),
            invitation_url="https://app.example.test/accept-invitation",
        )


def test_resend_sends_the_exact_supported_request_shape():
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(200, b'{"id":"email-message-id"}')

    invitation = message()
    result = ResendDelivery(settings(), opener=opener).deliver(invitation)

    assert result.status == "accepted"
    request, timeout = calls[0]
    assert request.full_url == RESEND_ENDPOINT
    assert request.method == "POST"
    assert timeout == 7
    assert request.headers["Authorization"] == "Bearer re_structurally_valid_test_key"
    assert json.loads(request.data) == {
        "from": "TeamFlow <no-reply@app.example.test>",
        "to": ["invitee@example.test"],
        "subject": "You're invited to join a TeamFlow workspace",
        "html": invitation.html,
        "text": invitation.text,
    }


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_resend_classifies_definitive_provider_rejections(status):
    def opener(request, timeout):
        del request, timeout
        raise HTTPError(RESEND_ENDPOINT, status, "provider response", {}, None)

    with pytest.raises(DeliveryRejected):
        ResendDelivery(settings(), opener=opener).deliver(message())


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502])
def test_resend_classifies_uncertain_provider_responses(status):
    def opener(request, timeout):
        del request, timeout
        raise HTTPError(RESEND_ENDPOINT, status, "provider response", {}, None)

    with pytest.raises(DeliveryUnknown):
        ResendDelivery(settings(), opener=opener).deliver(message())


@pytest.mark.parametrize("status", [100, 101, 300, 301, 302])
def test_resend_classifies_informational_and_redirect_responses_as_uncertain(status):
    def opener(request, timeout):
        del request, timeout
        return FakeResponse(status, b"")

    with pytest.raises(DeliveryUnknown):
        ResendDelivery(settings(), opener=opener).deliver(message())


def test_resend_bounds_success_response_body():
    def opener(request, timeout):
        del request, timeout
        return FakeResponse(200, b"x" * (MAX_RESPONSE_BYTES + 1))

    with pytest.raises(DeliveryUnknown):
        ResendDelivery(settings(), opener=opener).deliver(message())


def test_resend_classifies_timeout_as_uncertain():
    def opener(request, timeout):
        del request, timeout
        raise TimeoutError("provider timeout")

    with pytest.raises(DeliveryUnknown):
        ResendDelivery(settings(), opener=opener).deliver(message())


@pytest.mark.parametrize(
    "body",
    [b"{}", b"[]", b'{"id":""}', b'{"id":123}', b'{"id":[]}', b"not-json"],
)
def test_resend_requires_a_nonempty_provider_message_id(body):
    def opener(request, timeout):
        del request, timeout
        return FakeResponse(200, body)

    with pytest.raises(DeliveryUnknown):
        ResendDelivery(settings(), opener=opener).deliver(message())


def test_resend_transport_failure_is_uncertain_without_exposing_details():
    def opener(request, timeout):
        del request, timeout
        raise OSError("secret recipient and provider response")

    with pytest.raises(DeliveryUnknown) as caught:
        ResendDelivery(settings(), opener=opener).deliver(message())
    assert str(caught.value) == ""


def test_development_outbox_is_one_time_and_does_not_send_email():
    outbox = DevelopmentInvitationOutbox()
    invitation = message()
    invitation = replace(invitation, expires_at=datetime.now(UTC) + timedelta(days=1))

    assert outbox.deliver(invitation).status == "development_outbox"
    assert outbox.take(invitation.invitation_id) == invitation.invitation_url
    assert outbox.take(invitation.invitation_id) is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"INVITATION_EMAIL_PROVIDER": "unsupported"}, "INVITATION_EMAIL_PROVIDER"),
        ({"INVITATION_EMAIL_TIMEOUT_SECONDS": "0"}, "INVITATION_EMAIL_TIMEOUT_SECONDS"),
        ({"INVITATION_EMAIL_FROM": "TeamFlow <no-reply@example.invalid>"}, "INVITATION_EMAIL_FROM"),
        ({"RESEND_API_KEY": "replace-with-a-resend-api-key"}, "RESEND_API_KEY"),
        ({"RESEND_API_KEY": "bad\r\nkey"}, "RESEND_API_KEY"),
        ({"RESEND_API_KEY": "x" * 2049}, "RESEND_API_KEY"),
    ],
)
def test_provider_configuration_fails_before_delivery(overrides, message):
    with pytest.raises(RuntimeError, match=message):
        settings(**overrides)


def test_testing_configuration_uses_outbox_without_provider_credentials():
    result = get_invitation_email_settings(
        "testing",
        {
            "INVITATION_EMAIL_PROVIDER": "resend",
            "INVITATION_EMAIL_FROM": "",
            "RESEND_API_KEY": "",
            "INVITATION_EMAIL_TIMEOUT_SECONDS": "10",
        },
    )
    assert result.provider == "resend"
