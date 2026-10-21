from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models import Project, User, Workspace, WorkspaceMembership

PROJECTS_URL = "/api/v1/workspaces"
TEST_PASSWORD = "project-password-8"


def csrf_headers(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.get_json()["csrf_token"]}


def create_user(email: str) -> User:
    user = User(name=email.split("@")[0], email=email)
    user.set_password(TEST_PASSWORD)
    db.session.add(user)
    db.session.flush()
    return user


def create_workspace(owner: User, name: str = "Workspace") -> Workspace:
    workspace = Workspace(name=name, owner=owner)
    workspace.memberships.append(WorkspaceMembership(user=owner, role="owner"))
    db.session.add(workspace)
    db.session.flush()
    return workspace


def add_member(workspace: Workspace, user: User, role: str) -> None:
    db.session.add(WorkspaceMembership(workspace=workspace, user=user, role=role))
    db.session.flush()


def login(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200


def create_project(client, workspace_id: int, payload=None):
    return client.post(
        f"{PROJECTS_URL}/{workspace_id}/projects",
        json=payload if payload is not None else {"name": "Roadmap"},
        headers=csrf_headers(client),
    )


def project_url(workspace_id: int, project_id: int) -> str:
    return f"{PROJECTS_URL}/{workspace_id}/projects/{project_id}"


def make_project(workspace: Workspace, name: str = "Roadmap") -> Project:
    project = Project(workspace=workspace, name=name)
    db.session.add(project)
    db.session.flush()
    return project


def test_project_creation_persists_valid_fields_and_returns_utc_timestamps(client):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner)
    workspace_id = workspace.id
    db.session.commit()
    login(client, owner.email)

    response = create_project(
        client,
        workspace_id,
        {"name": "  Platform  ", "description": "  Build foundations  "},
    )

    assert response.status_code == 201
    payload = response.get_json()["project"]
    assert payload["workspace_id"] == workspace_id
    assert payload["name"] == "Platform"
    assert payload["description"] == "Build foundations"
    assert payload["created_at"].endswith("+00:00")
    assert payload["updated_at"].endswith("+00:00")
    project = db.session.get(Project, payload["id"])
    assert project is not None
    assert project.workspace_id == workspace_id


def test_project_creation_validates_required_name_and_description(client):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner)
    workspace_id = workspace.id
    db.session.commit()
    login(client, owner.email)

    invalid_payloads = [
        ({}, {"name"}),
        ({"name": "  "}, {"name"}),
        ({"name": "x" * 121}, {"name"}),
        ({"name": 42}, {"name"}),
        ({"name": "Valid", "description": 42}, {"description"}),
        ({"name": "Valid", "description": "x" * 2001}, {"description"}),
        ({"name": "Valid", "slug": "unexpected"}, {"slug"}),
    ]
    for payload, expected_fields in invalid_payloads:
        response = create_project(client, workspace_id, payload)
        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "validation_error"
        assert set(body["fields"]) == expected_fields

    assert db.session.scalar(select(func.count()).select_from(Project)) == 0


def test_project_routes_require_authentication(client):
    response = client.get(f"{PROJECTS_URL}/1/projects")
    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_failed"


def test_project_mutations_require_csrf(client):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner)
    workspace_id = workspace.id
    db.session.commit()
    login(client, owner.email)

    response = client.post(
        f"{PROJECTS_URL}/{workspace_id}/projects",
        json={"name": "No CSRF"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_token_invalid"
    assert db.session.scalar(select(func.count()).select_from(Project)) == 0


def test_listing_is_workspace_scoped_and_nonmembers_cannot_read(client, app):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    outsider = create_user("outsider@example.test")
    first_workspace = create_workspace(owner, "First")
    second_workspace = create_workspace(owner, "Second")
    first_project = make_project(first_workspace, "First project")
    second_project = make_project(second_workspace, "Second project")
    add_member(first_workspace, member, "member")
    first_workspace_id, second_workspace_id = first_workspace.id, second_workspace.id
    first_project_id = first_project.id
    second_project_id = second_project.id
    db.session.commit()
    login(client, member.email)

    first_response = client.get(f"{PROJECTS_URL}/{first_workspace_id}/projects")
    second_response = client.get(f"{PROJECTS_URL}/{second_workspace_id}/projects")
    assert first_response.status_code == 200
    assert [item["id"] for item in first_response.get_json()["projects"]] == [first_project_id]
    assert second_response.status_code == 404
    assert second_response.get_json()["error"] == "workspace_not_found"
    assert db.session.get(Project, second_project_id).name == "Second project"

    outsider_client = app.test_client()
    login(outsider_client, outsider.email)
    forbidden = outsider_client.get(f"{PROJECTS_URL}/{first_workspace_id}/projects")
    denied_create = create_project(
        outsider_client,
        first_workspace_id,
        {"name": "Unauthorized project"},
    )
    assert forbidden.status_code == 404
    assert forbidden.get_json()["error"] == "workspace_not_found"
    assert denied_create.status_code == 404
    assert denied_create.get_json()["error"] == "workspace_not_found"
    assert db.session.get(Project, first_project_id).name == "First project"
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(Project)
            .where(Project.workspace_id == first_workspace_id)
        )
        == 1
    )


