from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import User, Workspace, WorkspaceInvitation, WorkspaceMembership
from app.services.invitation_delivery import DeliveryRejected, DeliveryResult, DeliveryUnknown

BASE = "/api/v1"
WORKSPACES = f"{BASE}/workspaces"
TEST_PASSWORD = "workspace-password-8"


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


def make_workspace(owner: User, *, admin: User | None = None, member: User | None = None):
    workspace = Workspace(name="Members", owner=owner)
    workspace.memberships.append(WorkspaceMembership(user=owner, role="owner"))
    if admin:
        workspace.memberships.append(WorkspaceMembership(user=admin, role="admin"))
    if member:
        workspace.memberships.append(WorkspaceMembership(user=member, role="member"))
    db.session.add(workspace)
    db.session.commit()
    return workspace


def invite(client, workspace_id: int, email: str, role: str = "member"):
    return client.post(
        f"{WORKSPACES}/{workspace_id}/invitations",
        json={"email": email, "role": role},
        headers=csrf_headers(client),
    )


class FakeInvitationDelivery:
    def __init__(self, result: DeliveryResult | Exception, on_deliver=None):
        self.result = result
        self.on_deliver = on_deliver
        self.messages = []

    def deliver(self, message):
        self.messages.append(message)
        if self.on_deliver is not None:
            self.on_deliver(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_invitation_normalizes_email_stores_only_hash_and_uses_dev_outbox(client, app):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)

    response = invite(client, workspace.id, "  New.User@Example.Test  ")

    assert response.status_code == 201
    body = response.get_json()
    assert body["delivery_status"] == "development_outbox"
    assert "No email was sent" in body["message"]
    assert body["invitation"]["email"] == "new.user@example.test"
    assert body["invitation"]["role"] == "member"
    assert "token_hash" not in body["invitation"]
    assert "token" not in body["invitation"]

    invitation = db.session.get(WorkspaceInvitation, body["invitation"]["id"])
    assert invitation is not None
    assert len(invitation.token_hash) == 64
    assert invitation.token_hash != invitation.email
    assert invitation.expires_at.replace(tzinfo=UTC) > datetime.now(UTC)

    app.config["APP_CONFIG"] = "development"
    link_response = client.get(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation.id}/development-link"
    )
    assert link_response.status_code == 200
    assert link_response.headers["Cache-Control"] == "no-store"
    assert link_response.headers["Referrer-Policy"] == "no-referrer"
    token = parse_qs(urlparse(link_response.get_json()["invitation_url"]).query)["token"][0]
    assert hashlib.sha256(token.encode()).hexdigest() == invitation.token_hash
    assert (
        client.get(
            f"{WORKSPACES}/{workspace.id}/invitations/{invitation.id}/development-link"
        ).status_code
        == 404
    )


def test_invitation_role_permissions_validation_duplicates_and_csrf(client, app):
    owner = create_user("owner@example.test")
    admin = create_user("admin@example.test")
    workspace = make_workspace(owner, admin=admin)
    login(client, admin.email)

    forbidden_admin_invite = invite(client, workspace.id, "new@example.test", "admin")
    assert forbidden_admin_invite.status_code == 403
    assert forbidden_admin_invite.get_json()["error"] == "permission_denied"
    no_csrf = client.post(
        f"{WORKSPACES}/{workspace.id}/invitations",
        json={"email": "new@example.test"},
    )
    assert no_csrf.status_code == 403
    for payload in (
        {},
        {"email": "bad-email"},
        {"email": "another@example.test", "role": "owner"},
        {"email": "new@example.test", "extra": True},
    ):
        response = client.post(
            f"{WORKSPACES}/{workspace.id}/invitations",
            json=payload,
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "validation_error"

    first = invite(client, workspace.id, " New@Example.Test ")
    duplicate = invite(client, workspace.id, "new@example.test")
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.get_json()["error"] == "invitation_already_pending"
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(WorkspaceInvitation)
            .where(WorkspaceInvitation.workspace_id == workspace.id)
        )
        == 1
    )

    other = app.test_client()
    visitor = create_user("visitor@example.test")
    db.session.commit()
    login(other, visitor.email)
    inaccessible = other.post(
        f"{WORKSPACES}/{workspace.id}/invitations",
        json={"email": "hidden@example.test"},
        headers=csrf_headers(other),
    )
    assert inaccessible.status_code == 404
    assert inaccessible.get_json()["error"] == "workspace_not_found"


