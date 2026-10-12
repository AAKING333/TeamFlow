from __future__ import annotations

from datetime import date

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models import Project, Task, User, Workspace, WorkspaceMembership

API_URL = "/api/v1/workspaces"
TEST_PASSWORD = "task-password-8"


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


def create_workspace(owner: User, name: str) -> Workspace:
    workspace = Workspace(name=name, owner=owner)
    workspace.memberships.append(WorkspaceMembership(user=owner, role="owner"))
    db.session.add(workspace)
    db.session.flush()
    return workspace


def add_member(workspace: Workspace, user: User) -> None:
    db.session.add(WorkspaceMembership(workspace=workspace, user=user, role="member"))
    db.session.flush()


def create_project(workspace: Workspace, name: str = "Planning") -> Project:
    project = Project(workspace=workspace, name=name)
    db.session.add(project)
    db.session.flush()
    return project


def create_task(project: Project, title: str = "Review scope", **kwargs) -> Task:
    task = Task(project=project, title=title, **kwargs)
    db.session.add(task)
    db.session.flush()
    return task


def login(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200


def task_url(workspace_id: int, project_id: int, task_id: int | None = None) -> str:
    path = f"{API_URL}/{workspace_id}/projects/{project_id}/tasks"
    return f"{path}/{task_id}" if task_id is not None else path


def test_task_crud_and_filters_preserve_fields_and_assignee(client):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    workspace = create_workspace(owner, "Team")
    project = create_project(workspace)
    add_member(workspace, member)
    workspace_id, project_id, member_id = workspace.id, project.id, member.id
    db.session.commit()
    login(client, owner.email)

    created = client.post(
        task_url(workspace_id, project_id),
        json={
            "title": "  Prepare release  ",
            "description": "  Final review  ",
            "status": "in_progress",
            "priority": "high",
            "due_date": "2026-11-01",
            "assignee_id": member_id,
        },
        headers=csrf_headers(client),
    )
    assert created.status_code == 201
    response_task = created.get_json()["task"]
    task_id = response_task["id"]
    assert response_task["title"] == "Prepare release"
    assert response_task["description"] == "Final review"
    assert response_task["status"] == "in_progress"
    assert response_task["priority"] == "high"
    assert response_task["due_date"] == "2026-11-01"
    assert response_task["assignee"] == {"id": member_id, "name": "member"}
    assert response_task["created_at"].endswith("+00:00")

    listed = client.get(task_url(workspace_id, project_id))
    filtered = client.get(f"{task_url(workspace_id, project_id)}?status=in_progress&priority=high")
    assert [task["id"] for task in listed.get_json()["tasks"]] == [task_id]
    assert [task["id"] for task in filtered.get_json()["tasks"]] == [task_id]
    assert client.get(f"{task_url(workspace_id, project_id)}?status=done").get_json()["tasks"] == []
    assert client.get(f"{task_url(workspace_id, project_id)}?priority=urgent").status_code == 400

    retrieved = client.get(task_url(workspace_id, project_id, task_id))
    assert retrieved.status_code == 200
    updated = client.patch(
        task_url(workspace_id, project_id, task_id),
        json={"title": "Release review", "status": "done", "assignee_id": None},
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    persisted = db.session.get(Task, task_id)
    assert persisted is not None
    assert persisted.title == "Release review"
    assert persisted.status == "done"
    assert persisted.assignee_id is None

    deleted = client.delete(
        task_url(workspace_id, project_id, task_id),
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 200
    assert db.session.get(Task, task_id) is None


def test_task_creation_validates_fields_and_assignee_membership(client):
    owner = create_user("owner@example.test")
    stranger = create_user("stranger@example.test")
    workspace = create_workspace(owner, "Team")
    other_workspace = create_workspace(stranger, "Other")
    project = create_project(workspace)
    other_member = create_user("other-member@example.test")
    add_member(other_workspace, other_member)
    workspace_id, project_id, stranger_id, other_member_id = (
        workspace.id,
        project.id,
        stranger.id,
        other_member.id,
    )
    db.session.commit()
    login(client, owner.email)

    invalid_payloads = (
        ({}, "title"),
        ({"title": " "}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"title": "Valid", "status": "blocked"}, "status"),
        ({"title": "Valid", "priority": "urgent"}, "priority"),
        ({"title": "Valid", "due_date": "2026-02-30"}, "due_date"),
        ({"title": "Valid", "assignee_id": True}, "assignee_id"),
        ({"title": "Valid", "unknown": 1}, "unknown"),
    )
    for payload, field in invalid_payloads:
        response = client.post(
            task_url(workspace_id, project_id),
            json=payload,
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert field in response.get_json()["fields"]

    bad_assignee = client.post(
        task_url(workspace_id, project_id),
        json={"title": "Cross-tenant", "assignee_id": stranger_id},
        headers=csrf_headers(client),
    )
    assert bad_assignee.status_code == 400
    assert "assignee_id" in bad_assignee.get_json()["fields"]
    cross_workspace_assignee = client.post(
        task_url(workspace_id, project_id),
        json={"title": "Cross-workspace", "assignee_id": other_member_id},
        headers=csrf_headers(client),
    )
    assert cross_workspace_assignee.status_code == 400
    assert db.session.scalar(select(func.count()).select_from(Task)) == 0

    task = create_task(project)
    task_id = task.id
    db.session.commit()
    reassigned = client.patch(
        task_url(workspace_id, project_id, task_id),
        json={"assignee_id": stranger_id},
        headers=csrf_headers(client),
    )
    assert reassigned.status_code == 400
    assert "assignee_id" in reassigned.get_json()["fields"]
    persisted = db.session.get(Task, task_id)
    assert persisted is not None
    assert persisted.assignee_id is None


def test_task_endpoints_require_auth_and_csrf(client):
    response = client.get(task_url(1, 1))
    assert response.status_code == 401

    owner = create_user("owner@example.test")
    workspace = create_workspace(owner, "Team")
    project = create_project(workspace)
    workspace_id, project_id = workspace.id, project.id
    db.session.commit()
    login(client, owner.email)

    response = client.post(task_url(workspace_id, project_id), json={"title": "No token"})
    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_token_invalid"
    assert db.session.scalar(select(func.count()).select_from(Task)) == 0


def test_members_can_create_and_update_but_not_delete_tasks(client):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    workspace = create_workspace(owner, "Team")
    project = create_project(workspace)
    task = create_task(project)
    add_member(workspace, member)
    workspace_id, project_id, task_id = workspace.id, project.id, task.id
    db.session.commit()
    login(client, member.email)

    created = client.post(
        task_url(workspace_id, project_id),
        json={"title": "Member task"},
        headers=csrf_headers(client),
    )
    updated = client.patch(
        task_url(workspace_id, project_id, task_id),
        json={"status": "done", "priority": "low"},
        headers=csrf_headers(client),
    )
    deleted = client.delete(
        task_url(workspace_id, project_id, task_id),
        headers=csrf_headers(client),
    )
    assert created.status_code == 201
    assert updated.status_code == 200
    assert deleted.status_code == 403
    persisted = db.session.get(Task, task_id)
    assert persisted is not None
    assert persisted.status == "done"
    assert persisted.priority == "low"
    assert db.session.scalar(select(func.count()).select_from(Task)) == 2


def test_nonmembers_cannot_access_tasks_and_cross_project_ids_are_hidden(client, app):
    owner = create_user("owner@example.test")
    outsider = create_user("outsider@example.test")
    workspace = create_workspace(owner, "Team")
    first_project = create_project(workspace, "First")
    second_project = create_project(workspace, "Second")
    task = create_task(first_project, "Private task")
    workspace_id, first_id, second_id, task_id = (
        workspace.id,
        first_project.id,
        second_project.id,
        task.id,
    )
    db.session.commit()

    outsider_client = app.test_client()
    login(outsider_client, outsider.email)
    denied = outsider_client.get(task_url(workspace_id, first_id))
    assert denied.status_code == 404
    assert denied.get_json()["error"] == "workspace_not_found"

    login(client, owner.email)
    for method, path, kwargs in (
        ("get", task_url(workspace_id, second_id, task_id), {}),
        (
            "patch",
            task_url(workspace_id, second_id, task_id),
            {"json": {"title": "Tampered"}, "headers": csrf_headers(client)},
        ),
        (
            "delete",
            task_url(workspace_id, second_id, task_id),
            {"headers": csrf_headers(client)},
        ),
    ):
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404
        assert response.get_json()["error"] == "task_not_found"

    assert db.session.get(Task, task_id).title == "Private task"


def test_task_constraints_and_project_workspace_cascades(app, client):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner, "Team")
    project = create_project(workspace)
    task = create_task(project, due_date=date(2026, 12, 1))
    project_id, workspace_id, task_id = project.id, workspace.id, task.id
    db.session.commit()

    login(client, owner.email)
    deleted_project = client.delete(
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}",
        headers=csrf_headers(client),
    )
    assert deleted_project.status_code == 200
    assert db.session.get(Task, task_id) is None

    project = create_project(db.session.get(Workspace, workspace_id))
    task = create_task(project)
    task_id = task.id
    db.session.commit()
    workspace = db.session.get(Workspace, workspace_id)
    assert workspace is not None
    db.session.delete(workspace)
    db.session.commit()
    assert db.session.get(Task, task_id) is None


def test_database_rejects_invalid_task_enum_and_assignee_references(app):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner, "Team")
    project = create_project(workspace)
    project_id = project.id
    db.session.commit()

    if db.engine.dialect.name == "sqlite":
        db.session.execute(db.text("PRAGMA foreign_keys=ON"))
    invalid_rows = (
        {
            "project_id": project_id,
            "title": "Invalid status",
            "status": "blocked",
            "priority": "medium",
        },
        {
            "project_id": project_id,
            "title": "Invalid priority",
            "status": "todo",
            "priority": "urgent",
        },
        {
            "project_id": project_id,
            "title": "Orphan assignee",
            "status": "todo",
            "priority": "medium",
            "assignee_id": 999999,
        },
    )
    for values in invalid_rows:
        try:
            db.session.execute(insert(Task).values(**values))
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
        else:
            raise AssertionError("Invalid task data passed database constraints.")

    assert db.session.scalar(select(func.count()).select_from(Task)) == 0


def test_task_update_rejects_invalid_data_and_rolls_back_commit_error(client, monkeypatch):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner, "Team")
    project = create_project(workspace)
    task = create_task(project)
    workspace_id, project_id, task_id = workspace.id, project.id, task.id
    db.session.commit()
    login(client, owner.email)

    for payload in ({}, {"title": ""}, {"status": "blocked"}, {"due_date": "bad"}):
        response = client.patch(
            task_url(workspace_id, project_id, task_id),
            json=payload,
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
    assert db.session.get(Task, task_id).title == "Review scope"

    def fail_commit():
        raise SQLAlchemyError("injected task commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = client.post(
        task_url(workspace_id, project_id),
        json={"title": "Will roll back"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 500
    assert "injected task commit failure" not in response.get_data(as_text=True)
    assert db.session.scalar(select(func.count()).select_from(Task)) == 1
