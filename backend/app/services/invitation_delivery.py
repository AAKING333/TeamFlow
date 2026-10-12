from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class InvitationDelivery(Protocol):
    def deliver(
        self,
        invitation_id: int,
        recipient_email: str,
        invitation_url: str,
        expires_at: datetime,
    ) -> str: ...

    def take(self, invitation_id: int) -> str | None: ...


class DevelopmentInvitationOutbox:
    """Volatile local-only outbox; links expire and can be retrieved once."""

    def __init__(self) -> None:
        self._tokens: dict[int, tuple[str, datetime]] = {}

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def deliver(
        self,
        invitation_id: int,
        recipient_email: str,
        invitation_url: str,
        expires_at: datetime,
    ) -> str:
        del recipient_email
        now = datetime.now(UTC)
        self._tokens = {
            key: value for key, value in self._tokens.items() if self._as_utc(value[1]) > now
        }
        self._tokens[invitation_id] = (invitation_url, self._as_utc(expires_at))
        return "development_outbox"

    def take(self, invitation_id: int) -> str | None:
        value = self._tokens.pop(invitation_id, None)
        if value is None or self._as_utc(value[1]) <= datetime.now(UTC):
            return None
        return value[0]