def test_invitation_is_committed_before_provider_delivery(client, app):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    observed = {}

    def observe(message):
        invitation = db.session.get(WorkspaceInvitation, message.invitation_id)
        token = parse_qs(urlparse(message.invitation_url).query)["token"][0]
        observed["exists"] = invitation is not None
        observed["delivery_status"] = invitation.delivery_status
        observed["token_matches"] = (
            invitation.token_hash == hashlib.sha256(token.encode()).hexdigest()
        )

    app.extensions["invitation_delivery"] = FakeInvitationDelivery(
        DeliveryResult("accepted"), on_deliver=observe
    )

    response = invite(client, workspace.id, "committed@example.test")

    assert response.status_code == 201
    assert observed == {
        "exists": True,
        "delivery_status": "pending",
        "token_matches": True,
    }


def test_provider_outcomes_are_persisted_without_false_success(client, app):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    fake = FakeInvitationDelivery(DeliveryResult("accepted"))
    app.extensions["invitation_delivery"] = fake

    accepted = invite(client, workspace.id, "accepted@example.test")
    assert accepted.status_code == 201
    accepted_body = accepted.get_json()
    accepted_invitation = db.session.get(WorkspaceInvitation, accepted_body["invitation"]["id"])
    assert accepted_body["delivery_status"] == "accepted"
    assert accepted_invitation.delivery_status == "accepted"
    assert "token" not in accepted_body["invitation"]
    assert fake.messages[0].invitation_url.startswith(
        "http://localhost:5173/accept-invitation?token="
    )
    assert db.session.get(WorkspaceInvitation, accepted_invitation.id) is not None

    fake.result = DeliveryRejected()
    rejected = invite(client, workspace.id, "rejected@example.test")
    assert rejected.status_code == 502
    assert rejected.get_json()["error"] == "invitation_delivery_rejected"
    rejected_invitation = db.session.scalar(
        select(WorkspaceInvitation).where(WorkspaceInvitation.email == "rejected@example.test")
    )
    assert rejected_invitation.delivery_status == "rejected"

    fake.result = DeliveryUnknown()
    unavailable = invite(client, workspace.id, "unknown@example.test")
    assert unavailable.status_code == 503
    assert unavailable.get_json()["error"] == "invitation_delivery_unavailable"
    unknown_invitation = db.session.scalar(
        select(WorkspaceInvitation).where(WorkspaceInvitation.email == "unknown@example.test")
    )
    assert unknown_invitation.delivery_status == "unknown"
    assert "token_hash" not in rejected.get_json()["invitation"]
    assert "token=" not in rejected.get_data(as_text=True)


def test_failed_delivery_can_be_retried_without_creating_duplicate_rows(client, app):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    fake = FakeInvitationDelivery(DeliveryRejected())
    app.extensions["invitation_delivery"] = fake

    rejected = invite(client, workspace.id, "retry-rejected@example.test")
    rejected_id = rejected.get_json()["invitation"]["id"]
    fake.result = DeliveryUnknown()
    unknown = invite(client, workspace.id, "retry-unknown@example.test")
    unknown_id = unknown.get_json()["invitation"]["id"]

    fake.result = DeliveryResult("accepted")
    retried_rejected = client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{rejected_id}/resend",
        headers=csrf_headers(client),
    )
    retried_unknown = client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{unknown_id}/resend",
        headers=csrf_headers(client),
    )

    assert retried_rejected.status_code == 200
    assert retried_unknown.status_code == 200
    assert db.session.get(WorkspaceInvitation, rejected_id).delivery_status == "accepted"
    assert db.session.get(WorkspaceInvitation, unknown_id).delivery_status == "accepted"
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(WorkspaceInvitation)
            .where(WorkspaceInvitation.workspace_id == workspace.id)
        )
        == 2
    )


