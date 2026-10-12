# Development Setup

## Prerequisites

- Python 3.11 or newer
- Git
- Node.js and npm for the React frontend
- PostgreSQL for real integration testing and production-like local configuration

## Windows PowerShell setup

```powershell
cd D:\TeamFlow
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements-dev.txt
npm --prefix frontend install
Copy-Item backend\.env.example backend\.env
Copy-Item backend\.flaskenv.example backend\.flaskenv
```

Then update the copied environment files for your local database and secret values.

## macOS/Linux setup

```bash
cd TeamFlow
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt
npm --prefix frontend install
cp backend/.env.example backend/.env
cp backend/.flaskenv.example backend/.flaskenv
```

## PostgreSQL configuration

SQLite remains the default development database. To run PostgreSQL
integration tests, install/start a local PostgreSQL service (or an isolated
PostgreSQL container), then create separate disposable `teamflow_test` and
`teamflow_migration_check` databases and a role that can connect to them. For
example, from `psql` as a local database administrator:

```sql
CREATE ROLE teamflow_test LOGIN;
\password teamflow_test
CREATE DATABASE teamflow_test OWNER teamflow_test;
CREATE DATABASE teamflow_migration_check OWNER teamflow_test;
```

`\password` prompts for a local test-only password without placing it in shell
history. Configure `PGPASSWORD` through a local secret mechanism, or use your
PostgreSQL installation's configured local authentication. Do not place real
credentials in tracked files.

For a Docker-only disposable PostgreSQL 16 instance, bind it to loopback and
use trust authentication only for this local test container:

```powershell
docker run --rm --name teamflow-postgres-test `
  --publish 127.0.0.1:5432:5432 `
  --env POSTGRES_DB=teamflow_test `
  --env POSTGRES_USER=teamflow_test `
  --env POSTGRES_HOST_AUTH_METHOD=trust `
  --detach postgres:16
```

After verification, stop the disposable instance with
`docker stop teamflow-postgres-test`. Do not use trust authentication for a
shared or network-accessible PostgreSQL service.
Create the separate migration-check database in the disposable instance with
`createdb --host=localhost --username=teamflow_test teamflow_migration_check`.

From `D:\TeamFlow\backend`, point migrations and tests only at the disposable
database:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://teamflow_test@localhost:5432/teamflow_migration_check"
$env:TEST_DATABASE_URL = "postgresql+psycopg://teamflow_test@localhost:5432/teamflow_test"
$env:MIGRATION_DATABASE_URL = $env:DATABASE_URL
$env:APP_CONFIG = "development"
..\.venv\Scripts\python.exe -m flask --app run.py db upgrade
..\.venv\Scripts\python.exe -m flask --app run.py db check
..\.venv\Scripts\python.exe -m flask --app run.py db current
..\.venv\Scripts\python.exe -m flask --app run.py db downgrade 207ee96fe320
..\.venv\Scripts\python.exe -m flask --app run.py db upgrade
..\.venv\Scripts\python.exe -m flask --app run.py db check
$env:APP_CONFIG = "testing"
..\.venv\Scripts\python.exe -m pytest tests
```

The test fixture only allows in-memory SQLite or a PostgreSQL database named
`teamflow_test` / `teamflow_test_<suffix>` because it creates and drops the
application's test tables. The database must be disposable. Never point test
configuration at development or production data.

For the SQLite suite:

```powershell
$env:APP_CONFIG = "testing"
$env:TEST_DATABASE_URL = "sqlite:///:memory:"
..\.venv\Scripts\python.exe -m pytest tests
```

The `backend-ci.yml` workflow runs the SQLite suite and a separate PostgreSQL
16 job that uses separate disposable migration and test databases, migrates an
empty database, checks the schema, tests downgrade/re-upgrade, and runs the
full backend suite.

## Browser origin and authentication

The local React development origin is `http://localhost:5173`; the API is
`http://localhost:5000`. Configure `FRONTEND_ORIGIN` to the exact frontend
origin. The API permits credentialed requests only from that origin. Use
`fetch(..., { credentials: "include" })` and send the session-bound
`X-CSRF-Token` header on state-changing authentication requests. See
[authentication.md](authentication.md) for lifecycle and security details.

## Running the backend locally

```powershell
cd D:\TeamFlow\backend
$env:APP_CONFIG = "development"
..\.venv\Scripts\python.exe run.py
```

The local API base URL is `http://localhost:5000/api/v1`.
Workspace API behavior and role rules are described in
[workspaces.md](workspaces.md).

## Running the frontend

Start a second terminal:

```powershell
cd D:\TeamFlow\frontend
npm run dev
```

Vite uses `http://localhost:5173`; the default frontend API URL is
`http://localhost:5000/api/v1`. Copy `.env.example` to `.env.local` only if
overriding that URL. The backend's `FRONTEND_ORIGIN` must exactly match the
browser origin.

## Database migrations

The Alembic repository is already initialized. Review generated migration scripts before applying them, then run them against a verified local development database:

```powershell
cd D:\TeamFlow\backend
$env:APP_CONFIG = "development"
..\.venv\Scripts\python.exe -m flask --app run.py db migrate -m "Describe schema change"
..\.venv\Scripts\python.exe -m flask --app run.py db upgrade
```

`db upgrade` applies schema changes to the database selected by `APP_CONFIG` and `DATABASE_URL`. Do not run it with production configuration unless the deployment procedure explicitly calls for it.

The current Alembic head is `d2c4b91e7a63`. Existing local databases are not
migrated automatically. For safe backup, effective URL inspection with
credentials hidden, revision inspection, and manual upgrade steps for an
existing SQLite database, follow [deployment.md](deployment.md#safe-local-sqlite-upgrade).
Migration verification must use an isolated test database; it must not alter
the existing local SQLite file.

No email provider is configured, so invitations do not send email. For local
testing, create an invitation in the app and use its one-time **Get local test
link** action while the backend is running in development mode. The link is
held in process memory and is not included in ordinary API responses or logs.
The local outbox is cleared when the backend restarts.

## Running tests

```powershell
cd D:\TeamFlow\backend
..\.venv\Scripts\python.exe -m pytest
..\.venv\Scripts\python.exe -m pytest tests\test_health.py
..\.venv\Scripts\python.exe -m pytest --cov=app --cov-branch --cov-report=term-missing
```

## Linting

```powershell
cd D:\TeamFlow\backend
..\.venv\Scripts\ruff.exe check .
..\.venv\Scripts\ruff.exe format --check .
```

## Local limitations

- PostgreSQL may not be installed or running in a local environment; CI uses a
  disposable PostgreSQL 16 service for repeatable integration verification.
- SQLite is used in tests and development-safe verification when a real PostgreSQL database is not available.
- Do not use production credentials or secrets in local configuration files.
