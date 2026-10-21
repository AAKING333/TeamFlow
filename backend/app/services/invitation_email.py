from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape


@dataclass(frozen=True)
class InvitationEmailMessage:
    invitation_id: int
    recipient_email: str
    subject: str
    html: str
    text: str
    invitation_url: str
    expires_at: datetime


def _safe_display(value: str | None, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    return cleaned[:120] or fallback


def _expiry_text(expires_at: datetime) -> str:
    normalized = (
        expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at.astimezone(UTC)
    )
    month_day = f"{normalized.strftime('%B')} {normalized.day}"
    return f"{month_day}, {normalized.year} at {normalized:%H:%M} UTC"


def build_invitation_email(
    *,
    invitation_id: int,
    recipient_email: str,
    workspace_name: str,
    inviter_name: str | None,
    role: str,
    expires_at: datetime,
    invitation_url: str,
) -> InvitationEmailMessage:
    if role not in {"admin", "member"}:
        raise ValueError("Unsupported invitation role.")
    safe_workspace = _safe_display(workspace_name, "a TeamFlow workspace")
    safe_inviter = _safe_display(inviter_name, "A TeamFlow workspace administrator")
    purpose = "workspace administrator" if role == "admin" else "workspace member"
    expiry = _expiry_text(expires_at)
    subject = "You're invited to join a TeamFlow workspace"

    html_workspace = escape(safe_workspace, quote=True)
    html_inviter = escape(safe_inviter, quote=True)
    html_purpose = escape(purpose, quote=True)
    html_expiry = escape(expiry, quote=True)
    html_url = escape(invitation_url, quote=True)
    html = f"""<!doctype html>
<html lang="en">
  <body style="margin:0;background:#f5f7fb;color:#172033;">
    <div style="max-width:600px;margin:0 auto;padding:32px 20px;">
      <div style="background:#14213d;color:#fff;padding:18px 24px;">
        <strong style="font-size:22px;letter-spacing:.02em;">TeamFlow</strong>
      </div>
      <div style="background:#fff;padding:30px 24px;border:1px solid #dfe5ef;">
        <h1 style="margin:0 0 18px;font-size:26px;">
          You're invited to join TeamFlow
        </h1>
        <p>
          {html_inviter} invited you to join <strong>{html_workspace}</strong>
          as a {html_purpose}.
        </p>
        <p style="margin:26px 0;">
          <a
            href="{html_url}"
            style="display:inline-block;background:#315efb;color:#fff;padding:12px 20px;"
          >Accept invitation</a>
        </p>
        <p>This invitation expires on <strong>{html_expiry}</strong>.</p>
        <p style="font-size:14px;color:#536174;">
          If you were not expecting this invitation, do not use the link.
          Contact the inviter or workspace owner.
        </p>
        <p style="font-size:14px;color:#536174;word-break:break-word;">
          If the button does not work, copy this URL into your browser:<br>{html_url}
        </p>
      </div>
    </div>
  </body>
</html>"""
    text = (
        "TeamFlow\n\n"
        f"{safe_inviter} invited you to join {safe_workspace} as a {purpose}.\n\n"
        f"Accept the invitation: {invitation_url}\n\n"
        f"This invitation expires on {expiry}.\n\n"
        "If you were not expecting this invitation, do not use the link. "
        "Contact the inviter or your workspace owner.\n"
    )
    return InvitationEmailMessage(
        invitation_id=invitation_id,
        recipient_email=recipient_email,
        subject=subject,
        html=html,
        text=text,
        invitation_url=invitation_url,
        expires_at=expires_at,
    )
