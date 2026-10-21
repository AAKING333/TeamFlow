from __future__ import annotations

import email
import email.policy
import logging
import os
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPDataError,
    SMTPException,
    SMTPNotSupportedError,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPSenderRefused,
    SMTPServerDisconnected,
)

import pytest
from dotenv import dotenv_values
from smtp_fakes import (
    TEST_RECIPIENT,
    TEST_SENDER_ADDRESS,
    TEST_SMTP_PASSWORD,
    TEST_SMTP_PASSWORD_STRIPPED,
    FakeSmtpHarness,
    invitation_message,
    smtp_settings,
)

from app import create_app
from app.config import (
    BASE_DIR,
    Config,
    DevelopmentConfig,
    ProductionConfig,
    get_invitation_email_settings,
    should_load_dotenv,
)
from app.extensions import db
from app.services.invitation_delivery import (
    DeliveryMisconfigured,
    DeliveryRejected,
    DeliveryUnknown,
    DevelopmentInvitationOutbox,
)
from app.services.smtp_delivery import SmtpDelivery

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def smtp_logger_enabled(monkeypatch):
    # migrations/env.py calls logging.config.fileConfig(), which disables every logger
    # created before it ran. Re-enable ours so log assertions work in any test order.
    monkeypatch.setattr(logging.getLogger("app.services.smtp_delivery"), "disabled", False)


def deliver(harness: FakeSmtpHarness, settings=None, message=None):
    return harness.delivery(settings or smtp_settings()).deliver(message or invitation_message())


# ---------------------------------------------------------------- message construction


def test_message_construction_and_headers():
    harness = FakeSmtpHarness()
    invitation = invitation_message()

    result = deliver(harness, message=invitation)

    assert result.status == "accepted"
    message = harness.servers[0].sent_message
    assert message["From"] == f"TeamFlow <{TEST_SENDER_ADDRESS}>"
    assert message["To"] == TEST_RECIPIENT
    assert message["Subject"] == "You're invited to join a TeamFlow workspace"
    assert message["Date"].datetime.utcoffset() == timedelta(0)
    assert message["Message-ID"].endswith("@mail.example.test>")
    assert message["Bcc"] is None
    assert message["Cc"] is None
    assert message.get_content_type() == "multipart/alternative"
    text = message.get_body(("plain",)).get_content()
    html = message.get_body(("html",)).get_content()
    assert invitation.invitation_url in text
    assert "January 3, 2026 at 14:05 UTC" in text
    assert "Research &lt;North&gt;" in html and "Research <North>" not in html
    assert "Owner &amp; Lead" in html
    assert harness.servers[0].envelope == (TEST_SENDER_ADDRESS, [TEST_RECIPIENT])


def test_serialized_message_has_exactly_the_expected_recipient_headers():
    harness = FakeSmtpHarness()
    deliver(harness)

    raw = harness.servers[0].sent_message.as_bytes(policy=email.policy.SMTP)
    parsed = email.message_from_bytes(raw, policy=email.policy.default)

    assert [value for name, value in parsed.items() if name.lower() in {"to", "cc", "bcc"}] == [
        TEST_RECIPIENT
    ]
    assert raw.count(b"\r\nTo: ") == 1


def test_non_ascii_workspace_names_are_encoded_safely():
    harness = FakeSmtpHarness()
    invitation = invitation_message(workspace_name="Équipe — Café", inviter_name="Zoë")

    assert deliver(harness, message=invitation).status == "accepted"

    raw = harness.servers[0].sent_message.as_bytes(policy=email.policy.SMTP)
    assert raw.isascii()
    body = harness.servers[0].sent_message.get_body(("plain",)).get_content()
    assert "Équipe — Café" in body


# ---------------------------------------------------------------- TLS and protocol order


