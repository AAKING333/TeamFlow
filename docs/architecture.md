# TeamFlow Architecture Overview

## Application factory pattern

The backend is structured around a Flask application factory in `backend/app/__init__.py`. This keeps configuration and initialization isolated from runtime startup. The factory supports development, testing, and production configuration profiles through a dedicated config module.

## Blueprint organization

The API is organized into blueprints under `backend/app/api/`. A top-level API blueprint provides the `/api` namespace, and a versioned `v1` blueprint adds `/api/v1` routes. This layout supports future expansion without mixing unrelated logic into a single file.

## Extension initialization

Shared extension instances live in `backend/app/extensions.py`:

- SQLAlchemy
- Flask-Migrate

These are initialized with `init_app(app)` so the application is configured cleanly for each runtime environment without hidden global state.

## Configuration separation

The configuration layer in `backend/app/config.py` defines environment-specific defaults and validates mandatory production checks. A local `.env` file is read with `python-dotenv`, while explicit environment variables are used for runtime selection.

This keeps secrets and environment configuration outside the source code and prevents accidental use of production defaults in local development or testing.

## Database and migration strategy

TeamFlow uses PostgreSQL as the intended production and integration database, with SQLAlchemy 2.x APIs and Flask-Migrate for schema management.

The application models are imported during application creation so Alembic
autogeneration sees their metadata. The checked-in Alembic repository includes
migrations for users, session-version revocation, workspaces, and memberships.
The current migrations add projects scoped to workspaces and tasks scoped to
projects.
Future schema changes must be generated and reviewed as migrations; production
tables are not created automatically at startup.

## Testing strategy

The backend test suite is organized under `backend/tests` and uses pytest. The test app fixture creates an isolated testing configuration and uses SQLite in-memory settings for local validation when PostgreSQL is unavailable.

Tests focus on:

- app factory behavior
- configuration correctness
- health and readiness endpoints
- safe handling of database failures
- consistent error payloads
- user registration validation and password hashing

The test fixture's `db.create_all()` and `db.drop_all()` are limited to its
isolated in-memory SQLite database or a PostgreSQL database explicitly named
`teamflow_test` / `teamflow_test_<suffix>`. The fixture rejects file-backed
SQLite and other PostgreSQL databases to avoid accidentally dropping a
developer's application tables. These test helpers are not application
startup or production migration mechanisms.

The PostgreSQL CI job starts from an empty PostgreSQL 16 service database,
applies the migration chain, checks the live schema, tests downgrade/upgrade
from the prior revision, and runs the full backend suite.

## Registration API

`POST /api/v1/auth/register` validates name, email, and password inputs, normalizes email addresses, and stores a Werkzeug password hash. Responses use HTTP 201 for creation, HTTP 400 for validation errors, and HTTP 409 for duplicate normalized email addresses. State-changing auth requests require a CSRF token.

## Browser authentication

See [authentication.md](authentication.md) for the cookie-session lifecycle, logout revocation, CSRF contract, credentialed CORS origin, expiration policy, and deployment-edge rate-limit guidance. The API uses Flask's signed cookie session plus a user session-version check; it does not issue bearer tokens or store browser credentials in local storage.

## Workspace authorization

Workspace and membership records are served through a dedicated versioned API
blueprint. A workspace has a required owner user, and each membership has a
unique `(workspace_id, user_id)` pair and a constrained owner/admin/member role.
Authorization queries first require the current user's membership; inaccessible
workspace IDs are returned as not found. Owners and admins can rename a
workspace and list members, while only its owner can transfer ownership or
delete it. Transfer updates the owner reference and the two membership roles
in one transaction. See [workspaces.md](workspaces.md) for endpoint and role
details.

## Task authorization

Tasks belong to a project and are accessed only through nested workspace and
project routes. Each operation verifies the current user's workspace
membership, confirms the project belongs to the workspace, and constrains task
queries to that project. Workspace members can create and update tasks and
assign them only to workspace members; owners/admins alone can delete tasks.
Database checks constrain status and priority, while foreign keys and
SQLAlchemy cascades clean up project tasks and null references to deleted
assignees.

Task comments are retained only while the task exists and cascade on task
deletion. Important task mutations write constrained activity records in the
same database transaction as the task change. Activity rows retain workspace
and project references, while task deletion nulls the task reference so the
delete event remains visible at project scope; deleting a project/workspace
purges its timeline. Event types and data shapes are allow-listed, and text
changes do not duplicate the text itself into history.

## Project authorization

Projects are children of one workspace and are queried using both workspace
and project IDs. Workspace members can list and read projects; owners and
admins can create, rename, and delete them. Foreign-workspace IDs return a
consistent project not-found response. Workspace deletion cascades through
projects and memberships. No project slug is used, so project names need not be
globally unique. See [workspaces.md](workspaces.md) for the broader workspace
contract.

## Frontend/backend interaction

The React + TypeScript frontend lives under `frontend/src/`, with route
components in `pages/`, shared authentication UI in `components/`, a typed
credentialed API client in `api/`, and session state in `auth/`. Vite reads the
API base from `VITE_API_BASE_URL`; the default targets
`http://localhost:5000/api/v1`.

Registration, login, logout, and workspace mutations retrieve a CSRF token
before their requests. All API calls include browser credentials so the
backend can manage its HttpOnly signed session cookie. The frontend guard is
for navigation only; the backend checks the signed cookie, database session
version, workspace membership, and role for authorization.
