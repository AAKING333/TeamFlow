# TeamFlow Backend

The TeamFlow backend is a Flask application built around the application
factory pattern. It provides health/readiness checks, cookie-based
authentication, and membership-scoped workspace APIs, with database migrations
and test infrastructure.

## Local setup

```powershell
cd D:\TeamFlow
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements-dev.txt
cd backend
$env:APP_CONFIG = "development"
python run.py
```

## Environment variables

Create a local `.env` file based on the template:

```powershell
Copy-Item backend\.env.example backend\.env
```

Important values:

- `APP_CONFIG`: application configuration name (`development`, `testing`, or `production`)
- `SECRET_KEY`: local secret value for development use only
- `DATABASE_URL`: PostgreSQL connection string for real integration work
- `TEST_DATABASE_URL`: safe test database URL, usually SQLite in-memory
- `LOG_LEVEL`: logging level for the app
- `FRONTEND_ORIGIN`: exact browser origin allowed to make credentialed API requests
- `INVITATION_EMAIL_PROVIDER`: `development` for the explicit local outbox (no
  email is sent), `smtp` for Gmail or any SMTP server, or `resend` (needs a
  verified sending domain)
- `INVITATION_EMAIL_FROM`: sender address; for Gmail it must be the same Gmail
  address as `SMTP_USERNAME` (or a verified "Send mail as" alias)
- `SMTP_HOST` (default `smtp.gmail.com`), `SMTP_PORT` (default `587`),
  `SMTP_SECURITY` (`starttls` or `ssl`; defaults to `starttls` for 587 and
  `ssl` for 465), `SMTP_USERNAME`, `SMTP_PASSWORD`: used only by the `smtp`
  provider
- `RESEND_API_KEY`: server-side provider key for the `resend` provider
- `INVITATION_EMAIL_TIMEOUT_SECONDS`: provider timeout from 1 through 30

`python run.py` and `flask run` read `backend\.env` automatically
(`python-dotenv` is already in `requirements.txt`). Variables already set in
your shell win over the file, so remove a stale shell value with
`Remove-Item Env:SMTP_PASSWORD`. Settings are read once at startup: restart the
backend after editing `.env`. Save the file as UTF-8. `backend\.env` is
git-ignored and must never be committed. Test runs (`APP_CONFIG=testing`) and
the browser E2E runner never read it and never use SMTP.

### Real invitation email with Gmail (SMTP)

With the default `INVITATION_EMAIL_PROVIDER=development`, **no email is sent**;
invitations only create a local link. To send real invitation emails through
your own Gmail account:

1. Turn on 2-Step Verification for the Google account.
2. Create an App Password: Google Account > Security > App passwords. Google
   shows 16 characters in groups of four; spaces are ignored by TeamFlow.
3. Put the values only in `backend\.env` (never in a tracked file, chat, or
   issue). Replace every placeholder:

   ```text
   INVITATION_EMAIL_PROVIDER=smtp
   INVITATION_EMAIL_FROM=TeamFlow <your-address@gmail.com>
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_SECURITY=starttls
   SMTP_USERNAME=your-address@gmail.com
   SMTP_PASSWORD=replace-with-a-gmail-app-password
   ```

   `INVITATION_EMAIL_FROM` must use the same Gmail address as `SMTP_USERNAME`;
   Gmail rewrites or rejects other senders.
4. Stop the backend (Ctrl+C) and start it again with `python run.py`. Startup
   fails with a message naming the bad setting (never its value) when anything
   is missing, a placeholder, or unsafe.
5. Test deliberately: in the Members panel invite an address you control. A
   success message means the email server accepted the message, not that it
   reached an inbox; check the inbox and the spam folder. Real delivery is
   unverified until you have done this with your own credentials: the automated
   tests use a fake SMTP server and never send email.

