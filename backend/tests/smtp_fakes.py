"""In-process fake SMTP servers. No sockets are opened and no credentials are real."""

from __future__ import annotations

from datetime import UTC, datetime
from secrets import token_urlsafe
from urllib.parse import urlencode

from app.config import InvitationEmailSettings, get_invitation_email_settings
from app.services.invitation_email import InvitationEmailMessage, build_invitation_email
from app.services.smtp_delivery import SmtpDelivery

TEST_SMTP_PASSWORD = "qwer tyui opas dfgh"
TEST_SMTP_PASSWORD_STRIPPED = "qwertyuiopasdfgh"
TEST_SENDER_ADDRESS = "sender@mail.example.test"
TEST_RECIPIENT = "invitee@example.test"


def smtp_settings(config_name: str = "production", **overrides) -> InvitationEmailSettings:
    values = {
        "INVITATION_EMAIL_PROVIDER": "smtp",
        "INVITATION_EMAIL_FROM": f"TeamFlow <{TEST_SENDER_ADDRESS}>",
        "SMTP_HOST": "smtp.mail.example.test",
        "SMTP_PORT": "587",
        "SMTP_SECURITY": "starttls",
        "SMTP_USERNAME": TEST_SENDER_ADDRESS,
        "SMTP_PASSWORD": TEST_SMTP_PASSWORD,
        "INVITATION_EMAIL_TIMEOUT_SECONDS": "7",
    }
    values.update(overrides)
    return get_invitation_email_settings(config_name, values)


def invitation_message(**overrides) -> InvitationEmailMessage:
    values = {
        "invitation_id": 9,
        "recipient_email": TEST_RECIPIENT,
        "workspace_name": "Research <North>",
        "inviter_name": "Owner & Lead",
        "role": "member",
        "expires_at": datetime(2026, 1, 3, 14, 5, tzinfo=UTC),
        "invitation_url": (
            f"https://app.example.test/accept-invitation?{urlencode({'token': token_urlsafe(32)})}"
        ),
    }
    values.update(overrides)
    return build_invitation_email(**values)


class FakeSmtpServer:
    def __init__(self, harness: FakeSmtpHarness, kind: str, context=None) -> None:
        self.harness = harness
        self.kind = kind
        self.context = context
        self.starttls_context = None
        self.sent_message = None
        self.envelope: tuple[str, list[str]] | None = None

    def _event(self, *event) -> None:
        self.harness.events.append(event)

    def _maybe_fail(self, stage: str) -> None:
        error = self.harness.errors.get(stage)
        if error is not None:
            raise error

    def starttls(self, context=None):
        self._event("starttls")
        self.starttls_context = context
        self._maybe_fail("starttls")
        return (220, b"Ready to start TLS")

    def login(self, user, password):
        self._event("login", user, password)
        self._maybe_fail("login")
        return (235, b"Accepted")

    def send_message(self, message, from_addr=None, to_addrs=None):
        self._event("send_message", from_addr, tuple(to_addrs or ()))
        self.sent_message = message
        self.envelope = (from_addr, list(to_addrs or ()))
        self._maybe_fail("send")
        return self.harness.refused

    def quit(self):
        self._event("quit")
        self._maybe_fail("quit")
        return (221, b"Bye")

    def close(self):
        self._event("close")


class FakeSmtpHarness:
    """Scripted fake for smtplib.SMTP / smtplib.SMTP_SSL, keyed by stage name."""

    def __init__(self, **errors: BaseException) -> None:
        self.errors = errors
        self.refused: dict = {}
        self.events: list[tuple] = []
        self.servers: list[FakeSmtpServer] = []

    def smtp(self, host, port, timeout=None):
        self.events.append(("connect", "SMTP", host, port, timeout))
        server = FakeSmtpServer(self, "SMTP")
        if (error := self.errors.get("connect")) is not None:
            raise error
        self.servers.append(server)
        return server

    def smtp_ssl(self, host, port, timeout=None, context=None):
        self.events.append(("connect", "SMTP_SSL", host, port, timeout))
        server = FakeSmtpServer(self, "SMTP_SSL", context=context)
        if (error := self.errors.get("connect")) is not None:
            raise error
        self.servers.append(server)
        return server

    def delivery(self, settings: InvitationEmailSettings) -> SmtpDelivery:
        return SmtpDelivery(settings, smtp_factory=self.smtp, smtp_ssl_factory=self.smtp_ssl)

    def event_names(self) -> list[str]:
        return [event[0] for event in self.events]
