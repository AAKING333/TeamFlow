from __future__ import annotations

import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Project, Task, TaskActivity, User, Workspace, WorkspaceMembership


def create_user(email: str) -> User:
    user = User(name=email.split("@")[0], email=email)
    user.set_password("sqlite-test-password")
    db.session.add(user)
    db.session.flush()
    return user


def create_workspace(owner: User, name: str = "Workspace") -> Workspace:
    workspace = Workspace(name=name, owner=owner)
    workspace.memberships.append(WorkspaceMembership(user=owner, role="owner"))
    db.session.add(workspace)
    db.session.flush()
    return workspace


def create_project(workspace: Workspace, name: str = "Project") -> Project:
    project = Project(workspace=workspace, name=name)
    db.session.add(project)
    db.session.flush()
    return project


def create_task(project: Project, **kwargs) -> Task:
    task = Task(project=project, title="Task", **kwargs)
    db.session.add(task)
    db.session.flush()
    return task


def test_sqlite_connections_enable_foreign_keys(app):
    db.engine.dispose()
    with db.engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1


def test_sqlite_rejects_invalid_foreign_key_references(app):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner)
    db.session.commit()

    with pytest.raises(IntegrityError):
        db.session.execute(
            insert(Project).values(workspace_id=workspace.id + 100, name="Orphan project")
        )
    db.session.rollback()

    with pytest.raises(IntegrityError):
        db.session.execute(
            insert(Task).values(
                project_id=workspace.id + 100,
                title="Orphan task",
                status="todo",
                priority="medium",
            )
        )
    db.session.rollback()


def test_sqlite_enforces_cascade_and_set_null_actions(app):
    owner = create_user("owner@example.test")
    assignee = create_user("assignee@example.test")
    workspace = create_workspace(owner)
    workspace.memberships.append(WorkspaceMembership(user=assignee, role="member"))
    first_project = create_project(workspace, "First")
    first_task = create_task(first_project, assignee=assignee)
    activity = TaskActivity(
        workspace_id=workspace.id,
        project_id=first_project.id,
        task_id=first_task.id,
        actor_id=assignee.id,
        event_type="task_created",
        data={},
    )
    second_project = create_project(workspace, "Second")
    second_task = create_task(second_project)
    db.session.add(activity)
    db.session.flush()
    first_task_id, activity_id = first_task.id, activity.id
    second_project_id, second_task_id = second_project.id, second_task.id
    first_project_id = first_project.id
    workspace_id, assignee_id = workspace.id, assignee.id
    db.session.commit()

    db.session.execute(delete(User).where(User.id == assignee_id))
    db.session.commit()
    db.session.expire_all()
    assert db.session.get(Task, first_task_id).assignee_id is None

    db.session.execute(delete(Task).where(Task.id == first_task_id))
    db.session.commit()
    db.session.expire_all()
    assert db.session.get(TaskActivity, activity_id).task_id is None

    db.session.execute(delete(Project).where(Project.id == second_project_id))
    db.session.commit()
    assert db.session.get(Task, second_task_id) is None

    db.session.execute(delete(Workspace).where(Workspace.id == workspace_id))
    db.session.commit()
    assert db.session.get(Project, first_project_id) is None


def test_sqlite_restricts_deleting_workspace_owner(app):
    owner = create_user("owner@example.test")
    workspace = create_workspace(owner)
    owner_id = owner.id
    db.session.commit()

    with pytest.raises(IntegrityError):
        db.session.execute(delete(User).where(User.id == owner_id))
    db.session.rollback()

    assert (
        db.session.scalar(select(Workspace.id).where(Workspace.id == workspace.id)) == workspace.id
    )