def test_starttls_flow_verifies_certificates_and_never_logs_in_before_tls():
    harness = FakeSmtpHarness()

    result = deliver(harness)

    assert result.status == "accepted"
    assert harness.events == [
        ("connect", "SMTP", "smtp.mail.example.test", 587, 7),
        ("starttls",),
        ("login", TEST_SENDER_ADDRESS, TEST_SMTP_PASSWORD_STRIPPED),
        ("send_message", TEST_SENDER_ADDRESS, (TEST_RECIPIENT,)),
        ("quit",),
        ("close",),
    ]
    context = harness.servers[0].starttls_context
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_ssl_flow_uses_implicit_tls_with_verified_context_and_no_starttls():
    harness = FakeSmtpHarness()
    settings = smtp_settings(SMTP_PORT="465", SMTP_SECURITY="ssl")

    result = deliver(harness, settings)

    assert result.status == "accepted"
    assert harness.event_names() == ["connect", "login", "send_message", "quit", "close"]
    assert harness.events[0] == ("connect", "SMTP_SSL", "smtp.mail.example.test", 465, 7)
    context = harness.servers[0].context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_default_standard_library_classes_are_used_when_nothing_is_injected(monkeypatch):
    harness = FakeSmtpHarness()
    monkeypatch.setattr(smtplib, "SMTP", harness.smtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", harness.smtp_ssl)

    assert SmtpDelivery(smtp_settings()).deliver(invitation_message()).status == "accepted"
    assert (
        SmtpDelivery(smtp_settings(SMTP_PORT="465", SMTP_SECURITY="ssl"))
        .deliver(invitation_message())
        .status
        == "accepted"
    )

    assert [event[1] for event in harness.events if event[0] == "connect"] == [
        "SMTP",
        "SMTP_SSL",
    ]


def test_timeout_is_applied_to_the_connection_and_each_message_uses_its_own_connection():
    harness = FakeSmtpHarness()
    delivery = harness.delivery(smtp_settings(INVITATION_EMAIL_TIMEOUT_SECONDS="3"))

    delivery.deliver(invitation_message())
    delivery.deliver(invitation_message())

    connects = [event for event in harness.events if event[0] == "connect"]
    assert [event[4] for event in connects] == [3, 3]
    assert len(harness.servers) == 2
    assert harness.event_names().count("quit") == 2
    assert harness.event_names().count("close") == 2


# ---------------------------------------------------------------- outcome classification

FAILURES = [
    # (stage, error, expected outcome class, expected log category)
    (
        "login",
        SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted"),
        DeliveryMisconfigured,
        "authentication",
    ),
    (
        "login",
        SMTPAuthenticationError(534, b"5.7.9 Application-specific password required"),
        DeliveryMisconfigured,
        "authentication",
    ),
    (
        "login",
        SMTPAuthenticationError(454, b"4.7.0 Temporary authentication failure"),
        DeliveryUnknown,
        "authentication_deferred",
    ),
    (
        "login",
        SMTPNotSupportedError("SMTP AUTH extension not supported by server."),
        DeliveryMisconfigured,
        "capability",
    ),
    (
        "starttls",
        SMTPNotSupportedError("STARTTLS extension not supported by server."),
        DeliveryMisconfigured,
        "capability",
    ),
    (
        "send",
        SMTPNotSupportedError("SMTPUTF8 not supported by server"),
        DeliveryRejected,
        "unsupported_message",
    ),
    (
        "send",
        SMTPRecipientsRefused({TEST_RECIPIENT: (550, b"5.1.1 no such user")}),
        DeliveryRejected,
        "recipient_refused",
    ),
    (
        "send",
        SMTPRecipientsRefused({TEST_RECIPIENT: (553, b"5.1.3 bad address")}),
        DeliveryRejected,
        "recipient_refused",
    ),
    (
        "send",
        SMTPRecipientsRefused({TEST_RECIPIENT: (450, b"4.2.1 mailbox busy")}),
        DeliveryUnknown,
        "recipient_deferred",
    ),
    (
        "send",
        SMTPSenderRefused(553, b"5.7.1 sender not allowed", TEST_SENDER_ADDRESS),
        DeliveryRejected,
        "sender_refused",
    ),
    (
        "send",
        SMTPSenderRefused(451, b"4.3.0 try later", TEST_SENDER_ADDRESS),
        DeliveryUnknown,
        "sender_deferred",
    ),
    (
        "send",
        SMTPDataError(554, b"5.7.0 rejected as policy violation"),
        DeliveryRejected,
        "data_rejected",
    ),
    ("send", SMTPDataError(552, b"5.3.4 message too large"), DeliveryRejected, "data_rejected"),
    (
        "send",
        SMTPDataError(451, b"4.3.0 local error in processing"),
        DeliveryUnknown,
        "transient_response",
    ),
    (
        "send",
        SMTPResponseException(550, b"5.0.0 permanent"),
        DeliveryRejected,
        "permanent_response",
    ),
    (
        "send",
        SMTPResponseException(421, b"4.7.0 service not available"),
        DeliveryUnknown,
        "transient_response",
    ),
    ("connect", SMTPConnectError(421, b"4.3.2 service not available"), DeliveryUnknown, "connect"),
    ("connect", SMTPConnectError(554, b"5.5.1 no service"), DeliveryUnknown, "connect"),
    (
        "connect",
        SMTPServerDisconnected("Connection unexpectedly closed"),
        DeliveryUnknown,
        "disconnected",
    ),
    ("send", SMTPServerDisconnected("Server not connected"), DeliveryUnknown, "disconnected"),
    ("connect", TimeoutError("timed out"), DeliveryUnknown, "timeout"),
    ("send", TimeoutError("timed out"), DeliveryUnknown, "timeout"),
    ("connect", TimeoutError("timed out"), DeliveryUnknown, "timeout"),
    ("connect", ConnectionRefusedError("refused"), DeliveryUnknown, "connection"),
    ("send", ConnectionResetError("reset"), DeliveryUnknown, "connection"),
    ("connect", socket.gaierror(11001, "getaddrinfo failed"), DeliveryUnknown, "dns"),
    ("starttls", ssl.SSLCertVerificationError("certificate verify failed"), DeliveryUnknown, "tls"),
    ("starttls", ssl.SSLError("handshake failure"), DeliveryUnknown, "tls"),
    ("send", OSError("network down"), DeliveryUnknown, "connection"),
    ("send", SMTPException("generic smtp failure"), DeliveryUnknown, "smtp_error"),
    ("send", RuntimeError("unexpected"), DeliveryUnknown, "unexpected"),
]


@pytest.mark.parametrize(
    ("stage", "error", "expected", "category"),
    FAILURES,
    ids=[f"{case[0]}-{type(case[1]).__name__}-{case[3]}" for case in FAILURES],
)
def test_smtp_failures_are_classified_without_leaking_details(
    stage, error, expected, category, caplog
):
    caplog.set_level(logging.DEBUG)
    harness = FakeSmtpHarness(**{stage: error})
    invitation = invitation_message()

    with pytest.raises(Exception) as caught:
        deliver(harness, message=invitation)

    assert type(caught.value) is expected
    assert str(caught.value) == ""
    assert caught.value.__cause__ is None
    assert f"category={category}" in caplog.text
    assert "send_message" not in harness.event_names() or stage in {"send"}
    if stage != "connect":
        # Whatever the outcome, the connection is always quit and closed.
        assert harness.event_names()[-2:] == ["quit", "close"]
    forbidden = [
        TEST_SMTP_PASSWORD,
        TEST_SMTP_PASSWORD_STRIPPED,
        TEST_RECIPIENT,
        invitation.invitation_url,
        invitation.invitation_url.split("token=")[1],
        invitation.text[:30],
        "5.7.8",
        "no such user",
    ]
    log_and_exception = caplog.text + repr(caught.value)
    for value in forbidden:
        assert value not in log_and_exception


def test_authentication_failure_does_not_send_the_message():
    harness = FakeSmtpHarness(login=SMTPAuthenticationError(535, b"nope"))

    with pytest.raises(DeliveryMisconfigured):
        deliver(harness)

    assert harness.event_names() == ["connect", "starttls", "login", "quit", "close"]


def test_server_that_cannot_do_tls_is_never_sent_credentials():
    harness = FakeSmtpHarness(starttls=SMTPNotSupportedError("no STARTTLS"))

    with pytest.raises(DeliveryMisconfigured):
        deliver(harness)

    assert "login" not in harness.event_names()
    assert "send_message" not in harness.event_names()


@pytest.mark.parametrize("quit_error", [SMTPServerDisconnected("gone"), RuntimeError("boom")])
def test_quit_failure_after_server_acceptance_does_not_change_the_outcome(quit_error):
    harness = FakeSmtpHarness(quit=quit_error)

    assert deliver(harness).status == "accepted"
    assert harness.event_names()[-2:] == ["quit", "close"]


def test_refused_recipient_mapping_returned_by_the_server_is_a_rejection(caplog):
    caplog.set_level(logging.DEBUG)
    harness = FakeSmtpHarness()
    harness.refused = {TEST_RECIPIENT: (550, b"no such user")}

    with pytest.raises(DeliveryRejected):
        deliver(harness)

    assert TEST_RECIPIENT not in caplog.text


def test_accepted_delivery_logs_nothing_sensitive(caplog):
    caplog.set_level(logging.DEBUG)
    invitation = invitation_message()

    deliver(FakeSmtpHarness(), message=invitation)

    for value in (
        TEST_SMTP_PASSWORD,
        TEST_SMTP_PASSWORD_STRIPPED,
        TEST_RECIPIENT,
        TEST_SENDER_ADDRESS,
        invitation.invitation_url,
        invitation.text[:30],
    ):
        assert value not in caplog.text


# ---------------------------------------------------------------- header injection


@pytest.mark.parametrize(
    "recipient",
    [
        "victim@example.test\r\nBcc: attacker@example.test",
        "victim@example.test\nBcc: attacker@example.test",
        "victim@example.test\rBcc: attacker@example.test",
        "victim@example.test\x00",
        "victim@example.test,attacker@example.test",
        "Victim <victim@example.test>",
        "víctim@example.test",
        "",
    ],
)
def test_unsafe_recipients_are_rejected_before_any_connection(recipient):
    harness = FakeSmtpHarness()
    invitation = replace(invitation_message(), recipient_email=recipient)

    with pytest.raises(DeliveryRejected):
        deliver(harness, message=invitation)

    assert harness.events == []


@pytest.mark.parametrize(
    "subject",
    ["Hello\r\nBcc: attacker@example.test", "Hello\nBcc: a@b.test", "Hello\x00", ""],
)
def test_unsafe_subjects_are_rejected_before_any_connection(subject):
    harness = FakeSmtpHarness()
    invitation = replace(invitation_message(), subject=subject)

    with pytest.raises(DeliveryRejected):
        deliver(harness, message=invitation)

    assert harness.events == []


@pytest.mark.parametrize(
    "sender",
    [
        f"TeamFlow <{TEST_SENDER_ADDRESS}>\r\nBcc: attacker@example.test",
        f"{TEST_SENDER_ADDRESS}\nX-Injected: yes",
    ],
)
def test_unsafe_senders_are_rejected_before_any_connection(sender):
    harness = FakeSmtpHarness()
    settings = replace(smtp_settings(), sender=sender)

    with pytest.raises(DeliveryRejected):
        deliver(harness, settings)

    assert harness.events == []


# ---------------------------------------------------------------- secret redaction


def test_settings_representation_never_contains_the_password():
    settings = smtp_settings()

    assert settings.smtp_password == TEST_SMTP_PASSWORD_STRIPPED
    assert TEST_SMTP_PASSWORD_STRIPPED not in repr(settings)
    assert TEST_SMTP_PASSWORD not in repr(settings)
    assert TEST_SMTP_PASSWORD_STRIPPED not in str(settings)


# ---------------------------------------------------------------- startup validation


def test_defaults_target_gmail_with_starttls_on_587():
    settings = smtp_settings(SMTP_HOST="", SMTP_PORT="", SMTP_SECURITY="")

    assert (settings.smtp_host, settings.smtp_port, settings.smtp_security) == (
        "smtp.gmail.com",
        587,
        "starttls",
    )


def test_port_465_defaults_to_implicit_tls():
    settings = smtp_settings(SMTP_PORT="465", SMTP_SECURITY="")

    assert (settings.smtp_port, settings.smtp_security) == (465, "ssl")


def test_gmail_app_password_spaces_are_stripped_and_values_are_trimmed():
    settings = smtp_settings(
        SMTP_PASSWORD="  abcd efgh ijkl mnop  ",
        SMTP_USERNAME=f"  {TEST_SENDER_ADDRESS}  ",
        SMTP_SECURITY=" STARTTLS ",
    )

    assert settings.smtp_password == "abcdefghijklmnop"
    assert settings.smtp_username == TEST_SENDER_ADDRESS
    assert settings.smtp_security == "starttls"


def test_nonstandard_port_requires_an_explicit_security_mode():
    with pytest.raises(RuntimeError, match="SMTP_SECURITY"):
        smtp_settings(SMTP_PORT="2525", SMTP_SECURITY="")

    assert smtp_settings(SMTP_PORT="2525", SMTP_SECURITY="starttls").smtp_port == 2525
    assert smtp_settings(SMTP_PORT="2465", SMTP_SECURITY="ssl").smtp_security == "ssl"


INVALID_SETTINGS = [
    ({"SMTP_USERNAME": ""}, "SMTP_USERNAME"),
    ({"SMTP_USERNAME": "has space@example.test"}, "SMTP_USERNAME"),
    ({"SMTP_USERNAME": "u" * 321}, "SMTP_USERNAME"),
    ({"SMTP_USERNAME": "ünïcode@example.test"}, "SMTP_USERNAME"),
    ({"SMTP_USERNAME": "your-address@gmail.com"}, "SMTP_USERNAME"),
    ({"SMTP_PASSWORD": ""}, "SMTP_PASSWORD"),
    ({"SMTP_PASSWORD": "    "}, "SMTP_PASSWORD"),
    ({"SMTP_PASSWORD": "replace-with-a-gmail-app-password"}, "SMTP_PASSWORD"),
    ({"SMTP_PASSWORD": "replace-with-anything-else"}, "SMTP_PASSWORD"),
    ({"SMTP_PASSWORD": "xxxx xxxx xxxx xxxx"}, "SMTP_PASSWORD"),
    ({"SMTP_PASSWORD": "p" * 257}, "SMTP_PASSWORD"),
    ({"SMTP_PASSWORD": "pässwörd-with-unicode"}, "SMTP_PASSWORD"),
    ({"INVITATION_EMAIL_FROM": ""}, "INVITATION_EMAIL_FROM"),
    ({"INVITATION_EMAIL_FROM": "TeamFlow <no-reply@example.invalid>"}, "INVITATION_EMAIL_FROM"),
    ({"INVITATION_EMAIL_FROM": "TeamFlow <your-address@gmail.com>"}, "INVITATION_EMAIL_FROM"),
    ({"INVITATION_EMAIL_FROM": "not-an-address"}, "INVITATION_EMAIL_FROM"),
    (
        {"INVITATION_EMAIL_FROM": "A <a@mail.example.test>, B <b@mail.example.test>"},
        "INVITATION_EMAIL_FROM",
    ),
    ({"INVITATION_EMAIL_FROM": "TeamFlow <sénder@mail.example.test>"}, "INVITATION_EMAIL_FROM"),
    ({"SMTP_HOST": "bad host"}, "SMTP_HOST"),
    ({"SMTP_HOST": "smtp.example.test:587"}, "SMTP_HOST"),
    ({"SMTP_HOST": "smtp.example.test/path"}, "SMTP_HOST"),
    ({"SMTP_HOST": "h" * 254}, "SMTP_HOST"),
    ({"SMTP_HOST": "-leading.example.test"}, "SMTP_HOST"),
    ({"SMTP_PORT": "0"}, "SMTP_PORT"),
    ({"SMTP_PORT": "65536"}, "SMTP_PORT"),
    ({"SMTP_PORT": "-1"}, "SMTP_PORT"),
    ({"SMTP_PORT": "abc"}, "SMTP_PORT"),
    ({"SMTP_PORT": "5_87"}, "SMTP_PORT"),
    ({"SMTP_PORT": "587.0"}, "SMTP_PORT"),
    ({"SMTP_SECURITY": "none"}, "SMTP_SECURITY"),
    ({"SMTP_SECURITY": "plain"}, "SMTP_SECURITY"),
    ({"SMTP_SECURITY": "tls"}, "SMTP_SECURITY"),
    ({"SMTP_PORT": "587", "SMTP_SECURITY": "ssl"}, "SMTP_PORT and SMTP_SECURITY"),
    ({"SMTP_PORT": "465", "SMTP_SECURITY": "starttls"}, "SMTP_PORT and SMTP_SECURITY"),
    ({"INVITATION_EMAIL_TIMEOUT_SECONDS": "0"}, "INVITATION_EMAIL_TIMEOUT_SECONDS"),
    ({"INVITATION_EMAIL_TIMEOUT_SECONDS": "31"}, "INVITATION_EMAIL_TIMEOUT_SECONDS"),
]


@pytest.mark.parametrize(("overrides", "match"), INVALID_SETTINGS)
def test_smtp_startup_validation_rejects_unsafe_configuration(overrides, match):
    with pytest.raises(RuntimeError, match=match):
        smtp_settings(**overrides)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("SMTP_HOST", "smtp.example.test\r\nX-Injected: yes"),
        ("SMTP_HOST", "smtp.example.test\n"),
        ("SMTP_USERNAME", "user\r\nRCPT TO:<a@b.test>"),
        ("SMTP_USERNAME", "user\x00@example.test"),
        ("SMTP_PASSWORD", "pass\r\nword"),
        ("SMTP_PASSWORD", "pass\tword"),
        ("SMTP_PASSWORD", "password\n"),
        ("SMTP_PORT", "587\r\n"),
        ("SMTP_SECURITY", "starttls\n"),
        ("INVITATION_EMAIL_FROM", f"TeamFlow <{TEST_SENDER_ADDRESS}>\r\nBcc: a@b.test"),
        ("INVITATION_EMAIL_FROM", f"TeamFlow <{TEST_SENDER_ADDRESS}>\n"),
        ("INVITATION_EMAIL_FROM", f"Team\x07Flow <{TEST_SENDER_ADDRESS}>"),
    ],
)
def test_control_characters_are_rejected_in_every_smtp_setting(field, value):
    with pytest.raises(RuntimeError):
        smtp_settings(**{field: value})


