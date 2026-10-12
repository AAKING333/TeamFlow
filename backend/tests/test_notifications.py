from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import (
    Notification,
    Project,
    Task,
    TaskActivity,
    TaskComment,
    User,
    Workspace,
    WorkspaceMembership,
)

BASE = "/api/v1"
PASSWORD = "notification-password-8"


def csrf_headers(client):
    response = client.get(f"{BASE}/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.get_json()["csrf_token"]}


def create_user(email: str) -> User:
    user = User(name=email.split("@")[0], email=email)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.flush()
    return user


def make_scope(owner: User, *members: User) -> tuple[Workspace, Project, Task]:
    workspace = Workspace(name="Notifications", owner=owner)
    workspace.memberships.append(WorkspaceMembership(user=owner, role="owner"))
    for member in members:
        workspace.memberships.append(WorkspaceMembership(user=member, role="member"))
    project = Project(workspace=workspace, name="Product")
    task = Task(project=project, title="Ship notifications")
    db.session.add(workspace)
    db.session.flush()
    return workspace, project, task


def login(client, email: str) -> None:
    response = client.post(
        f"{BASE}/auth/login",
        json={"email": email, "password": PASSWORD},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200


def add_notification(
    recipient: User,
    workspace: Workspace,
    project: Project,
    task: Task,
    dedupe_key: str,
) -> Notification:
    notification = Notification(
        recipient=recipient,
        notification_type="task_assigned",
        message="You were assigned to a task.",
        payload={},
        workspace=workspace,
        project=project,
        task=task,
        dedupe_key=dedupe_key,
    )
    db.session.add(notification)
    db.session.flush()
    return notification


def test_notifications_are_private_and_limited_to_current_memberships(client):
    owner = create_user("owner@example.test")
    recipient = create_user("recipient@example.test")
    outsider = create_user("outsider@example.test")
    workspace, project, task = make_scope(owner, recipient)
    other_workspace, other_project, other_task = make_scope(outsider)
    visible = add_notification(recipient, workspace, project, task, "visible")
    add_notification(recipient, other_workspace, other_project, other_task, "not-a-member")
    add_notification(outsider, workspace, project, task, "not-the-recipient")
    visible_id = visible.id
    db.session.commit()

    unauthenticated = client.get(f"{BASE}/notifications")
    assert unauthenticated.status_code == 401
    login(client, recipient.email)

    response = client.get(f"{BASE}/notifications")
    assert response.status_code == 200
    payload = response.get_json()
    assert [item["id"] for item in payload["notifications"]] == [visible_id]
    assert payload["unread_count"] == 1
    assert payload["notifications"][0]["payload"] == {}


def test_unread_count_and_read_state_changes_are_scoped(client):
    owner = create_user("owner@example.test")
    recipient = create_user("recipient@example.test")
    workspace, project, task = make_scope(owner, recipient)
    notification = add_notification(recipient, workspace, project, task, "read-flow")
    notification_id = notification.id
    db.session.commit()
    login(client, recipient.email)

    count = client.get(f"{BASE}/notifications/unread-count")
    assert count.get_json() == {"unread_count": 1}

    marked = client.post(
        f"{BASE}/notifications/{notification_id}/read",
        headers=csrf_headers(client),
    )
    assert marked.status_code == 200
    assert marked.get_json()["notification"]["read_at"] is not None
    assert marked.get_json()["unread_count"] == 0

    second = add_notification(recipient, workspace, project, task, "read-all-flow")
    db.session.commit()
    assert second.read_at is None
    all_marked = client.post(f"{BASE}/notifications/read-all", headers=csrf_headers(client))
    assert all_marked.status_code == 200
    assert all_marked.get_json()["unread_count"] == 0
    assert (
        db.session.scalar(select(func.count(Notification.id)).where(Notification.read_at.is_(None)))
        == 0
    )


def test_read_and_pagination_endpoints_validate_and_hide_other_users(client):
    owner = create_user("owner@example.test")
    recipient = create_user("recipient@example.test")
    workspace, project, task = make_scope(owner, recipient)
    notification = add_notification(recipient, workspace, project, task, "not-readable")
    notification_id = notification.id
    db.session.commit()
    login(client, owner.email)

    hidden = client.post(
        f"{BASE}/notifications/{notification_id}/read",
        headers=csrf_headers(client),
    )
    assert hidden.status_code == 404
    assert hidden.get_json()["error"] == "notification_not_found"
    csrf_rejected = client.post(f"{BASE}/notifications/{notification_id}/read")
    assert csrf_rejected.status_code == 403

    for query in ("?limit=0", "?limit=101", "?offset=-1", "?unknown=x", "?limit=1&limit=2"):
        invalid = client.get(f"{BASE}/notifications{query}")
        assert invalid.status_code == 400
        assert invalid.get_json()["error"] == "validation_error"


def test_task_assignment_and_comment_events_notify_only_recipient(client):
    owner = create_user("owner@example.test")
    assignee = create_user("assignee@example.test")
    next_assignee = create_user("next-assignee@example.test")
    workspace, project, task = make_scope(owner, assignee, next_assignee)
    workspace_id, project_id, task_id = workspace.id, project.id, task.id
    db.session.commit()
    login(client, owner.email)
    headers = csrf_headers(client)

    created = client.post(
        f"{BASE}/workspaces/{workspace_id}/projects/{project_id}/tasks",
        json={"title": "Assigned work", "assignee_id": assignee.id},
        headers=headers,
    )
    assert created.status_code == 201
    assigned_task_id = created.get_json()["task"]["id"]
    assignment_event = db.session.scalar(
        select(Notification).where(
            Notification.recipient_id == assignee.id,
            Notification.task_id == assigned_task_id,
        )
    )
    assert assignment_event is not None
    assert assignment_event.notification_type == "task_assigned"
    assert (
        db.session.scalar(
            select(func.count(Notification.id)).where(Notification.recipient_id == owner.id)
        )
        == 0
    )

    comment = client.post(
        f"{BASE}/workspaces/{workspace_id}/projects/{project_id}/tasks/{assigned_task_id}/comments",
        json={"body": "Progress update"},
        headers=csrf_headers(client),
    )
    assert comment.status_code == 201
    comment_event = db.session.scalar(
        select(Notification).where(
            Notification.recipient_id == assignee.id,
            Notification.task_id == assigned_task_id,
            Notification.notification_type == "task_comment",
        )
    )
    assert comment_event is not None
    assert (
        db.session.scalar(
            select(func.count(Notification.id)).where(Notification.recipient_id == owner.id)
        )
        == 0
    )

    own_comment = client.post(
        f"{BASE}/workspaces/{workspace_id}/projects/{project_id}/tasks/{task_id}/comments",
        json={"body": "As the assignee"},
        headers=csrf_headers(client),
    )
    assert own_comment.status_code == 201
    assert (
        db.session.scalar(
            select(func.count(Notification.id)).where(
                Notification.recipient_id == assignee.id,
                Notification.notification_type == "task_comment",
                Notification.task_id == task_id,
            )
        )
        == 0
    )

    login(client, assignee.email)
    assigned_user_comment = client.post(
        f"{BASE}/workspaces/{workspace_id}/projects/{project_id}/tasks/{assigned_task_id}/comments",
        json={"body": "I am the assignee."},
        headers=csrf_headers(client),
    )
    assert assigned_user_comment.status_code == 201
    assert (
        db.session.scalar(
            select(func.count(Notification.id)).where(
                Notification.recipient_id == assignee.id,
                Notification.notification_type == "task_comment",
                Notification.task_id == assigned_task_id,
            )
        )
        == 1
    )

    login(client, owner.email)
    task_url = f"{BASE}/workspaces/{workspace_id}/projects/{project_id}/tasks/{assigned_task_id}"
    reassigned = client.patch(
        task_url,
        json={"assignee_id": next_assignee.id},
        headers=csrf_headers(client),
    )
    assert reassigned.status_code == 200
    repeated = client.patch(
        task_url,
        json={"assignee_id": next_assignee.id},
        headers=csrf_headers(client),
    )
    assert repeated.status_code == 200
    assert (
        db.session.scalar(
            select(func.count(Notification.id)).where(
                Notification.recipient_id == next_assignee.id,
                Notification.notification_type == "task_assigned",
                Notification.task_id == assigned_task_id,
            )
        )
        == 1
    )


def test_failed_task_notification_rolls_back_task_and_activity(client, monkeypatch):
    from app.api import tasks as tasks_api

    owner = create_user("owner@example.test")
    assignee = create_user("assignee@example.test")
    workspace, project, _task = make_scope(owner, assignee)
    workspace_id, project_id = workspace.id, project.id
    db.session.commit()
    login(client, owner.email)

    def fail_assignment(**_kwargs):
        raise SQLAlchemyError("simulated notification failure")

    monkeypatch.setattr(tasks_api, "record_assignment_notification", fail_assignment)
    failed = client.post(
        f"{BASE}/workspaces/{workspace_id}/projects/{project_id}/tasks",
        json={"title": "Must roll back", "assignee_id": assignee.id},
        headers=csrf_headers(client),
    )
    assert failed.status_code == 500

    assert db.session.scalar(select(func.count(Task.id)).where(Task.title == "Must roll back")) == 0
    assert db.session.scalar(select(func.count(TaskActivity.id))) == 0
    assert db.session.scalar(select(func.count(Notification.id))) == 0


def test_failed_comment_notification_rolls_back_comment(client, monkeypatch):
    from app.api import task_discussion

    owner = create_user("owner@example.test")
    assignee = create_user("assignee@example.test")
    workspace, project, task = make_scope(owner, assignee)
    task.assignee_id = assignee.id
    workspace_id, project_id, task_id = workspace.id, project.id, task.id
    db.session.commit()
    login(client, owner.email)

    def fail_notification(**_kwargs):
        raise SQLAlchemyError("simulated comment notification failure")

    monkeypatch.setattr(task_discussion, "create_notification", fail_notification)
    failed = client.post(
        f"{BASE}/workspaces/{workspace_id}/projects/{project_id}/tasks/{task_id}/comments",
        json={"body": "Must roll back"},
        headers=csrf_headers(client),
    )
    assert failed.status_code == 500

    assert (
        db.session.scalar(
            select(func.count(TaskComment.id)).where(TaskComment.body == "Must roll back")
        )
        == 0
    )
    assert db.session.scalar(select(func.count(Notification.id))) == 0


def test_task_deletion_and_membership_removal_clear_notifications(client):
    owner = create_user("owner@example.test")
    member = create_user("member@example.test")
    workspace, project, task = make_scope(owner, member)
    workspace_id, project_id, task_id = workspace.id, project.id, task.id
    add_notification(member, workspace, project, task, "deleted-with-task")
    add_notification(member, workspace, project, task, "deleted-with-membership")
    db.session.commit()
    login(client, owner.email)

    deleted = client.delete(
        f"{BASE}/workspaces/{workspace_id}/projects/{project_id}/tasks/{task_id}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 200
    assert db.session.scalar(select(func.count(Notification.id))) == 0

    surviving_task = Task(project_id=project_id, title="Keep me")
    surviving_task.assignee_id = member.id
    db.session.add(surviving_task)
    db.session.flush()
    add_notification(member, workspace, project, surviving_task, "deleted-with-member")
    db.session.commit()
    removed = client.delete(
        f"{BASE}/workspaces/{workspace_id}/members/{member.id}",
        headers=csrf_headers(client),
    )
    assert removed.status_code == 200
    assert db.session.scalar(select(func.count(Notification.id))) == 0
    after_removal = client.post(
        f"{BASE}/workspaces/{workspace_id}/projects/{project_id}/tasks/{surviving_task.id}/comments",
        json={"body": "No notification for a removed member."},
        headers=csrf_headers(client),
    )
    assert after_removal.status_code == 201
    assert db.session.scalar(select(func.count(Notification.id))) == 0


def test_project_and_workspace_deletion_remove_notifications(client):
    owner = create_user("owner@example.test")
    workspace, project, task = make_scope(owner)
    workspace_id, project_id = workspace.id, project.id
    add_notification(owner, workspace, project, task, "deleted-with-project")
    db.session.commit()
    login(client, owner.email)

    deleted_project = client.delete(
        f"{BASE}/workspaces/{workspace_id}/projects/{project_id}",
        headers=csrf_headers(client),
    )
    assert deleted_project.status_code == 200
    assert db.session.scalar(select(func.count(Notification.id))) == 0

    new_project = Project(workspace=workspace, name="Retained context")
    new_task = Task(project=new_project, title="Will be deleted with workspace")
    db.session.add(new_project)
    db.session.flush()
    add_notification(owner, workspace, new_project, new_task, "deleted-with-workspace")
    db.session.commit()
    deleted_workspace = client.delete(
        f"{BASE}/workspaces/{workspace_id}",
        headers=csrf_headers(client),
    )
    assert deleted_workspace.status_code == 200
    assert db.session.scalar(select(func.count(Notification.id))) == 0