def test_resend_rotates_token_and_preserves_authorization_and_lifecycle(client, app):
    owner = create_user("owner@example.test")
    invitee = create_user("invitee@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    fake = FakeInvitationDelivery(DeliveryResult("accepted"))
    app.extensions["invitation_delivery"] = fake

    created = invite(client, workspace.id, invitee.email)
    invitation_id = created.get_json()["invitation"]["id"]
    first_token = parse_qs(urlparse(fake.messages[-1].invitation_url).query)["token"][0]
    first_hash = db.session.get(WorkspaceInvitation, invitation_id).token_hash

    resent = client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/resend",
        headers=csrf_headers(client),
    )
    assert resent.status_code == 200
    second_token = parse_qs(urlparse(fake.messages[-1].invitation_url).query)["token"][0]
    invitation = db.session.get(WorkspaceInvitation, invitation_id)
    assert invitation.token_hash != first_hash
    assert second_token != first_token
    assert invitation.delivery_status == "accepted"

    invitee_client = app.test_client()
    login(invitee_client, invitee.email)
    old_token = invitee_client.post(
        f"{BASE}/invitations/accept",
        json={"token": first_token},
        headers=csrf_headers(invitee_client),
    )
    assert old_token.status_code == 404
    current_token = invitee_client.post(
        f"{BASE}/invitations/accept",
        json={"token": second_token},
        headers=csrf_headers(invitee_client),
    )
    assert current_token.status_code == 200


def test_resend_requires_empty_body_and_rejects_unavailable_lifecycle(client, app):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    fake = FakeInvitationDelivery(DeliveryResult("accepted"))
    app.extensions["invitation_delivery"] = fake
    created = invite(client, workspace.id, "invitee@example.test")
    invitation_id = created.get_json()["invitation"]["id"]

    body = client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/resend",
        data="{}",
        content_type="application/json",
        headers=csrf_headers(client),
    )
    assert body.status_code == 400
    assert body.get_json()["error"] == "validation_error"

    invitation = db.session.get(WorkspaceInvitation, invitation_id)
    invitation.status = "revoked"
    db.session.commit()
    unavailable = client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/resend",
        headers=csrf_headers(client),
    )
    assert unavailable.status_code == 410
    assert len(fake.messages) == 1


def test_resend_authorization_csrf_workspace_and_expiry_guards(client, app):
    owner = create_user("owner@example.test")
    admin = create_user("admin@example.test")
    other_owner = create_user("other-owner@example.test")
    workspace = make_workspace(owner, admin=admin)
    make_workspace(other_owner)
    login(client, owner.email)
    fake = FakeInvitationDelivery(DeliveryResult("accepted"))
    app.extensions["invitation_delivery"] = fake

    admin_invitation = invite(client, workspace.id, "admin-target@example.test", "admin")
    admin_invitation_id = admin_invitation.get_json()["invitation"]["id"]
    missing_csrf = client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{admin_invitation_id}/resend"
    )
    assert missing_csrf.status_code == 403

    admin_client = app.test_client()
    login(admin_client, admin.email)
    forbidden_role = admin_client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{admin_invitation_id}/resend",
        headers=csrf_headers(admin_client),
    )
    assert forbidden_role.status_code == 403
    assert forbidden_role.get_json()["error"] == "permission_denied"

    other_client = app.test_client()
    login(other_client, other_owner.email)
    cross_workspace = other_client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{admin_invitation_id}/resend",
        headers=csrf_headers(other_client),
    )
    assert cross_workspace.status_code == 404
    assert cross_workspace.get_json()["error"] == "workspace_not_found"

    expired = invite(client, workspace.id, "expired-resend@example.test")
    expired_id = expired.get_json()["invitation"]["id"]
    invitation = db.session.get(WorkspaceInvitation, expired_id)
    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.session.commit()
    delivery_calls_before = len(fake.messages)
    expired_response = client.post(
        f"{WORKSPACES}/{workspace.id}/invitations/{expired_id}/resend",
        headers=csrf_headers(client),
    )

    assert expired_response.status_code == 410
    assert expired_response.get_json()["error"] == "invitation_unavailable"
    assert db.session.get(WorkspaceInvitation, expired_id).status == "expired"
    assert len(fake.messages) == delivery_calls_before


def test_delivery_outcome_commit_failure_is_unknown_without_false_success(client, app, monkeypatch):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    app.extensions["invitation_delivery"] = FakeInvitationDelivery(DeliveryResult("accepted"))
    commit_calls = 0
    original_commit = db.session.commit

    def fail_outcome_commit():
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 2:
            raise SQLAlchemyError("injected delivery outcome commit failure")
        original_commit()

    monkeypatch.setattr(db.session, "commit", fail_outcome_commit)
    response = invite(client, workspace.id, "outcome-failure@example.test")

    assert response.status_code == 503
    body = response.get_json()
    assert body["error"] == "invitation_delivery_unavailable"
    assert body["delivery_status"] == "unknown"
    assert "invitation" not in body
    invitation = db.session.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.email == "outcome-failure@example.test"
        )
    )
    assert invitation.status == "pending"
    assert invitation.delivery_status == "pending"


