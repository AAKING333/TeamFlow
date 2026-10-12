from __future__ import annotations

from datetime import UTC

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models import User, Workspace, WorkspaceMembership

WORKSPACES_URL = "/api/v1/workspaces"
TEST_PASSWORD = "workspace-password-8"


def csrf_headers(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.get_json()["csrf_token"]}


def create_user(email: str, name: str | None = None) -> User:
    user = User(name=name or email.split("@")[0], email=email)
    user.set_password(TEST_PASSWORD)
    db.session.add(user)
    db.session.flush()
    return user


def login(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200


def create_workspace(client, name: str = "Research"):
    return client.post(
        WORKSPACES_URL,
        json={"name": name},
        headers=csrf_headers(client),
    )


def add_member(workspace: Workspace, user: User, role: str) -> WorkspaceMembership:
    membership = WorkspaceMembership(workspace=workspace, user=user, role=role)
    db.session.add(membership)
    db.session.flush()
    return membership


def test_workspace_creation_trims_name_and_establishes_owner(client):
    owner = create_user("owner@example.test", "Workspace Owner")
    db.session.commit()
    login(client, owner.email)

    response = create_workspace(client, "  Design Team  ")

    assert response.status_code == 201
    workspace_payload = response.get_json()["workspace"]
    assert workspace_payload["name"] == "Design Team"
    assert workspace_payload["role"] == "owner"
    assert workspace_payload["owner_id"] == owner.id
    assert workspace_payload["created_at"].endswith("+00:00")
    assert workspace_payload["updated_at"].endswith("+00:00")

    workspace = db.session.get(Workspace, workspace_payload["id"])
    assert workspace is not None
    assert workspace.owner_id == owner.id
    if db.engine.dialect.name == "postgresql":
        assert workspace.created_at.tzinfo is not None
        assert workspace.updated_at.tzinfo is not None
        assert workspace.created_at.utcoffset() == UTC.utcoffset(workspace.created_at)
        assert workspace.updated_at.utcoffset() == UTC.utcoffset(workspace.updated_at)
    assert [(member.user_id, member.role) for member in workspace.memberships] == [
        (owner.id, "owner")
    ]


def test_workspace_creation_rejects_invalid_names_without_persisting(client):
    owner = create_user("owner@example.test")
    db.session.commit()
    login(client, owner.email)

    for payload in ({}, {"name": "   "}, {"name": "x" * 121}, {"name": 42}):
        response = client.post(WORKSPACES_URL, json=payload, headers=csrf_headers(client))
        assert response.status_code == 400
        assert response.get_json()["error"] == "validation_error"

    assert db.session.scalar(select(func.count()).select_from(Workspace)) == 0


def test_workspace_mutations_require_csrf(client):
    owner = create_user("owner@example.test")
    db.session.commit()
    login(client, owner.email)

    response = client.post(WORKSPACES_URL, json={"name": "No CSRF"})

    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_token_invalid"


def test_workspace_routes_require_authentication(client):
    response = client.get(WORKSPACES_URL)
    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_failed"

    response = client.post(
        WORKSPACES_URL,
        json={"name": "Private"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_failed"


def test_workspace_list_only_includes_current_users_memberships(app, client):
    owner = create_user("owner@example.test")
    other = create_user("other@example.test")
    db.session.commit()
    login(client, owner.email)
    created = create_workspace(client, "Owner workspace")
    assert created.status_code == 201

    other_client = app.test_client()
    login(other_client, other.email)
    response = other_client.get(WORKSPACES_URL)

    assert response.status_code == 200
    assert response.get_json()["workspaces"] == []


def test_nonmember_cannot_read_or_modify_workspace(client):
    owner = create_user("owner@example.test")
    nonmember = create_user("visitor@example.test")
    db.session.commit()
    login(client, owner.email)
    created = create_workspace(client)
    workspace_id = created.get_json()["workspace"]["id"]

    visitor = client.application.test_client()
    login(visitor, nonmember.email)
    expected = {
        "error": "workspace_not_found",
        "message": "The workspace was not found.",
    }
    read_response = visitor.get(f"{WORKSPACES_URL}/{workspace_id}")
    update_response = visitor.patch(
        f"{WORKSPACES_URL}/{workspace_id}",
        json={"name": "Stolen"},
        headers=csrf_headers(visitor),
    )

    assert read_response.status_code == update_response.status_code == 404
    assert read_response.get_json() == update_response.get_json() == expected
    assert db.session.get(Workspace, workspace_id).name == "Research"


def test_owner_admin_and_member_permissions(client, app):
    owner = create_user("owner@example.test")
    admin = create_user("admin@example.test")
    member = create_user("member@example.test")
    db.session.commit()
    login(client, owner.email)
    created = create_workspace(client)
    workspace_id = created.get_json()["workspace"]["id"]
    workspace = db.session.get(Workspace, workspace_id)
    add_member(workspace, admin, "admin")
    add_member(workspace, member, "member")
    db.session.commit()

    admin_client = app.test_client()
    login(admin_client, admin.email)
    admin_update = admin_client.patch(
        f"{WORKSPACES_URL}/{workspace_id}",
        json={"name": "Admin update"},
        headers=csrf_headers(admin_client),
    )
    assert admin_update.status_code == 200
    admin_members = admin_client.get(f"{WORKSPACES_URL}/{workspace_id}/members")
    assert admin_members.status_code == 200
    assert len(admin_members.get_json()["members"]) == 3

    member_client = app.test_client()
    login(member_client, member.email)
    member_update = member_client.patch(
        f"{WORKSPACES_URL}/{workspace_id}",
        json={"name": "Unauthorized update"},
        headers=csrf_headers(member_client),
    )
    assert member_update.status_code == 403
    assert member_update.get_json()["error"] == "permission_denied"

    members_response = member_client.get(f"{WORKSPACES_URL}/{workspace_id}/members")
    assert members_response.status_code == 200
    assert all("email" not in item for item in members_response.get_json()["members"])
    assert db.session.get(Workspace, workspace_id).name == "Admin update"


def test_member_listing_and_workspace_access_are_membership_scoped(client):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    db.session.commit()
    login(client, owner.email)
    created = create_workspace(client, "Members")
    workspace_id = created.get_json()["workspace"]["id"]
    workspace = db.session.get(Workspace, workspace_id)
    add_member(workspace, member, "member")
    db.session.commit()

    member_client = client.application.test_client()
    login(member_client, member.email)
    workspace_response = member_client.get(f"{WORKSPACES_URL}/{workspace_id}")
    members_response = member_client.get(f"{WORKSPACES_URL}/{workspace_id}/members")

    assert workspace_response.status_code == 200
    assert workspace_response.get_json()["workspace"]["role"] == "member"
    assert members_response.status_code == 200
    assert all("email" not in member for member in members_response.get_json()["members"])


def test_workspace_creation_rolls_back_workspace_and_owner_membership(client, monkeypatch):
    owner = create_user("owner@example.test")
    db.session.commit()
    login(client, owner.email)

    def fail_commit():
        raise SQLAlchemyError("injected commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = create_workspace(client)

    assert response.status_code == 500
    assert db.session.scalar(select(func.count()).select_from(Workspace)) == 0
    assert db.session.scalar(select(func.count()).select_from(WorkspaceMembership)) == 0


def test_duplicate_membership_and_second_owner_are_rejected(client):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    db.session.commit()
    login(client, owner.email)
    created = create_workspace(client)
    workspace = db.session.get(Workspace, created.get_json()["workspace"]["id"])
    add_member(workspace, member, "member")
    db.session.commit()

    db.session.add(WorkspaceMembership(workspace=workspace, user=member, role="member"))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
    else:
        raise AssertionError("Duplicate membership was accepted.")

    workspace = db.session.get(Workspace, workspace.id)
    other = create_user("other@example.test")
    db.session.commit()
    workspace = db.session.get(Workspace, workspace.id)
    db.session.add(WorkspaceMembership(workspace=workspace, user=other, role="owner"))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
    else:
        raise AssertionError("A second workspace owner was accepted.")

    workspace = db.session.get(Workspace, workspace.id)
    db.session.add(WorkspaceMembership(workspace=workspace, user=other, role="observer"))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
    else:
        raise AssertionError("An unsupported membership role was accepted.")


def test_owner_can_transfer_to_existing_member_without_becoming_ownerless(client):
    owner = create_user("owner@example.test")
    target = create_user("target@example.test")
    db.session.commit()
    login(client, owner.email)
    created = create_workspace(client)
    workspace_id = created.get_json()["workspace"]["id"]
    workspace = db.session.get(Workspace, workspace_id)
    add_member(workspace, target, "member")
    db.session.commit()

    response = client.post(
        f"{WORKSPACES_URL}/{workspace_id}/transfer-ownership",
        json={"user_id": target.id},
        headers=csrf_headers(client),
    )

    assert response.status_code == 200
    assert response.get_json()["workspace"]["owner_id"] == target.id
    assert response.get_json()["workspace"]["role"] == "admin"
    assert workspace.owner_id == target.id
    assert {membership.user_id: membership.role for membership in workspace.memberships} == {
        owner.id: "admin",
        target.id: "owner",
    }


def test_only_owner_can_transfer_and_target_must_already_be_a_member(client, app):
    owner = create_user("owner@example.test")
    admin = create_user("admin@example.test")
    outsider = create_user("outsider@example.test")
    db.session.commit()
    login(client, owner.email)
    created = create_workspace(client)
    workspace_id = created.get_json()["workspace"]["id"]
    workspace = db.session.get(Workspace, workspace_id)
    add_member(workspace, admin, "admin")
    db.session.commit()

    admin_client = app.test_client()
    login(admin_client, admin.email)
    denied = admin_client.post(
        f"{WORKSPACES_URL}/{workspace_id}/transfer-ownership",
        json={"user_id": outsider.id},
        headers=csrf_headers(admin_client),
    )
    invalid_target = client.post(
        f"{WORKSPACES_URL}/{workspace_id}/transfer-ownership",
        json={"user_id": outsider.id},
        headers=csrf_headers(client),
    )

    assert denied.status_code == 403
    assert invalid_target.status_code == 400
    assert workspace.owner_id == owner.id
    assert [item.role for item in workspace.memberships if item.role == "owner"] == ["owner"]


def test_owner_membership_cannot_be_removed_or_owner_user_deleted(client):
    owner = create_user("owner@example.test")
    db.session.commit()
    owner_id = owner.id
    login(client, owner.email)
    created = create_workspace(client)
    workspace_id = created.get_json()["workspace"]["id"]

    removal = client.delete(
        f"{WORKSPACES_URL}/{workspace_id}/members/{owner_id}",
        headers=csrf_headers(client),
    )
    assert removal.status_code == 404

    db.session.delete(db.session.get(User, owner_id))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
    else:
        raise AssertionError("Deleting the owner removed the workspace owner.")

    workspace = db.session.get(Workspace, workspace_id)
    assert workspace is not None
    assert workspace.owner_id == owner_id
    assert [(item.user_id, item.role) for item in workspace.memberships] == [(owner_id, "owner")]


def test_only_owner_can_delete_and_deletion_cascades_memberships(client, app):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    db.session.commit()
    login(client, owner.email)
    created = create_workspace(client)
    workspace_id = created.get_json()["workspace"]["id"]
    workspace = db.session.get(Workspace, workspace_id)
    add_member(workspace, member, "member")
    db.session.commit()

    member_client = app.test_client()
    login(member_client, member.email)
    denied = member_client.delete(
        f"{WORKSPACES_URL}/{workspace_id}",
        headers=csrf_headers(member_client),
    )
    assert denied.status_code == 403
    assert db.session.get(Workspace, workspace_id) is not None

    deleted = client.delete(
        f"{WORKSPACES_URL}/{workspace_id}",
        headers=csrf_headers(client),
    )

    assert deleted.status_code == 200
    assert deleted.get_json()["status"] == "ok"
    assert db.session.get(Workspace, workspace_id) is None
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
        )
        == 0
    )


def test_workspace_schema_has_required_constraints_and_indexes():
    workspace_table = Workspace.__table__
    membership_table = WorkspaceMembership.__table__
    membership_uniques = {
        constraint.name
        for constraint in membership_table.constraints
        if constraint.name == "uq_workspace_memberships_workspace_user"
    }

    assert workspace_table.c.owner_id.nullable is False
    assert workspace_table.c.name.type.length == 120
    assert workspace_table.c.created_at.type.timezone is True
    assert workspace_table.c.updated_at.type.timezone is True
    owner_foreign_key = next(iter(workspace_table.c.owner_id.foreign_keys))
    assert owner_foreign_key.ondelete == "RESTRICT"
    assert membership_uniques == {"uq_workspace_memberships_workspace_user"}
    assert membership_table.c.workspace_id.nullable is False
    assert membership_table.c.user_id.nullable is False
    assert membership_table.c.created_at.type.timezone is True
    assert membership_table.c.updated_at.type.timezone is True
    indexes = {index.name: index for index in membership_table.indexes}
    assert set(indexes) == {
        "ix_workspace_memberships_user_id",
        "uq_workspace_memberships_single_owner",
    }
    owner_index = indexes["uq_workspace_memberships_single_owner"]
    assert str(owner_index.dialect_options["postgresql"]["where"]) == "role = 'owner'"
    assert str(owner_index.dialect_options["sqlite"]["where"]) == "role = 'owner'"


def test_workspace_cors_allows_credentialed_patch_and_delete(client):
    response = client.options(
        WORKSPACES_URL,
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert "DELETE" in response.headers["Access-Control-Allow-Methods"]
