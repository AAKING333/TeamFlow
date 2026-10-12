from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import (
    Project,
    Task,
    TaskActivity,
    TaskComment,
    User,
    Workspace,
    WorkspaceMembership,
)

BASE = "/api/v1/workspaces"
PASSWORD = "discussion-password-8"


def csrf_headers(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.get_json()["csrf_token"]}


def create_user(email: str) -> User:
    user = User(name=email.split("@")[0], email=email)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.flush()
    return user


def make_scope(owner: User, name: str = "Team") -> tuple[Workspace, Project, Task]:
    workspace = Workspace(name=name, owner=owner)
    workspace.memberships.append(WorkspaceMembership(user=owner, role="owner"))
    project = Project(workspace=workspace, name="Product")
    task = Task(project=project, title="Plan release")
    db.session.add(workspace)
    db.session.flush()
    return workspace, project, task


def add_member(workspace: Workspace, user: User, role: str = "member") -> None:
    db.session.add(WorkspaceMembership(workspace=workspace, user=user, role=role))
    db.session.flush()


def login(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200


def task_path(workspace_id: int, project_id: int, task_id: int) -> str:
    return f"{BASE}/{workspace_id}/projects/{project_id}/tasks/{task_id}"


def comments_path(workspace_id: int, project_id: int, task_id: int) -> str:
    return f"{task_path(workspace_id, project_id, task_id)}/comments"


def activity_path(workspace_id: int, project_id: int) -> str:
    return f"{BASE}/{workspace_id}/projects/{project_id}/activity"


def test_comments_create_list_and_author_can_edit_and_delete(client):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    workspace, project, task = make_scope(owner)
    add_member(workspace, member)
    workspace_id, project_id, task_id = workspace.id, project.id, task.id
    db.session.commit()
    login(client, member.email)

    created = client.post(
        comments_path(workspace_id, project_id, task_id),
        json={"body": "  Looks good.  "},
        headers=csrf_headers(client),
    )
    assert created.status_code == 201
    comment = created.get_json()["comment"]
    comment_id = comment["id"]
    assert comment["body"] == "Looks good."
    assert comment["author"] == {"id": member.id, "name": "member"}

    listed = client.get(comments_path(workspace_id, project_id, task_id))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.get_json()["comments"]] == [comment_id]

    updated = client.patch(
        f"{comments_path(workspace_id, project_id, task_id)}/{comment_id}",
        json={"body": "Updated note"},
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.get_json()["comment"]["body"] == "Updated note"
    assert db.session.get(TaskComment, comment_id).body == "Updated note"

    deleted = client.delete(
        f"{comments_path(workspace_id, project_id, task_id)}/{comment_id}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 200
    assert db.session.get(TaskComment, comment_id) is None


def test_comment_validation_permissions_and_admin_moderation(client, app):
    owner = create_user("owner@example.test")
    author = create_user("author@example.test")
    other_member = create_user("other-member@example.test")
    outsider = create_user("outsider@example.test")
    workspace, project, task = make_scope(owner)
    add_member(workspace, author)
    add_member(workspace, other_member)
    workspace_id, project_id, task_id = workspace.id, project.id, task.id
    comment = TaskComment(task=task, author=author, body="Original")
    db.session.add(comment)
    db.session.commit()
    comment_id = comment.id
    login(client, other_member.email)

    for payload in ({}, {"body": ""}, {"body": "x" * 4001}, {"body": "Ok", "extra": 1}):
        response = client.post(
            comments_path(workspace_id, project_id, task_id),
            json=payload,
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "validation_error"

    forbidden = client.patch(
        f"{comments_path(workspace_id, project_id, task_id)}/{comment_id}",
        json={"body": "Hijacked"},
        headers=csrf_headers(client),
    )
    assert forbidden.status_code == 403
    assert db.session.get(TaskComment, comment_id).body == "Original"

    owner_client = app.test_client()
    login(owner_client, owner.email)
    moderated = owner_client.patch(
        f"{comments_path(workspace_id, project_id, task_id)}/{comment_id}",
        json={"body": "Moderated"},
        headers=csrf_headers(owner_client),
    )
    assert moderated.status_code == 200
    assert db.session.get(TaskComment, comment_id).body == "Moderated"

    outsider_client = app.test_client()
    login(outsider_client, outsider.email)
    inaccessible = outsider_client.get(comments_path(workspace_id, project_id, task_id))
    assert inaccessible.status_code == 404
    assert inaccessible.get_json()["error"] == "workspace_not_found"


def test_comments_require_auth_csrf_and_correct_task_scope(client):
    owner = create_user("owner@example.test")
    workspace, project, task = make_scope(owner)
    other_task = Task(project=project, title="Other task")
    db.session.add(other_task)
    db.session.commit()
    workspace_id, project_id, task_id, other_task_id = (
        workspace.id,
        project.id,
        task.id,
        other_task.id,
    )

    assert client.get(comments_path(workspace_id, project_id, task_id)).status_code == 401
    login(client, owner.email)
    missing_csrf = client.post(
        comments_path(workspace_id, project_id, task_id),
        json={"body": "No token"},
    )
    assert missing_csrf.status_code == 403

    created = client.post(
        comments_path(workspace_id, project_id, task_id),
        json={"body": "Scoped"},
        headers=csrf_headers(client),
    )
    comment_id = created.get_json()["comment"]["id"]
    wrong_task = client.patch(
        f"{comments_path(workspace_id, project_id, other_task_id)}/{comment_id}",
        json={"body": "Wrong task"},
        headers=csrf_headers(client),
    )
    assert wrong_task.status_code == 404
    assert wrong_task.get_json()["error"] == "comment_not_found"
    assert db.session.get(TaskComment, comment_id).body == "Scoped"


def test_task_activity_tracks_changes_and_survives_task_deletion(client):
    owner = create_user("owner@example.test")
    workspace, project, task = make_scope(owner)
    workspace_id, project_id, task_id = workspace.id, project.id, task.id
    db.session.commit()
    login(client, owner.email)

    created_task = client.post(
        f"{BASE}/{workspace_id}/projects/{project_id}/tasks",
        json={"title": "  Build timeline  "},
        headers=csrf_headers(client),
    )
    assert created_task.status_code == 201
    created_id = created_task.get_json()["task"]["id"]
    update = client.patch(
        task_path(workspace_id, project_id, created_id),
        json={
            "title": "Timeline",
            "description": "Details",
            "status": "in_progress",
            "priority": "high",
            "due_date": "2026-11-02",
        },
        headers=csrf_headers(client),
    )
    assert update.status_code == 200

    activities = client.get(f"{activity_path(workspace_id, project_id)}?task_id={created_id}")
    assert activities.status_code == 200
    events = activities.get_json()["activities"]
    assert [event["event_type"] for event in events] == [
        "task_due_date_changed",
        "task_priority_changed",
        "task_status_changed",
        "task_description_changed",
        "task_title_changed",
        "task_created",
    ]
    assert events[2]["data"] == {"from": "todo", "to": "in_progress"}
    assert events[0]["data"] == {"from": None, "to": "2026-11-02"}
    assert events[0]["actor"] == {"id": owner.id, "name": "owner"}

    deleted = client.delete(
        task_path(workspace_id, project_id, created_id),
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 200
    assert db.session.get(Task, created_id) is None
    deletion_event = client.get(activity_path(workspace_id, project_id)).get_json()["activities"][0]
    assert deletion_event["event_type"] == "task_deleted"
    assert deletion_event["task_id"] is None
    assert deletion_event["data"] == {"task_title": "Timeline"}
    assert deletion_event["project_id"] == project_id
    assert deletion_event["workspace_id"] == workspace_id
    assert task.id == task_id


def test_activity_scope_pagination_and_foreign_workspace_protection(client, app):
    owner = create_user("owner@example.test")
    outsider = create_user("outsider@example.test")
    first, first_project, first_task = make_scope(owner, "First")
    second_project = Project(workspace=first, name="Second")
    second_task = Task(project=second_project, title="Another task")
    db.session.add(second_project)
    db.session.flush()
    db.session.add(second_task)
    db.session.add(
        TaskActivity(
            workspace_id=first.id,
            project_id=first_project.id,
            task_id=first_task.id,
            actor_id=owner.id,
            event_type="task_created",
            data={},
        )
    )
    db.session.commit()
    first_id, first_project_id, second_project_id = first.id, first_project.id, second_project.id
    login(client, owner.email)

    response = client.get(f"{activity_path(first_id, first_project_id)}?limit=1&offset=0")
    assert response.status_code == 200
    assert len(response.get_json()["activities"]) == 1
    assert response.get_json()["limit"] == 1
    invalid = client.get(f"{activity_path(first_id, first_project_id)}?limit=101")
    assert invalid.status_code == 400
    wrong_task = client.get(f"{activity_path(first_id, first_project_id)}?task_id={second_task.id}")
    assert wrong_task.status_code == 404

    outsider_client = app.test_client()
    login(outsider_client, outsider.email)
    hidden = outsider_client.get(activity_path(first_id, first_project_id))
    assert hidden.status_code == 404
    assert hidden.get_json()["error"] == "workspace_not_found"
    cross_project = client.get(
        activity_path(first_id, second_project_id) + f"?task_id={first_task.id}"
    )
    assert cross_project.status_code == 404


def test_activity_and_task_mutation_roll_back_together(client, monkeypatch):
    owner = create_user("owner@example.test")
    workspace, project, _task = make_scope(owner)
    workspace_id, project_id = workspace.id, project.id
    db.session.commit()
    login(client, owner.email)

    def fail_commit():
        raise SQLAlchemyError("injected task activity commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = client.post(
        f"{BASE}/{workspace_id}/projects/{project_id}/tasks",
        json={"title": "No partial event"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 500
    assert "injected task activity commit failure" not in response.get_data(as_text=True)
    assert db.session.scalar(select(func.count()).select_from(Task)) == 1
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(TaskActivity)
            .where(TaskActivity.event_type == "task_created")
        )
        == 0
    )


def test_comment_and_activity_rows_follow_parent_deletion_behavior(app):
    owner = create_user("owner@example.test")
    workspace, project, task = make_scope(owner)
    comment = TaskComment(task=task, author=owner, body="Will cascade")
    db.session.add(comment)
    db.session.add(
        TaskActivity(
            workspace_id=workspace.id,
            project_id=project.id,
            task_id=task.id,
            actor_id=owner.id,
            event_type="task_created",
            data={},
        )
    )
    project_id, workspace_id = project.id, workspace.id
    db.session.commit()
    comment_id = comment.id

    db.session.delete(task)
    db.session.commit()
    assert db.session.get(TaskComment, comment_id) is None
    task_events = db.session.scalars(
        select(TaskActivity).where(TaskActivity.project_id == project_id)
    ).all()
    assert task_events
    assert all(event.task_id is None for event in task_events)

    project = db.session.get(Project, project_id)
    assert project is not None
    db.session.delete(project)
    db.session.commit()
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(TaskActivity)
            .where(TaskActivity.project_id == project_id)
        )
        == 0
    )

    workspace = db.session.get(Workspace, workspace_id)
    assert workspace is not None
    db.session.delete(workspace)
    db.session.commit()


def test_activity_text_change_payload_requires_a_real_boolean(app):
    owner = create_user("owner@example.test")
    workspace, project, task = make_scope(owner)

    with pytest.raises(ValueError, match="text activity data"):
        TaskActivity(
            workspace_id=workspace.id,
            project_id=project.id,
            task_id=task.id,
            actor_id=owner.id,
            event_type="task_title_changed",
            data={"changed": 1},
        )