def test_invitation_creation_is_disabled_without_a_delivery_adapter(client, app):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    app.extensions.pop("invitation_delivery")

    response = invite(client, workspace.id, "undeliverable@example.test")

    assert response.status_code == 503
    assert response.get_json()["error"] == "invitation_delivery_unconfigured"
    assert db.session.scalar(select(func.count()).select_from(WorkspaceInvitation)) == 0


def test_invitation_model_server_default_is_conservative(client, app):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email="direct@example.test",
        role="member",
        token_hash="d" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=7),
        inviter_id=owner.id,
        status="pending",
    )
    db.session.add(invitation)
    db.session.commit()
    assert invitation.delivery_status == "unknown"


def test_development_invitation_link_route_is_hidden_outside_development(client, app):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    created = invite(client, workspace.id, "invitee@example.test")
    invitation_id = created.get_json()["invitation"]["id"]

    app.config["APP_CONFIG"] = "production"
    unavailable = client.get(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/development-link"
    )
    assert unavailable.status_code == 404
    assert unavailable.get_json()["error"] == "not_found"

    app.config["APP_CONFIG"] = "development"
    available = client.get(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/development-link"
    )
    assert available.status_code == 200


def test_invitation_acceptance_requires_matching_email_and_can_only_succeed_once(client, app):
    owner = create_user("owner@example.test")
    invitee = create_user("invitee@example.test")
    wrong_user = create_user("wrong@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    response = invite(client, workspace.id, "Invitee@Example.Test", "admin")
    invitation_id = response.get_json()["invitation"]["id"]
    app.config["APP_CONFIG"] = "development"
    link = client.get(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/development-link"
    ).get_json()["invitation_url"]
    token = parse_qs(urlparse(link).query)["token"][0]

    wrong_client = app.test_client()
    login(wrong_client, wrong_user.email)
    mismatch = wrong_client.post(
        f"{BASE}/invitations/accept",
        json={"token": token},
        headers=csrf_headers(wrong_client),
    )
    assert mismatch.status_code == 403
    assert mismatch.get_json()["error"] == "invitation_email_mismatch"
    assert (
        db.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == wrong_user.id,
            )
        )
        is None
    )

    invitee_client = app.test_client()
    login(invitee_client, invitee.email)
    missing_csrf = invitee_client.post(
        f"{BASE}/invitations/accept",
        json={"token": token},
    )
    assert missing_csrf.status_code == 403
    invalid_token = invitee_client.post(
        f"{BASE}/invitations/accept",
        json={"token": "x" * 43},
        headers=csrf_headers(invitee_client),
    )
    assert invalid_token.status_code == 404
    accepted = invitee_client.post(
        f"{BASE}/invitations/accept",
        json={"token": token},
        headers=csrf_headers(invitee_client),
    )
    assert accepted.status_code == 200
    membership = db.session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == invitee.id,
        )
    )
    assert membership is not None
    assert membership.role == "admin"
    assert db.session.get(WorkspaceInvitation, invitation_id).status == "accepted"

    reused = invitee_client.post(
        f"{BASE}/invitations/accept",
        json={"token": token},
        headers=csrf_headers(invitee_client),
    )
    assert reused.status_code == 410
    assert reused.get_json()["error"] == "invitation_unavailable"
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == invitee.id,
            )
        )
        == 1
    )


def test_acceptance_database_failure_rolls_back_membership_and_invitation(client, app, monkeypatch):
    owner = create_user("owner@example.test")
    invitee = create_user("invitee@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    result = invite(client, workspace.id, invitee.email)
    invitation_id = result.get_json()["invitation"]["id"]
    app.config["APP_CONFIG"] = "development"
    link = client.get(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/development-link"
    ).get_json()["invitation_url"]
    token = parse_qs(urlparse(link).query)["token"][0]

    invitee_client = app.test_client()
    login(invitee_client, invitee.email)

    def fail_commit():
        raise SQLAlchemyError("injected acceptance commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = invitee_client.post(
        f"{BASE}/invitations/accept",
        json={"token": token},
        headers=csrf_headers(invitee_client),
    )
    assert response.status_code == 500
    assert db.session.get(WorkspaceInvitation, invitation_id).status == "pending"
    assert (
        db.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == invitee.id,
            )
        )
        is None
    )