def test_validation_errors_never_echo_the_password_or_the_sender():
    secret_password = "sentinel-secret-password-value"
    sender = "sentinel.sender@mail.example.test"
    bad_inputs = [
        {"SMTP_PASSWORD": secret_password + "p" * 300},
        {"SMTP_PASSWORD": secret_password + "\r\nX: y"},
        {"SMTP_PASSWORD": secret_password + "é"},
        {"SMTP_PORT": "0"},
        {"SMTP_HOST": "bad host"},
        {"SMTP_SECURITY": "none"},
        {"SMTP_PORT": "587", "SMTP_SECURITY": "ssl"},
        {"SMTP_USERNAME": ""},
        {"INVITATION_EMAIL_FROM": sender + "\r\nBcc: x@y.test"},
        {"INVITATION_EMAIL_FROM": f"A <{sender}>, B <{sender}>"},
        {"INVITATION_EMAIL_FROM": f"TeamFlow <{sender.replace('e', 'é', 1)}>"},
        {"INVITATION_EMAIL_FROM": "no-at-sign-sentinel.sender"},
    ]
    for overrides in bad_inputs:
        values = {
            "SMTP_PASSWORD": secret_password,
            "INVITATION_EMAIL_FROM": f"TeamFlow <{sender}>",
            **overrides,
        }
        with pytest.raises(RuntimeError) as caught:
            smtp_settings(**values)
        assert "sentinel" not in str(caught.value)
        assert secret_password not in str(caught.value)


