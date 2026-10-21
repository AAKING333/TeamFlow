from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..config import InvitationEmailSettings
from .invitation_delivery import DeliveryRejected, DeliveryResult, DeliveryUnknown
from .invitation_email import InvitationEmailMessage

RESEND_ENDPOINT = "https://api.resend.com/emails"
MAX_RESPONSE_BYTES = 8192


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, new):
        del req, fp, code, msg, headers, new
        return None


class ResendDelivery:
    """Synchronous Resend adapter with bounded, redacted response handling."""

    def __init__(
        self,
        settings: InvitationEmailSettings,
        opener: Callable[..., object] | None = None,
    ) -> None:
        self._settings = settings
        self._opener = opener or build_opener(_NoRedirectHandler()).open

    def deliver(self, message: InvitationEmailMessage) -> DeliveryResult:
        payload = {
            "from": self._settings.sender,
            "to": [message.recipient_email],
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
        }
        request = Request(
            RESEND_ENDPOINT,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            response = self._opener(request, timeout=self._settings.timeout_seconds)
            try:
                status = response.status if hasattr(response, "status") else response.getcode()
                if not isinstance(status, int) or status < 200 or status >= 300:
                    raise DeliveryUnknown()
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise DeliveryUnknown()
                parsed = json.loads(body.decode("utf-8"))
            finally:
                response.close()
        except HTTPError as error:
            if 400 <= error.code < 500 and error.code not in {408, 425, 429}:
                raise DeliveryRejected() from None
            raise DeliveryUnknown() from None
        except DeliveryRejected:
            raise
        except DeliveryUnknown:
            raise
        except Exception as error:
            del error
            raise DeliveryUnknown() from None

        if not isinstance(parsed, dict) or not isinstance(parsed.get("id"), str):
            raise DeliveryUnknown()
        if not parsed["id"].strip():
            raise DeliveryUnknown()
        return DeliveryResult("accepted")