def test_revoked_expired_invalid_and_existing_member_invites_are_rejected(client, app):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    expired_user = create_user("expired@example.test")
    revoked_user = create_user("revoked@example.test")
    workspace = make_workspace(owner, member=member)
    login(client, owner.email)
    existing_member = invite(client, workspace.id, member.email)
    assert existing_member.status_code == 409

    revoked = invite(client, workspace.id, revoked_user.email)
    revoked_id = revoked.get_json()["invitation"]["id"]
    expired = invite(client, workspace.id, expired_user.email)
    expired_id = expired.get_json()["invitation"]["id"]
    app.config["APP_CONFIG"] = "development"
    revoked_link = client.get(
        f"{WORKSPACES}/{workspace.id}/invitations/{revoked_id}/development-link"
    ).get_json()["invitation_url"]
    expired_link = client.get(
        f"{WORKSPACES}/{workspace.id}/invitations/{expired_id}/development-link"
    ).get_json()["invitation_url"]
    revoked_token = parse_qs(urlparse(revoked_link).query)["token"][0]
    expired_token = parse_qs(urlparse(expired_link).query)["token"][0]

    assert (
        client.delete(
            f"{WORKSPACES}/{workspace.id}/invitations/{revoked_id}",
            headers=csrf_headers(client),
        ).status_code
        == 200
    )
    invitation = db.session.get(WorkspaceInvitation, expired_id)
    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.session.commit()

    for user, token in ((revoked_user, revoked_token), (expired_user, expired_token)):
        invitee = app.test_client()
        login(invitee, user.email)
        result = invitee.post(
            f"{BASE}/invitations/accept",
            json={"token": token},
            headers=csrf_headers(invitee),
        )
        assert result.status_code == 410
        assert result.get_json()["error"] == "invitation_unavailable"
        assert (
            db.session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace.id,
                    WorkspaceMembership.user_id == user.id,
                )
            )
            is None
        )

    listed = client.get(f"{WORKSPACES}/{workspace.id}/invitations")
    assert listed.status_code == 200
    assert {item["email"] for item in listed.get_json()["invitations"]} == set()


def test_owner_only_role_changes_and_member_removal_safeguards(client, app):
    owner = create_user("owner@example.test")
    admin = create_user("admin@example.test")
    member = create_user("member@example.test")
    workspace = make_workspace(owner, admin=admin, member=member)
    login(client, owner.email)

    self_change = client.patch(
        f"{WORKSPACES}/{workspace.id}/members/{owner.id}",
        json={"role": "member"},
        headers=csrf_headers(client),
    )
    owner_change = client.patch(
        f"{WORKSPACES}/{workspace.id}/members/{owner.id}",
        json={"role": "admin"},
        headers=csrf_headers(client),
    )
    assert self_change.status_code == owner_change.status_code == 403
    assert (
        db.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == owner.id,
            )
        ).role
        == "owner"
    )

    promotion = client.patch(
        f"{WORKSPACES}/{workspace.id}/members/{member.id}",
        json={"role": "admin"},
        headers=csrf_headers(client),
    )
    assert promotion.status_code == 200
    assert promotion.get_json()["member"]["role"] == "admin"

    admin_client = app.test_client()
    login(admin_client, admin.email)
    demotion = admin_client.patch(
        f"{WORKSPACES}/{workspace.id}/members/{member.id}",
        json={"role": "member"},
        headers=csrf_headers(admin_client),
    )
    assert demotion.status_code == 403
    assert (
        db.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == member.id,
            )
        ).role
        == "admin"
    )

    admin_remove_admin = admin_client.delete(
        f"{WORKSPACES}/{workspace.id}/members/{member.id}",
        headers=csrf_headers(admin_client),
    )
    assert admin_remove_admin.status_code == 403
    owner_remove_admin = client.delete(
        f"{WORKSPACES}/{workspace.id}/members/{admin.id}",
        headers=csrf_headers(client),
    )
    assert owner_remove_admin.status_code == 200
    assert (
        db.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == admin.id,
            )
        )
        is None
    )
    assert (
        client.delete(
            f"{WORKSPACES}/{workspace.id}/members/{owner.id}",
            headers=csrf_headers(client),
        ).status_code
        == 404
    )


