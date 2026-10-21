# Development Setup

## Prerequisites

- Python 3.11 or newer
- Git
- Node.js 20 or newer and npm for the React frontend and Playwright
- Chromium for real-browser smoke tests (`npx playwright install chromium`)
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

The `backend-ci.yml` workflow runs the SQLite backend suite, separate frontend
test/build checks, and a PostgreSQL 16 job that uses separate disposable
migration and test databases, migrates an empty database, checks the schema,
tests downgrade/re-upgrade, and runs the full backend suite. It also runs a
disposable PostgreSQL custom-archive backup and restore drill into a third
database. Browser smoke tests run in a separate job after the frontend checks,
against a freshly migrated temporary SQLite database.

## Browser origin and authentication

The local React development origin is normally `http://localhost:5173` (or
`http://127.0.0.1:5173`); the backend listens on port 5000. With the normal
Vite setup, the frontend uses the same-origin `/api/v1` path and Vite proxies
it to the local backend, preserving credentialed cookies and response status.
Configure `FRONTEND_ORIGIN` to the exact frontend origin for direct
cross-origin API requests and generated invitation URLs. The API permits
credentialed cross-origin requests only from that origin. Use `fetch(...,
{ credentials: "include" })` and send the session-bound `X-CSRF-Token` header
on state-changing authentication requests. See
[authentication.md](authentication.md) for lifecycle and security details.

## Running the backend locally

```powershell
cd D:\TeamFlow\backend
$env:APP_CONFIG = "development"
..\.venv\Scripts\python.exe run.py
```

The backend listens at `http://127.0.0.1:5000`; the normal frontend API path
is `/api/v1` through the Vite development proxy. Set an absolute
`VITE_API_BASE_URL` only for an intentional separate API host. Workspace API
behavior and role rules are described in [workspaces.md](workspaces.md).

## Browser smoke tests

Install the frontend dependencies and Chromium once:

```powershell
cd D:\TeamFlow\frontend
npm ci
npx playwright install chromium
```

The launcher automatically uses a Python environment under `backend\.venv` or
`backend\.VENV` when present. Otherwise, activate the Python environment
containing `backend\requirements-dev.txt`, then run the browser suite:

```powershell
cd D:\TeamFlow
npm --prefix frontend run e2e
```

To select a particular Python environment explicitly, set `E2E_PYTHON`:

```powershell
$env:E2E_PYTHON = "D:\TeamFlow\backend\.venv\Scripts\python.exe"
npm --prefix frontend run e2e
Remove-Item Env:E2E_PYTHON
```

The runner creates a uniquely named SQLite database and a separate uniquely
owned artifact directory under the operating system's temporary directory,
applies the migrations, checks schema drift, downgrades and re-upgrades that
isolated database, and starts Flask and Vite on loopback only. It removes only
that run's temporary directory after Playwright stops the servers. It does not
use or migrate `backend\teamflow.db`; do not change the launcher to use a
developer or production URL. The suite covers registration/login/logout,
workspace and project creation, invitation acceptance via the development-only
in-memory outbox, member role restrictions, task status/priority/assignment,
comments, notification navigation, non-member access denial, and workspace
switching. Passwords and the one-time invitation URL are generated at runtime.
The runner passes an allowlisted environment to the test processes, forces the
development outbox, disables traces/video/screenshots, and scans only its owned
artifacts for raw, percent-encoded, HTML-escaped, or JSON bearer URL forms
before cleanup.

## Running the frontend

Start a second terminal:

```powershell
cd D:\TeamFlow\frontend
npm run dev
```

Vite uses `http://localhost:5173` (or `http://127.0.0.1:5173`). Leave
`VITE_API_BASE_URL` unset for the default same-origin `/api/v1` path, which the
Vite development proxy forwards to `http://127.0.0.1:5000`. Set an absolute
`VITE_API_BASE_URL` in `.env.local` only for an intentional separate API host.
The backend's `FRONTEND_ORIGIN` remains an exact-origin rule for direct
cross-origin requests and generated invitation URLs.

## Database migrations

The Alembic repository is already initialized. Review generated migration scripts before applying them, then run them against a verified local development database:

```powershell
cd D:\TeamFlow\backend
$env:APP_CONFIG = "development"
..\.venv\Scripts\python.exe -m flask --app run.py db migrate -m "Describe schema change"
..\.venv\Scripts\python.exe -m flask --app run.py db upgrade
```

`db upgrade` applies schema changes to the database selected by `APP_CONFIG` and `DATABASE_URL`. Do not run it with production configuration unless the deployment procedure explicitly calls for it.

