from __future__ import annotations

from flask import Blueprint

from .auth import auth_bp
from .health import health_bp
from .notifications import notifications_bp
from .projects import projects_bp
from .task_discussion import discussion_bp
from .tasks import tasks_bp
from .workspace_memberships import invitation_accept_bp, workspace_memberships_bp
from .workspaces import workspaces_bp

api_bp = Blueprint("api", __name__, url_prefix="/api")
v1_bp = Blueprint("api_v1", __name__, url_prefix="/v1")
v1_bp.register_blueprint(auth_bp, url_prefix="/auth")
v1_bp.register_blueprint(health_bp, url_prefix="/health")
v1_bp.register_blueprint(workspaces_bp, url_prefix="/workspaces")
v1_bp.register_blueprint(projects_bp, url_prefix="/workspaces")
v1_bp.register_blueprint(tasks_bp, url_prefix="/workspaces")
v1_bp.register_blueprint(discussion_bp, url_prefix="/workspaces")
v1_bp.register_blueprint(workspace_memberships_bp, url_prefix="/workspaces")
v1_bp.register_blueprint(invitation_accept_bp, url_prefix="/invitations")
v1_bp.register_blueprint(notifications_bp, url_prefix="/notifications")
api_bp.register_blueprint(v1_bp)


def register_blueprints(app) -> None:
    app.register_blueprint(api_bp)