def test_members_can_view_projects_and_single_project(client):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    workspace = create_workspace(owner)
    project = make_project(workspace)
    add_member(workspace, member, "member")
    workspace_id, project_id = workspace.id, project.id
    db.session.commit()
    login(client, member.email)

    listed = client.get(f"{PROJECTS_URL}/{workspace_id}/projects")
    retrieved = client.get(project_url(workspace_id, project_id))

    assert listed.status_code == retrieved.status_code == 200
    assert listed.get_json()["projects"][0]["id"] == project_id
    assert retrieved.get_json()["project"]["name"] == "Roadmap"
    assert retrieved.get_json()["project"]["workspace_id"] == workspace_id


def test_member_cannot_create_update_or_delete_projects(client):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    workspace = create_workspace(owner)
    project = make_project(workspace)
    add_member(workspace, member, "member")
    workspace_id, project_id = workspace.id, project.id
    db.session.commit()
    login(client, member.email)

    created = create_project(client, workspace_id, {"name": "Unauthorized"})
    updated = client.patch(
        project_url(workspace_id, project_id),
        json={"name": "Unauthorized rename"},
        headers=csrf_headers(client),
    )
    deleted = client.delete(
        project_url(workspace_id, project_id),
        headers=csrf_headers(client),
    )

    assert created.status_code == updated.status_code == deleted.status_code == 403
    assert all(
        response.get_json()["error"] == "permission_denied"
        for response in (
            created,
            updated,
            deleted,
        )
    )
    assert db.session.scalar(select(func.count()).select_from(Project)) == 1
    persisted = db.session.get(Project, project_id)
    assert persisted is not None
    assert persisted.name == "Roadmap"


def test_owner_and_admin_can_create_update_and_delete_projects(client, app):
    owner = create_user("owner@example.test")
    admin = create_user("admin@example.test")
    workspace = create_workspace(owner)
    add_member(workspace, admin, "admin")
    workspace_id = workspace.id
    db.session.commit()
    login(client, owner.email)

    owner_created = create_project(client, workspace_id, {"name": "Owner project"})
    assert owner_created.status_code == 201

    admin_client = app.test_client()
    login(admin_client, admin.email)
    admin_created = create_project(admin_client, workspace_id, {"name": "Admin project"})
    assert admin_created.status_code == 201
    admin_project_id = admin_created.get_json()["project"]["id"]

    updated = admin_client.patch(
        project_url(workspace_id, admin_project_id),
        json={"name": "Admin project renamed", "description": "Planning"},
        headers=csrf_headers(admin_client),
    )
    assert updated.status_code == 200
    assert updated.get_json()["project"]["name"] == "Admin project renamed"
    assert updated.get_json()["project"]["description"] == "Planning"

    deleted = admin_client.delete(
        project_url(workspace_id, admin_project_id),
        headers=csrf_headers(admin_client),
    )
    assert deleted.status_code == 200
    assert db.session.get(Project, admin_project_id) is None
    assert (
        db.session.scalar(
            select(func.count()).select_from(Project).where(Project.workspace_id == workspace_id)
        )
        == 1
    )


def test_cross_workspace_project_id_cannot_be_retrieved_updated_or_deleted(client):
    owner = create_user("owner@example.test")
    first_workspace = create_workspace(owner, "First")
    second_workspace = create_workspace(owner, "Second")
    project = make_project(first_workspace, "Protected")
    wrong_workspace_id = second_workspace.id
    project_id = project.id
    db.session.commit()
    login(client, owner.email)

    retrieved = client.get(project_url(wrong_workspace_id, project_id))
    updated = client.patch(
        project_url(wrong_workspace_id, project_id),
        json={"name": "Tampered"},
        headers=csrf_headers(client),
    )
    deleted = client.delete(
        project_url(wrong_workspace_id, project_id),
        headers=csrf_headers(client),
    )

    assert retrieved.status_code == updated.status_code == deleted.status_code == 404
    assert all(
        response.get_json()["error"] == "project_not_found"
        for response in (
            retrieved,
            updated,
            deleted,
        )
    )
    persisted = db.session.get(Project, project_id)
    assert persisted is not None
    assert persisted.workspace_id == first_workspace.id
    assert persisted.name == "Protected"