The current Alembic head is `f0a1b2c3d4e5`. Existing local databases are not
migrated automatically. For safe backup, effective URL inspection with
credentials hidden, revision inspection, and manual upgrade steps for an
existing SQLite database, follow [deployment.md](deployment.md#safe-local-sqlite-upgrade).
Migration verification must use an isolated test database; it must not alter
the existing local SQLite file.

Workspace invitation email configuration
---------------------------------------

Development and testing must use the explicit no-network mode:
`INVITATION_EMAIL_PROVIDER=development`. Creating an invitation stores its
hashed token and keeps the raw link only in the backend process; an authorized
workspace owner/admin can use the one-time **Get local test link** action. No
email is sent, and the local outbox is cleared when the backend restarts.
Automated tests inject/mock delivery or use this outbox and never contact
Resend or an SMTP server. The isolated browser runner removes provider and SMTP
credentials from its child environments, never reads `backend\.env`, forces
the outbox, and uses a disposable database/artifact directory.

Real email uses `INVITATION_EMAIL_PROVIDER=smtp` (Gmail or any SMTP server,
described below) or `INVITATION_EMAIL_PROVIDER=resend` (needs a verified
sending domain). Production must set one of them, a valid
`INVITATION_EMAIL_FROM` sender, the matching secret-managed credentials, and an
`INVITATION_EMAIL_TIMEOUT_SECONDS` value from 1 through 30. `FRONTEND_ORIGIN`
must be the exact HTTPS frontend origin used by the acceptance link. Startup
fails clearly for missing, placeholder, malformed, or unsupported settings;
there is no fallback to the development link. A provider or SMTP server
accepting a message means only that it accepted it for delivery, not that it
reached the inbox. Rejection is shown as a failed delivery and a timeout or
transport failure is shown as unconfirmed; use the authenticated Retry email
action, or revoke the invitation, rather than assuming success.

Sending real invitation email with Gmail (SMTP)
-----------------------------------------------

Until you set this up, **no email is sent**: the development outbox only keeps
a local link. To send real invitations from your own Gmail account:

1. Turn on 2-Step Verification (Google Account > Security > 2-Step
   Verification).
2. Create an App Password (Google Account > Security > App passwords). Google
   shows it as 16 characters in four groups; TeamFlow ignores the spaces. It is
   a secret: put it only in `backend\.env`, never in a tracked file, an issue,
   or a chat.
3. Create `backend\.env` (`Copy-Item backend\.env.example backend\.env` if you
   have not yet) and set these values, replacing every placeholder:

   ```text
   INVITATION_EMAIL_PROVIDER=smtp
   INVITATION_EMAIL_FROM=TeamFlow <your-address@gmail.com>
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_SECURITY=starttls
   SMTP_USERNAME=your-address@gmail.com
   SMTP_PASSWORD=replace-with-a-gmail-app-password
   ```

   `INVITATION_EMAIL_FROM` must be the same Gmail address as `SMTP_USERNAME`
   (or a "Send mail as" alias you verified in Gmail). Use `SMTP_PORT=465` with
   `SMTP_SECURITY=ssl` if port 587 is blocked on your network. `backend\.env`
   is git-ignored; save it as UTF-8 and check `git status` shows it as ignored.
4. Restart the backend: press Ctrl+C in its terminal and run `python run.py`
   again from `D:\TeamFlow\backend`. Settings are read only at startup. If a
   setting is missing, a placeholder, or unsafe, the backend refuses to start
   and names the setting (never its value).
5. Run an intentional end-to-end test: sign in, open the Members panel, and
   invite an address you control. TeamFlow reports that the email was handed to
   the email server. Check that mailbox, including spam, then open the link and
   accept the invitation with an account using that address. Real delivery is
   not proven until you have done this with your own credentials; the automated
   tests use a fake SMTP server and never send email.

Things to expect: Gmail limits how many messages an account may send per day
(see Google's [Gmail sending limits](https://support.google.com/mail/answer/22839)
and, for Workspace, [its limits](https://support.google.com/a/answer/166852));
messages from a personal address may be filtered to spam; and an invitation
shown as "Email provider accepted" only means the server accepted it.

Troubleshooting (the backend log shows only a category such as
`category=authentication`; never the password, address, or link):

- `535` / "Username and Password not accepted": the Members panel says email
  delivery is misconfigured. Recreate the App Password, confirm
  `SMTP_USERNAME` is the full Gmail address, and restart the backend.
- No "App passwords" option: Google hides it when 2-Step Verification is off or
  uses only security keys, for Advanced Protection accounts, and for accounts
  whose administrator disabled it ([Google's help](https://support.google.com/mail/answer/185833)).
- Google Workspace (work or school) accounts often need administrator
  permission for App passwords or SMTP access, and some require OAuth, which
  TeamFlow does not use. Use a personal Gmail account or another SMTP provider.
- Timeouts or "delivery was not confirmed": a firewall, VPN, or antivirus may
  block outbound port 587; try 465/`ssl`. Categories `timeout`, `connection`,
  `dns`, and `tls` point to the network. TLS certificates are always verified
  and cannot be disabled; an intercepting proxy or a wrong system clock fails
  the check.
- Settings seem ignored: the file must be exactly `backend\.env` (not
  `.env.txt`), and a variable already set in your PowerShell session overrides
  the file (`Remove-Item Env:SMTP_PASSWORD`).

After pulling changes that add migrations, run `flask db upgrade` (with a
backup) on your existing development database; see
[deployment.md](deployment.md#safe-local-sqlite-upgrade). Tests use fresh
in-memory databases and do not exercise your real development database, so they
can pass while the Members panel fails on a database that is behind.

A deliberate live-provider smoke test is not part of automated verification.
If one is separately authorized, use an isolated disposable database, valid
secret-managed credentials, a verified sender, a controlled recipient, and
`INVITATION_EMAIL_PROVIDER=resend` or `smtp`; verify only provider or server
acceptance, never inbox placement, and remove any resulting invitation
afterward. Do not
put credentials, raw tokens, or bearer URLs in logs, fixtures, reports, or
documentation.

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