TeamFlow always verifies TLS certificates and never sends credentials over an
unencrypted connection. Gmail limits how many messages an account can send per
day, and messages from a personal address may land in spam. See
[the development guide](../docs/development-setup.md#sending-real-invitation-email-with-gmail-smtp)
for troubleshooting (535 authentication errors, missing App passwords option,
Google Workspace restrictions, and timeouts).

The default `DATABASE_URL` in `.env.example` uses the existing local SQLite
database. PostgreSQL is selected explicitly with a URL such as
`postgresql+psycopg://teamflow_user@localhost:5432/teamflow_dev`; the PostgreSQL
role/database must already exist. Never point test commands at a development
or production database.

`APP_CONFIG` selects the factory configuration when `create_app()` is called without an explicit name. Explicit factory arguments take precedence.

## Running the app

```powershell
cd backend
$env:APP_CONFIG = "development"
..\.venv\Scripts\python.exe run.py
```

You can also start the app directly:

```powershell
cd D:\TeamFlow
.\.venv\Scripts\Activate.ps1
cd backend
python run.py
```

If the virtual environment is not activated, run the project interpreter
explicitly from `D:\TeamFlow\backend`:

```powershell
..\.venv\Scripts\python.exe run.py
```

From Command Prompt, you can activate the backend-local environment and then
run the same `python run.py` command:

```bat
cd /d D:\TeamFlow\backend
.venv\Scripts\activate.bat
python run.py
```

In PowerShell, activate that backend-local environment with
`.\.venv\Scripts\Activate.ps1`. The project-root `.venv` is also supported.

Install dependencies into that same environment if imports are missing:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Health endpoints

- `GET /api/v1/health`
- `GET /api/v1/health/ready`

The liveness endpoint confirms the API is alive. The readiness endpoint checks the configured database with a minimal query and returns HTTP 503 when the database is unavailable.

## Registration endpoint

State-changing auth requests require a CSRF token from `GET /api/v1/auth/csrf` in the `X-CSRF-Token` header.

`POST /api/v1/auth/register` accepts a JSON object:

```json
{
  "name": "Ada Lovelace",
  "email": "ada@example.com",
  "password": "a-local-password"
}
```

Names are trimmed and limited to 120 characters. Emails are trimmed, normalized to case-folded form, limited to 320 characters, and checked for basic email syntax. Passwords must be 8–1024 characters. Successful registration returns HTTP 201 with the public user fields only. Invalid input returns HTTP 400, and an already registered normalized email returns HTTP 409. Passwords are stored only as Werkzeug-generated hashes.

## Session authentication

- `POST /api/v1/auth/login` starts a signed-cookie session after verifying credentials.
- `GET /api/v1/auth/me` returns the current user's safe profile or HTTP 401.
- `POST /api/v1/auth/logout` revokes the session and clears its cookie.
- `GET /api/v1/auth/csrf` provides the CSRF token needed for state-changing requests.

The session cookie is HttpOnly and SameSite=Lax; production sets Secure. Sessions expire after 30 minutes of inactivity and have a 12-hour absolute lifetime. Logout increments `users.session_version`, so replaying an older signed cookie is rejected. Read [the authentication design](../docs/authentication.md) before integrating a browser client.

## Workspaces and memberships

Workspace routes under `/api/v1/workspaces` require a signed-in user and
membership checks on every workspace-specific request. Owners and admins can
rename a workspace; only the owner can transfer ownership to an existing member
or delete the workspace. All members can read workspace details; only owners
and admins can read member lists. Mutations require CSRF tokens. See
[workspace API and authorization](../docs/workspaces.md) for endpoint,
response, and role rules. Projects are scoped to those workspace routes.
Members can list/read projects; owners/admins can create, rename, or delete
them. Every project operation checks both the requested workspace membership
and that the project belongs to that workspace.
Task assignment and task-comment notifications are available under
`/api/v1/notifications`; the supported events, ownership checks, pagination,
and retention rules are documented in
[the notification API guide](../docs/notifications.md).

## Database and migrations

The Alembic repository includes migrations for users, sessions, workspaces,
memberships, projects, tasks, comments, activity, invitations, invitation
email delivery outcomes, and notifications. The current migration head is
`f0a1b2c3d4e5`. An existing local database is never migrated automatically when
the code is updated. **After pulling changes that add migrations, run
`flask db upgrade` on your existing development database (make a backup
first).** Automated tests use fresh in-memory databases and do not exercise
your real development database, so tests can pass while the Members panel
fails with HTTP 500 (for example `no such column`) on a database that is behind.
Inspect the selected database before running `db upgrade`; migration
verification uses an isolated SQLite database.

Inspect the actual selected database revision before applying a migration.
For an existing local database, make a backup, verify that the selected URL is
the intended development database, then apply the additive migration and
confirm the result:

```powershell
cd backend
..\.venv\Scripts\python.exe -m flask --app run.py db current
..\.venv\Scripts\python.exe -m flask --app run.py db migrate -m "Describe schema change"
..\.venv\Scripts\python.exe -m flask --app run.py db upgrade
..\.venv\Scripts\python.exe -m flask --app run.py db current
..\.venv\Scripts\python.exe -m flask --app run.py db check
```

`db upgrade` changes the database selected by the active application configuration. Verify the selected local development database before running it; do not point local commands at production.

### PostgreSQL integration testing

Use an installed PostgreSQL service or an isolated PostgreSQL container. Create
a dedicated, disposable database named `teamflow_test` (or
`teamflow_test_<suffix>`) and a local role with access to it. The pytest fixture
accepts only this reserved PostgreSQL database name or in-memory SQLite, then
creates and drops the TeamFlow test tables. Never aim `TEST_DATABASE_URL` at a
development, production, or valuable database.

Set `PGPASSWORD` using your local secret manager or current shell's secure
environment configuration; do not store a real password in a tracked file.
Use a dedicated `teamflow_migration_check` database for migrations and schema
inspection, separate from `teamflow_test`, which pytest fixtures create and
drop:

```powershell
cd D:\TeamFlow\backend
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

The first `db upgrade` must start from the empty database. The downgrade and
upgrade pair verifies the transition from the previous revision and returns
the schema to head. Do not run these commands against the local development
SQLite database or any non-disposable database.

For the standard SQLite suite, explicitly select the in-memory test database:

```powershell
$env:APP_CONFIG = "testing"
$env:TEST_DATABASE_URL = "sqlite:///:memory:"
..\.venv\Scripts\python.exe -m pytest tests
```

The PostgreSQL CI job repeats the fresh upgrade, schema drift check, previous
revision upgrade, and full test suite against a disposable PostgreSQL 16
service.

## Testing

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
..\.venv\Scripts\python.exe -m pytest tests\test_health.py
..\.venv\Scripts\python.exe -m pytest --cov=app --cov-branch --cov-report=term-missing
```

## Linting

```powershell
cd backend
..\.venv\Scripts\ruff.exe check .
..\.venv\Scripts\ruff.exe format --check .
```

The `Flask-Cors` package is declared in `requirements.txt`. If
`ModuleNotFoundError: No module named 'flask_cors'` appears, the process is
using an environment that does not have the project dependencies installed.
Activate `D:\TeamFlow\.venv` or install `requirements-dev.txt` into the
interpreter used to run `run.py` (for example, activate `backend\.venv` first);
installing a package into a different Python environment will not fix that
process.

## Browser authentication smoke test

With the development backend and frontend running on their documented local
origins:

1. Open `http://localhost:5173/register`, create an account using a synthetic
   development-only email address, and submit matching passwords.
2. Sign in with that account. The browser sends the session cookie and
   anti-CSRF header; no token is stored in local storage.
3. Confirm `/app` displays the profile returned by `/api/v1/auth/me`.
4. Sign out and confirm the browser returns to `/login`. A direct visit to
   `/app` redirects to sign-in, while the backend independently rejects any
   unauthenticated `/api/v1/auth/me` request.

## Development note

PostgreSQL is the intended production database, but this environment does not guarantee a local PostgreSQL service is running. SQLite is used in tests for safe, isolated validation when PostgreSQL is unavailable.