def test_testing_configuration_ignores_smtp_settings_entirely():
    settings = get_invitation_email_settings(
        "testing",
        {
            "INVITATION_EMAIL_PROVIDER": "smtp",
            "INVITATION_EMAIL_FROM": "",
            "SMTP_HOST": "bad host",
            "SMTP_PORT": "not-a-port",
            "SMTP_SECURITY": "none",
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "leaked-secret",
            "INVITATION_EMAIL_TIMEOUT_SECONDS": "10",
        },
    )

    assert settings.provider == "smtp"
    assert (settings.smtp_host, settings.smtp_port, settings.smtp_password) == ("", 0, "")


def test_unknown_providers_are_still_rejected():
    with pytest.raises(RuntimeError, match="INVITATION_EMAIL_PROVIDER"):
        smtp_settings(INVITATION_EMAIL_PROVIDER="sendmail")


# ---------------------------------------------------------------- application wiring


def patch_production(monkeypatch, **overrides):
    values = {
        "SECRET_KEY": "s" * 40,
        "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://teamflow@localhost/teamflow_prod",
        "FRONTEND_ORIGIN": "https://app.example.test",
        "DEBUG": False,
        "INVITATION_EMAIL_PROVIDER": "smtp",
        "INVITATION_EMAIL_FROM": f"TeamFlow <{TEST_SENDER_ADDRESS}>",
        "SMTP_HOST": "smtp.mail.example.test",
        "SMTP_PORT": "587",
        "SMTP_SECURITY": "starttls",
        "SMTP_USERNAME": TEST_SENDER_ADDRESS,
        "SMTP_PASSWORD": TEST_SMTP_PASSWORD,
        "INVITATION_EMAIL_TIMEOUT_SECONDS": "10",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setattr(ProductionConfig, name, value, raising=False)


def test_production_accepts_the_smtp_provider_and_never_uses_the_outbox(monkeypatch):
    patch_production(monkeypatch)

    application = create_app("production")

    delivery = application.extensions["invitation_delivery"]
    assert isinstance(delivery, SmtpDelivery)
    assert not isinstance(delivery, DevelopmentInvitationOutbox)
    assert application.config["SMTP_PASSWORD"] == TEST_SMTP_PASSWORD_STRIPPED
    assert application.config["INVITATION_EMAIL_PROVIDER"] == "smtp"


@pytest.mark.parametrize(
    "overrides",
    [
        {"SMTP_PASSWORD": ""},
        {"SMTP_PASSWORD": "replace-with-a-gmail-app-password"},
        {"SMTP_USERNAME": ""},
        {"SMTP_PORT": "587", "SMTP_SECURITY": "ssl"},
        {"INVITATION_EMAIL_FROM": "TeamFlow <no-reply@example.invalid>"},
    ],
)
def test_production_smtp_misconfiguration_fails_before_the_database_is_initialized(
    monkeypatch, overrides
):
    patch_production(monkeypatch, **overrides)

    def database_must_not_be_initialized(*_args, **_kwargs):
        raise AssertionError("db.init_app ran before email validation")

    monkeypatch.setattr(db, "init_app", database_must_not_be_initialized)

    with pytest.raises(RuntimeError):
        create_app("production")


def test_production_still_never_falls_back_to_the_outbox(monkeypatch):
    patch_production(monkeypatch, INVITATION_EMAIL_PROVIDER="development")

    with pytest.raises(RuntimeError, match="INVITATION_EMAIL_PROVIDER=smtp"):
        create_app("production")


def test_development_with_the_smtp_provider_uses_smtp_delivery(monkeypatch):
    monkeypatch.setattr(DevelopmentConfig, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(DevelopmentConfig, "INVITATION_EMAIL_PROVIDER", "smtp", raising=False)
    monkeypatch.setattr(
        DevelopmentConfig, "INVITATION_EMAIL_FROM", f"TeamFlow <{TEST_SENDER_ADDRESS}>"
    )
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY"):
        monkeypatch.setattr(DevelopmentConfig, name, "")
    monkeypatch.setattr(DevelopmentConfig, "SMTP_USERNAME", TEST_SENDER_ADDRESS)
    monkeypatch.setattr(DevelopmentConfig, "SMTP_PASSWORD", TEST_SMTP_PASSWORD)

    application = create_app("development")

    delivery = application.extensions["invitation_delivery"]
    assert isinstance(delivery, SmtpDelivery)
    # SMTP_HOST/PORT/SECURITY were blank, so the Gmail defaults apply.
    assert application.config["SMTP_HOST"] == "smtp.gmail.com"
    assert application.config["SMTP_PORT"] == 587
    assert application.config["SMTP_SECURITY"] == "starttls"


def test_development_without_a_provider_keeps_the_explicit_outbox(monkeypatch):
    monkeypatch.setattr(DevelopmentConfig, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(DevelopmentConfig, "INVITATION_EMAIL_PROVIDER", "development")

    application = create_app("development")

    assert isinstance(application.extensions["invitation_delivery"], DevelopmentInvitationOutbox)


def test_development_smtp_misconfiguration_is_a_startup_error(monkeypatch):
    monkeypatch.setattr(DevelopmentConfig, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(DevelopmentConfig, "INVITATION_EMAIL_PROVIDER", "smtp", raising=False)
    monkeypatch.setattr(
        DevelopmentConfig, "INVITATION_EMAIL_FROM", f"TeamFlow <{TEST_SENDER_ADDRESS}>"
    )
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY"):
        monkeypatch.setattr(DevelopmentConfig, name, "")
    monkeypatch.setattr(DevelopmentConfig, "SMTP_USERNAME", TEST_SENDER_ADDRESS)
    monkeypatch.setattr(DevelopmentConfig, "SMTP_PASSWORD", "")

    with pytest.raises(RuntimeError, match="SMTP_PASSWORD"):
        create_app("development")


def test_testing_configuration_forces_the_outbox_even_with_smtp_class_settings(monkeypatch):
    monkeypatch.setattr(Config, "INVITATION_EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(Config, "SMTP_PASSWORD", "leaked-secret-from-environment")
    monkeypatch.setattr(Config, "SMTP_USERNAME", "leaked@example.test")

    application = create_app("testing")

    assert isinstance(application.extensions["invitation_delivery"], DevelopmentInvitationOutbox)
    assert application.config["INVITATION_EMAIL_PROVIDER"] == "development"
    assert application.config["SMTP_PASSWORD"] == ""
    assert application.config["SMTP_USERNAME"] == ""


def test_testing_app_ignores_smtp_variables_in_the_process_environment():
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("SMTP_", "INVITATION_EMAIL", "RESEND_", "DATABASE_URL"))
    }
    environment.update(
        {
            "TEST_DATABASE_URL": "sqlite:///:memory:",
            "FLASK_SKIP_DOTENV": "1",
            "INVITATION_EMAIL_PROVIDER": "smtp",
            "INVITATION_EMAIL_FROM": "Real <real.person@example.test>",
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_USERNAME": "real.person@example.test",
            "SMTP_PASSWORD": "leaked-environment-secret",
            "RESEND_API_KEY": "re_leaked_environment_key",
        }
    )
    environment.pop("APP_CONFIG", None)
    script = (
        "from app import create_app\n"
        "app = create_app('testing')\n"
        "delivery = type(app.extensions['invitation_delivery']).__name__\n"
        "print(delivery, app.config['INVITATION_EMAIL_PROVIDER'], "
        "repr(app.config['SMTP_PASSWORD']), repr(app.config['RESEND_API_KEY']))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["DevelopmentInvitationOutbox", "development", "''", "''"]


# ---------------------------------------------------------------- .env handling

COPIED_BACKEND_SCRIPT = (
    "from app import create_app\n"
    "app = create_app()\n"
    "print(type(app.extensions['invitation_delivery']).__name__, app.config['APP_CONFIG'], "
    "app.config['INVITATION_EMAIL_PROVIDER'], app.config['SMTP_HOST'], app.config['SMTP_PORT'], "
    "app.config['SMTP_SECURITY'], app.config['SMTP_USERNAME'] == 'fake.sender@example.test', "
    "app.config['SMTP_PASSWORD'] == 'fakeapppasswordvalue')\n"
)


def run_copied_backend(tmp_path, extra_env=None, env_file_encoding="utf-8"):
    """Run create_app() from a throwaway copy of the app package next to a fake .env.

    This exercises the real python-dotenv loading path (config.py loads BASE_DIR/.env)
    without touching the developer's backend/.env or any real credential.
    """
    shutil.copytree(
        BACKEND_DIR / "app", tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__")
    )
    (tmp_path / ".env").write_text(
        "APP_CONFIG=development\n"
        "INVITATION_EMAIL_PROVIDER=smtp\n"
        "INVITATION_EMAIL_FROM=TeamFlow <fake.sender@example.test>\n"
        "SMTP_USERNAME=fake.sender@example.test\n"
        "SMTP_PASSWORD=fake appp assw ordv alue\n",
        encoding=env_file_encoding,
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("SMTP_", "INVITATION_EMAIL", "RESEND_", "DATABASE_URL", "APP_CONFIG", "FLASK_")
        )
    }
    environment["DATABASE_URL"] = "sqlite:///:memory:"
    environment.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", COPIED_BACKEND_SCRIPT],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_backend_dotenv_is_picked_up_by_a_normal_development_start(tmp_path, encoding):
    result = run_copied_backend(tmp_path, env_file_encoding=encoding)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "SmtpDelivery",
        "development",
        "smtp",
        "smtp.gmail.com",
        "587",
        "starttls",
        "True",
        "True",
    ]
    assert "fakeapppasswordvalue" not in result.stderr


def test_shell_variables_override_backend_dotenv(tmp_path):
    result = run_copied_backend(tmp_path, {"INVITATION_EMAIL_PROVIDER": "development"})

    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[:3] == [
        "DevelopmentInvitationOutbox",
        "development",
        "development",
    ]


@pytest.mark.parametrize(
    "extra_env",
    [
        {"FLASK_SKIP_DOTENV": "1"},
        {"APP_CONFIG": "testing", "TEST_DATABASE_URL": "sqlite:///:memory:"},
    ],
    ids=["skip-dotenv", "testing-config"],
)
def test_backend_dotenv_is_ignored_for_tests_and_isolated_runs(tmp_path, extra_env):
    result = run_copied_backend(tmp_path, extra_env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[0] == "DevelopmentInvitationOutbox"
    assert result.stdout.split()[-2:] == ["False", "False"]


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, True),
        ({"APP_CONFIG": "development"}, True),
        ({"APP_CONFIG": "production"}, True),
        ({"APP_CONFIG": "testing"}, False),
        ({"APP_CONFIG": " Testing "}, False),
        ({"FLASK_SKIP_DOTENV": "1"}, False),
        ({"FLASK_SKIP_DOTENV": "true"}, False),
        ({"FLASK_SKIP_DOTENV": "0"}, True),
    ],
)
def test_dotenv_is_never_loaded_for_tests_or_when_explicitly_skipped(environ, expected):
    assert should_load_dotenv(environ) is expected