def test_member_leave_owner_transfer_safeguard_and_nonmember_privacy(client, app):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    outsider = create_user("outsider@example.test")
    workspace = make_workspace(owner, member=member)
    login(client, owner.email)
    assert (
        client.post(
            f"{WORKSPACES}/{workspace.id}/leave",
            headers=csrf_headers(client),
        ).status_code
        == 409
    )
    assert (
        db.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == owner.id,
            )
        )
        is not None
    )

    member_client = app.test_client()
    login(member_client, member.email)
    members = member_client.get(f"{WORKSPACES}/{workspace.id}/members")
    assert members.status_code == 200
    assert all("email" not in item for item in members.get_json()["members"])
    left = member_client.post(
        f"{WORKSPACES}/{workspace.id}/leave",
        headers=csrf_headers(member_client),
    )
    assert left.status_code == 200
    assert (
        db.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == member.id,
            )
        )
        is None
    )

    outsider_client = app.test_client()
    login(outsider_client, outsider.email)
    inaccessible = outsider_client.get(f"{WORKSPACES}/{workspace.id}/invitations")
    assert inaccessible.status_code == 404
    assert inaccessible.get_json()["error"] == "workspace_not_found"


def test_invitation_creation_rolls_back_on_database_failure(client, monkeypatch):
    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)

    def fail_commit():
        raise SQLAlchemyError("injected invitation commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = invite(client, workspace.id, "rollback@example.test")
    assert response.status_code == 500
    assert "injected invitation commit failure" not in response.get_data(as_text=True)
    assert db.session.scalar(select(func.count()).select_from(WorkspaceInvitation)) == 0


def test_concurrent_resend_cannot_overwrite_a_newer_attempt_on_postgresql(client, app):
    if db.engine.dialect.name != "postgresql":
        pytest.skip("Resend row-lock concurrency is verified by the PostgreSQL integration job.")

    owner = create_user("owner@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    delivery = FakeInvitationDelivery(DeliveryResult("accepted"))
    app.extensions["invitation_delivery"] = delivery
    created = invite(client, workspace.id, "resend@example.test")
    invitation_id = created.get_json()["invitation"]["id"]

    first_started = Event()
    release_first = Event()
    original_deliver = delivery.deliver
    resend_calls = 0

    def block_first_resend(message):
        nonlocal resend_calls
        resend_calls += 1
        if resend_calls == 1:
            first_started.set()
            assert release_first.wait(timeout=10)
        return original_deliver(message)

    delivery.deliver = block_first_resend
    first_client = app.test_client()
    second_client = app.test_client()
    login(first_client, owner.email)
    login(second_client, owner.email)
    first_headers = csrf_headers(first_client)
    second_headers = csrf_headers(second_client)

    def resend_with(client_instance, headers):
        return client_instance.post(
            f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/resend",
            headers=headers,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(resend_with, first_client, first_headers)
        assert first_started.wait(timeout=10)
        second_future = executor.submit(resend_with, second_client, second_headers)
        second_response = second_future.result(timeout=10)
        release_first.set()
        first_response = first_future.result(timeout=10)

    assert second_response.status_code == 200
    assert first_response.status_code == 409
    assert first_response.get_json()["error"] == "invitation_delivery_superseded"
    assert db.session.get(WorkspaceInvitation, invitation_id).delivery_status == "accepted"


def test_concurrent_invitation_acceptance_is_single_use_on_postgresql(client, app):
    if db.engine.dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency is verified by the PostgreSQL integration job.")

    owner = create_user("owner@example.test")
    invitee = create_user("invitee@example.test")
    workspace = make_workspace(owner)
    login(client, owner.email)
    invitation = invite(client, workspace.id, invitee.email)
    invitation_id = invitation.get_json()["invitation"]["id"]
    app.config["APP_CONFIG"] = "development"
    invitation_url = client.get(
        f"{WORKSPACES}/{workspace.id}/invitations/{invitation_id}/development-link"
    ).get_json()["invitation_url"]
    token = parse_qs(urlparse(invitation_url).query)["token"][0]

    clients = [app.test_client(), app.test_client()]
    csrf_tokens = []
    for invitee_client in clients:
        login(invitee_client, invitee.email)
        csrf_tokens.append(csrf_headers(invitee_client))

    barrier = Barrier(2)

    def accept(index: int) -> int:
        barrier.wait(timeout=10)
        response = clients[index].post(
            f"{BASE}/invitations/accept",
            json={"token": token},
            headers=csrf_tokens[index],
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(accept, range(2)))

    assert sorted(results) == [200, 410]
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == invitee.id,
            )
        )
        == 1
    )