def test_mismatched_or_missing_workspace_and_project_ids_return_not_found(client):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner)
    project = make_project(workspace)
    workspace_id, project_id = workspace.id, project.id
    db.session.commit()
    login(client, owner.email)

    for path in (
        project_url(workspace_id + 999, project_id),
        project_url(workspace_id, project_id + 999),
    ):
        response = client.get(path)
        assert response.status_code == 404

    missing_workspace = client.get(f"{PROJECTS_URL}/999999/projects")
    assert missing_workspace.status_code == 404
    assert missing_workspace.get_json()["error"] == "workspace_not_found"

    malformed_workspace = client.get(f"{PROJECTS_URL}/not-an-id/projects")
    malformed_project = client.get(f"{PROJECTS_URL}/{workspace_id}/projects/not-an-id")
    assert malformed_workspace.status_code == 404
    assert malformed_project.status_code == 404
    assert malformed_workspace.get_json()["error"] == "not_found"
    assert malformed_project.get_json()["error"] == "not_found"


def test_project_update_rejects_empty_patch_and_invalid_fields_without_changes(client):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner)
    project = make_project(workspace)
    workspace_id, project_id = workspace.id, project.id
    db.session.commit()
    login(client, owner.email)

    for payload in ({}, {"name": ""}, {"name": "x" * 121}, {"other": "value"}):
        response = client.patch(
            project_url(workspace_id, project_id),
            json=payload,
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "validation_error"

    persisted = db.session.get(Project, project_id)
    assert persisted is not None
    assert persisted.name == "Roadmap"
    assert persisted.description is None


def test_database_constraints_prevent_orphan_and_oversized_project_data(app):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner)
    db.session.commit()

    db.session.add(Project(workspace_id=workspace.id + 100, name="Orphan"))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
    else:
        raise AssertionError("Project with an unknown workspace was accepted.")

    workspace = db.session.get(Workspace, workspace.id)
    try:
        db.session.add(Project(workspace=workspace, name="x" * 121))
        db.session.flush()
    except (IntegrityError, ValueError):
        db.session.rollback()
    else:
        raise AssertionError("Oversized project name was accepted.")

    assert db.session.scalar(select(func.count()).select_from(Project)) == 0


def test_project_creation_rolls_back_after_database_error(client, monkeypatch):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner)
    workspace_id = workspace.id
    db.session.commit()
    login(client, owner.email)

    def fail_commit():
        raise SQLAlchemyError("injected project commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = create_project(client, workspace_id, {"name": "Will roll back"})

    assert response.status_code == 500
    assert "injected project commit failure" not in response.get_data(as_text=True)
    assert db.session.scalar(select(func.count()).select_from(Project)) == 0


def test_deleting_project_and_workspace_cleans_up_project_rows(client):
    owner = create_user("owner@example.test")
    standalone_workspace = create_workspace(owner, "Standalone")
    workspace_with_projects = create_workspace(owner, "Parent")
    removable = make_project(standalone_workspace, "Removable")
    child_project = make_project(workspace_with_projects, "Child")
    standalone_id, removable_id = standalone_workspace.id, removable.id
    parent_id, child_id = workspace_with_projects.id, child_project.id
    db.session.commit()
    login(client, owner.email)

    response = client.delete(
        project_url(standalone_id, removable_id),
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    assert db.session.get(Project, removable_id) is None

    workspace_response = client.delete(
        f"{PROJECTS_URL}/{parent_id}",
        headers=csrf_headers(client),
    )
    assert workspace_response.status_code == 200
    assert db.session.get(Workspace, parent_id) is None
    assert db.session.get(Project, child_id) is None


def test_project_schema_constraints_and_index():
    table = Project.__table__
    foreign_key = next(iter(table.c.workspace_id.foreign_keys))
    assert table.c.workspace_id.nullable is False
    assert foreign_key.ondelete == "CASCADE"
    assert table.c.name.type.length == 120
    assert table.c.description.nullable is True
    assert table.c.created_at.type.timezone is True
    assert table.c.updated_at.type.timezone is True
    assert {index.name for index in table.indexes} == {"ix_projects_workspace_id"}
