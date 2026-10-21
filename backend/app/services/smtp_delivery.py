from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid, parseaddr
from typing import Any

from ..config import InvitationEmailSettings, _has_ascii_control
from .invitation_delivery import (
    DeliveryMisconfigured,
    DeliveryRejected,
    DeliveryResult,
    DeliveryUnknown,
)
from .invitation_email import InvitationEmailMessage

logger = logging.getLogger(__name__)


def _is_transient(code: object) -> bool:
    return isinstance(code, int) and 400 <= code < 500


def _is_permanent(code: object) -> bool:
    return isinstance(code, int) and 500 <= code < 600


def _refused_codes(error: smtplib.SMTPRecipientsRefused) -> list[object]:
    codes: list[object] = []
    for value in getattr(error, "recipients", {}).values():
        codes.append(value[0] if isinstance(value, (tuple, list)) and value else None)
    return codes


def classify_smtp_failure(
    error: BaseException, stage: str
) -> tuple[DeliveryRejected | DeliveryUnknown, str]:
    """Map an smtplib/socket failure to a delivery outcome and a log-safe category.

    Only the category (never the exception text, which can contain addresses or
    server banners) is ever logged.
    """
    if isinstance(error, smtplib.SMTPAuthenticationError):
        if _is_transient(error.smtp_code):
            return DeliveryUnknown(), "authentication_deferred"
        return DeliveryMisconfigured(), "authentication"
    if isinstance(error, smtplib.SMTPNotSupportedError):
        if stage in {"starttls", "login"}:
            return DeliveryMisconfigured(), "capability"
        return DeliveryRejected(), "unsupported_message"
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        if any(_is_transient(code) for code in _refused_codes(error)):
            return DeliveryUnknown(), "recipient_deferred"
        return DeliveryRejected(), "recipient_refused"
    if isinstance(error, smtplib.SMTPSenderRefused):
        if _is_transient(error.smtp_code):
            return DeliveryUnknown(), "sender_deferred"
        return DeliveryRejected(), "sender_refused"
    if isinstance(error, smtplib.SMTPConnectError):
        return DeliveryUnknown(), "connect"
    if isinstance(error, smtplib.SMTPServerDisconnected):
        return DeliveryUnknown(), "disconnected"
    if isinstance(error, smtplib.SMTPResponseException):
        if _is_permanent(error.smtp_code):
            if isinstance(error, smtplib.SMTPDataError):
                return DeliveryRejected(), "data_rejected"
            return DeliveryRejected(), "permanent_response"
        return DeliveryUnknown(), "transient_response"
    if isinstance(error, smtplib.SMTPException):
        return DeliveryUnknown(), "smtp_error"
    if isinstance(error, TimeoutError):
        return DeliveryUnknown(), "timeout"
    if isinstance(error, ssl.SSLError):
        return DeliveryUnknown(), "tls"
    if isinstance(error, socket.gaierror):
        return DeliveryUnknown(), "dns"
    if isinstance(error, OSError):
        return DeliveryUnknown(), "connection"
    return DeliveryUnknown(), "unexpected"


def _close_quietly(server: Any) -> None:
    if server is None:
        return
    # Closing must never change the delivery outcome that was already decided.
    try:
        server.quit()
    except Exception:
        pass
    try:
        server.close()
    except Exception:
        pass


class SmtpDelivery:
    """Synchronous SMTP adapter (Gmail or any SMTP server) using only the standard library.

    "accepted" means the SMTP server accepted the message for delivery. It does not
    mean the message reached an inbox. TLS is mandatory and certificates are always
    verified; credentials are never sent over a plaintext connection.
    """

    def __init__(
        self,
        settings: InvitationEmailSettings,
        smtp_factory: Callable[..., Any] | None = None,
        smtp_ssl_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings
        self._smtp_factory = smtp_factory
        self._smtp_ssl_factory = smtp_ssl_factory

    def _build_message(self, message: InvitationEmailMessage) -> tuple[EmailMessage, str]:
        sender = self._settings.sender
        recipient = message.recipient_email
        for value in (sender, recipient, message.subject):
            if not isinstance(value, str) or not value or _has_ascii_control(value):
                raise DeliveryRejected()
        # Exactly one bare ASCII mailbox: no lists, display names, or angle brackets.
        if getaddresses([recipient]) != [("", recipient)] or not recipient.isascii():
            raise DeliveryRejected()
        envelope_sender = parseaddr(sender)[1]
        if not envelope_sender:
            raise DeliveryRejected()

        mime = EmailMessage()
        mime["From"] = sender
        mime["To"] = recipient
        mime["Subject"] = message.subject
        mime["Date"] = formatdate(usegmt=True)
        mime["Message-ID"] = make_msgid(domain=envelope_sender.rpartition("@")[2])
        mime.set_content(message.text, subtype="plain", charset="utf-8", cte="quoted-printable")
        mime.add_alternative(message.html, subtype="html", charset="utf-8", cte="quoted-printable")
        return mime, envelope_sender

    def deliver(self, message: InvitationEmailMessage) -> DeliveryResult:
        try:
            mime, envelope_sender = self._build_message(message)
        except DeliveryRejected:
            logger.warning("SMTP invitation delivery rejected: category=invalid_message")
            raise DeliveryRejected() from None
        except Exception:
            logger.warning("SMTP invitation delivery unconfirmed: category=message_build")
            raise DeliveryUnknown() from None

        settings = self._settings
        server: Any = None
        stage = "connect"
        refused: object = None
        try:
            context = ssl.create_default_context()
            if settings.smtp_security == "ssl":
                factory = self._smtp_ssl_factory or smtplib.SMTP_SSL
                server = factory(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.timeout_seconds,
                    context=context,
                )
            else:
                factory = self._smtp_factory or smtplib.SMTP
                server = factory(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.timeout_seconds,
                )
                stage = "starttls"
                server.starttls(context=context)
            stage = "login"
            server.login(settings.smtp_username, settings.smtp_password)
            stage = "send"
            refused = server.send_message(
                mime, from_addr=envelope_sender, to_addrs=[message.recipient_email]
            )
        except Exception as error:
            outcome, category = classify_smtp_failure(error, stage)
            logger.warning(
                "SMTP invitation delivery %s: category=%s",
                "rejected" if isinstance(outcome, DeliveryRejected) else "unconfirmed",
                category,
            )
            raise outcome from None
        finally:
            _close_quietly(server)

        if refused:
            logger.warning("SMTP invitation delivery rejected: category=recipient_refused")
            raise DeliveryRejected()
        logger.info("SMTP server accepted an invitation message for delivery.")
        return DeliveryResult("accepted")
