from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .invitation_email import InvitationEmailMessage


@dataclass(frozen=True)
class DeliveryResult:
    status: str


class DeliveryRejected(Exception):
    """The provider definitively rejected the invitation email."""


class DeliveryMisconfigured(DeliveryRejected):
    """The provider refused the server's own credentials or settings (nothing was sent)."""


class DeliveryUnknown(Exception):
    """The provider result could not be confirmed safely."""


class InvitationDelivery(Protocol):
    def deliver(self, message: InvitationEmailMessage) -> DeliveryResult: ...


class DevelopmentInvitationOutbox:
    """Volatile local-only outbox; links expire and can be retrieved once."""

    def __init__(self) -> None:
        self._tokens: dict[int, tuple[str, datetime]] = {}

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def deliver(self, message: InvitationEmailMessage) -> DeliveryResult:
        now = datetime.now(UTC)
        self._tokens = {
            key: value for key, value in self._tokens.items() if self._as_utc(value[1]) > now
        }
        self._tokens[message.invitation_id] = (
            message.invitation_url,
            self._as_utc(message.expires_at),
        )
        return DeliveryResult("development_outbox")

    def take(self, invitation_id: int) -> str | None:
        value = self._tokens.pop(invitation_id, None)
        if value is None or self._as_utc(value[1]) <= datetime.now(UTC):
            return None
        return value[0]
