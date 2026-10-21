# TeamFlow

TeamFlow is a full-stack team collaboration and project management platform intended to support professional portfolio work, learning, and internship-ready engineering practice.

## Current implementation status

The backend foundation, cookie-session authentication, workspaces, memberships,
and workspace-scoped projects are implemented:

- a Flask application factory
- environment-based configuration
- SQLAlchemy and Flask-Migrate initialization
- health/readiness endpoints
- a SQLAlchemy User model with normalized unique email and Werkzeug password hashing
- validated user registration at `POST /api/v1/auth/register`
- cookie-based login, current-user, and logout endpoints with CSRF checks
- an Alembic migration history for users, workspaces, memberships, and projects
- workspace and membership models with role constraints and authorization
- workspace create/list/read/update/member-list/ownership-transfer/delete APIs
- workspace-scoped project creation, listing, retrieval, update, and deletion
- pytest infrastructure
- Ruff setup
- GitHub Actions CI
- project documentation

The React + TypeScript frontend provides registration, login, a protected
account shell, logout, and workspace/project loading, creation, and selection
through typed API clients. Authentication uses signed-cookie sessions and does
not issue bearer tokens. Workspace owners/admins can create invitations, which
use the configured invitation email provider in production and the explicit
one-time development outbox locally. See [workspace API and authorization](docs/workspaces.md).

## Planned product capabilities

- task management
- collaboration and document workflows
- activity history and comments
- analytics and operational reporting

## Technology stack

- Python 3.11+
- Flask
- Flask-SQLAlchemy
- SQLAlchemy 2.x
- Flask-Migrate
- PostgreSQL for integration and production use
- psycopg 3
- pytest and pytest-cov
- Ruff
- GitHub Actions

## Repository structure

```text
TeamFlow/
├── backend/
├── frontend/
├── docs/
├── .github/
├── .editorconfig
├── .gitattributes
├── .gitignore
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── ...
```

## Development prerequisites

- Python 3.11 or newer
- Git
- Node.js and npm for frontend development
- PostgreSQL 14+ recommended for integration testing and local development

## Backend setup

### Windows PowerShell

```powershell
cd D:\TeamFlow
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements-dev.txt
```

### macOS/Linux

```bash
cd TeamFlow
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt
```

## Environment configuration

Copy the backend environment templates and adapt them for local use:

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item backend\.flaskenv.example backend\.flaskenv
```

Example values are placeholders only. Do not commit real secrets;
`backend\.env` is git-ignored.

### Sending real invitation emails (Gmail)

By default no email is sent: workspace invitations use a local development
outbox. To send real invitations from a Gmail account, turn on 2-Step
Verification, create an App Password (Google Account > Security > App
passwords), and set the following in `backend\.env` (placeholders shown), using
the same Gmail address for `INVITATION_EMAIL_FROM` and `SMTP_USERNAME`:

```text
INVITATION_EMAIL_PROVIDER=smtp
INVITATION_EMAIL_FROM=TeamFlow <your-address@gmail.com>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-address@gmail.com
SMTP_PASSWORD=replace-with-a-gmail-app-password
```

Then restart the backend and invite an address you control to test it. Gmail
limits daily sends and messages may land in spam; "accepted" means the email
server took the message, not that it reached an inbox. Real delivery is
unverified until you test it with your own credentials (automated tests use a
fake SMTP server). See
[the Gmail setup and troubleshooting guide](docs/development-setup.md#sending-real-invitation-email-with-gmail-smtp).

## Database setup

TeamFlow expects PostgreSQL as the intended production database. Configure `DATABASE_URL` for a local or hosted PostgreSQL instance.

Example:

```text
DATABASE_URL=postgresql+psycopg://teamflow_user@localhost:5432/teamflow_dev
```

Testing uses a safe isolated configuration by default and can fall back to an in-memory SQLite database in local tests when PostgreSQL is unavailable.

## Migration commands

```powershell
cd D:\TeamFlow\backend
$env:APP_CONFIG = "development"
flask --app run.py db migrate -m "Describe schema change"
flask --app run.py db upgrade
```

Review migration files before applying them. `db upgrade` acts on the database selected by the current configuration; verify that configuration points to a local development database, not production.
For safe backup and revision checks before manually upgrading a valued SQLite
database, see [the deployment and migration guide](docs/deployment.md).

To inspect migration status:

```powershell
cd D:\TeamFlow\backend
flask --app run.py db current
flask --app run.py db history
```

## Running the backend

```powershell
cd D:\TeamFlow
.\.venv\Scripts\Activate.ps1
cd backend
$env:APP_CONFIG = "development"
python run.py
```

If the environment is not activated, run
`..\.venv\Scripts\python.exe run.py` from `D:\TeamFlow\backend`.

## Running the frontend

```powershell
cd D:\TeamFlow\frontend
npm install
npm run dev
```

See [frontend/README.md](frontend/README.md) for environment configuration,
browser auth behavior, and frontend checks.

## Running tests

```powershell
cd D:\TeamFlow\backend
..\.venv\Scripts\python.exe -m pytest
..\.venv\Scripts\python.exe -m pytest tests\test_health.py
..\.venv\Scripts\python.exe -m pytest --cov=app --cov-branch --cov-report=term-missing
```

## Lint and formatting

```powershell
cd D:\TeamFlow\backend
..\.venv\Scripts\ruff.exe check .
..\.venv\Scripts\ruff.exe format --check .
```

## API health endpoints

```http
GET /api/v1/health
GET /api/v1/health/ready
```

## Registration endpoint

State-changing authentication requests require `X-CSRF-Token`, fetched from `GET /api/v1/auth/csrf`.

`POST /api/v1/auth/register` accepts `name`, `email`, and `password` in a JSON object. It returns HTTP 201 for a new account, HTTP 400 for invalid fields, and HTTP 409 for a duplicate normalized email. Passwords are stored only as secure Werkzeug hashes.

Example success response:

```json
{
  "status": "created",
  "user": {
    "id": 1,
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "created_at": "2026-10-11T08:00:00+00:00"
  }
}
```

## Session authentication

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/csrf`

The browser session uses an HttpOnly, SameSite=Lax signed cookie, Secure in
production, with 30-minute idle and 12-hour absolute expiry. Logout increments
the user session version so old signed cookies no longer authorize requests.
Configure the exact frontend origin with `FRONTEND_ORIGIN` and use browser
requests with credentials included. See [docs/authentication.md](docs/authentication.md)
for the full flow, CSRF contract, and deployment rate-limiting strategy.

## Current limitations

- Workspaces and projects are not implemented yet.
- PostgreSQL integration is configured in CI using a disposable PostgreSQL 16 service; no local PostgreSQL service is available in every development environment.
- The latest migration head is `f0a1b2c3d4e5`. Existing local databases are never migrated automatically: after pulling changes that add migrations, back up your development database and run `flask --app run.py db upgrade` from `backend` (tests use fresh in-memory databases and do not exercise your real one). PostgreSQL remains unverified.
- The database readiness check is implemented and tested with a safe simulated failure path.
- Task assignment and comment notifications are documented in [the notification guide](docs/notifications.md); they remain in-app only. Workspace invitations have a separate, configured email delivery path documented in [the workspace guide](docs/workspaces.md).

## Security notes

- No hardcoded production secrets are included.
- Application startup blocks unsafe production configuration.
- Debug mode remains disabled in production.
- Sensitive values are not exposed through API error responses or logs.

## Contribution workflow

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution, review, and branch conventions.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