def test_dotenv_example_contains_only_rejected_smtp_placeholders():
    example = dotenv_values(BASE_DIR / ".env.example")

    assert example["INVITATION_EMAIL_PROVIDER"] == "development"
    assert example["SMTP_HOST"] == "smtp.gmail.com"
    assert example["SMTP_PORT"] == "587"
    assert example["SMTP_SECURITY"] == "starttls"
    # Selecting smtp without replacing the placeholders must fail at startup.
    with pytest.raises(RuntimeError):
        get_invitation_email_settings(
            "development", {**example, "INVITATION_EMAIL_PROVIDER": "smtp"}
        )
    # Even with a valid sender, the placeholder username/password are still rejected.
    with pytest.raises(RuntimeError, match="SMTP_USERNAME"):
        get_invitation_email_settings(
            "development",
            {
                **example,
                "INVITATION_EMAIL_PROVIDER": "smtp",
                "INVITATION_EMAIL_FROM": f"TeamFlow <{TEST_SENDER_ADDRESS}>",
            },
        )
    with pytest.raises(RuntimeError, match="SMTP_PASSWORD"):
        get_invitation_email_settings(
            "development",
            {
                **example,
                "INVITATION_EMAIL_PROVIDER": "smtp",
                "INVITATION_EMAIL_FROM": f"TeamFlow <{TEST_SENDER_ADDRESS}>",
                "SMTP_USERNAME": TEST_SENDER_ADDRESS,
            },
        )


def test_backend_dotenv_file_is_gitignored():
    patterns = (BACKEND_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in patterns
