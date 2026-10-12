# Production deployment and release checks

## Required configuration

Deploy behind an HTTPS-terminating reverse proxy or managed platform and set:

- `APP_CONFIG=production`
- `SECRET_KEY` to a random secret of at least 32 characters from a secret
  manager. Never use the development or testing secret.
- `DATABASE_URL` to a PostgreSQL URL using the `psycopg` driver and a
  least-privilege application role.
- `FRONTEND_ORIGIN` to the exact HTTPS origin serving the React app
  (scheme and host only; no wildcard, path, credentials, query, or fragment).

Production startup rejects a missing/short secret, missing or non-PostgreSQL
database URL, non-HTTPS frontend origin, and debug mode. Session cookies are
HttpOnly, Secure, SameSite=Lax; mutations continue to require the session-bound
CSRF header. Configure TLS and trusted proxy headers at the deployment edge.
No email provider or external notification delivery is configured.

Do not start production with `python run.py` or `flask run`; these are
development servers. Install the backend dependencies and serve the WSGI app
with Waitress, behind the platform's TLS proxy:

```powershell
cd D:\TeamFlow\backend
$env:APP_CONFIG = "production"
..\.venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8080 wsgi:app
```

Bind to the interface required by the hosting platform only when network
firewalling and TLS termination are configured. The development invitation-link
route is available only when `APP_CONFIG=development`; production returns
not-found for that route.

Build the frontend in CI or at release time and deploy the generated
`frontend\dist` assets with a static web server:

```powershell
cd D:\TeamFlow\frontend
npm ci
npm run build
```

Set the frontend API URL to the HTTPS backend origin at build time using
`VITE_API_BASE_URL`, and set the backend `FRONTEND_ORIGIN` to the exact
frontend origin.

## Database backup and migration

Never point tests at production or a developer database. For a production
release, use a tested PostgreSQL backup/snapshot and maintenance/rollback
procedure appropriate to the hosting provider. The current Alembic head is
`d2c4b91e7a63`. First verify the release image's head and live database
revision; then apply the forward migration as a separately controlled release
step:

```powershell
cd D:\TeamFlow\backend
$env:APP_CONFIG = "production"
..\.venv\Scripts\python.exe -m flask --app run.py db heads
..\.venv\Scripts\python.exe -m flask --app run.py db current
..\.venv\Scripts\python.exe -m flask --app run.py db upgrade
..\.venv\Scripts\python.exe -m flask --app run.py db current
..\.venv\Scripts\python.exe -m flask --app run.py db check
```

Do not run a downgrade as a routine rollback. Downgrades that drop tables
(`users`, workspaces, projects, tasks, task comments/activity, invitations, or
notifications) permanently discard the data in those tables. For an application
rollback, prefer deploying a compatible previous application release while
keeping the additive schema, or restore a verified database backup only under
the incident plan. Review each migration's downgrade before considering it.

### Safe local SQLite upgrade

The local SQLite database is never upgraded automatically. Stop the backend,
inspect the effective URL with the password hidden, and inspect the selected
revision before making any copy or migration:

```powershell
cd D:\TeamFlow\backend
$env:APP_CONFIG = "development"
..\.venv\Scripts\python.exe -c "from app import create_app; from app.extensions import db; from sqlalchemy.engine import make_url; app=create_app(); ctx=app.app_context(); ctx.push(); url=make_url(app.config['SQLALCHEMY_DATABASE_URI']); print('URL:', url.render_as_string(hide_password=True)); print('SQLite file:', db.engine.url.database if url.get_backend_name() == 'sqlite' else 'not SQLite')"
..\.venv\Scripts\python.exe -m flask --app run.py db current
```

If the effective URL is SQLite and you intentionally choose to upgrade that
development database, stop the app and copy the exact reported database file
to a timestamped backup first:

```powershell
$dbPath = "REPLACE_WITH_THE_EXACT_REPORTED_SQLITE_FILE"
Copy-Item -LiteralPath $dbPath -Destination "$dbPath.$(Get-Date -Format yyyyMMdd-HHmmss).bak"
..\.venv\Scripts\python.exe -m flask --app run.py db upgrade
..\.venv\Scripts\python.exe -m flask --app run.py db current
..\.venv\Scripts\python.exe -m flask --app run.py db check
```

The placeholder must be replaced with the exact inspected file; do not paste
the command unchanged. This release workflow does not upgrade the existing
SQLite database automatically.

## Health and readiness

- `GET /api/v1/health` is a liveness check.
- `GET /api/v1/health/ready` checks database connectivity and returns HTTP 503
  when the database cannot be reached.

Configure deployment probes to use readiness for traffic admission and
liveness for process health. Avoid exposing internal database errors in
external diagnostics.

## CI and integration coverage

The PostgreSQL CI job uses PostgreSQL 16, waits for `pg_isready`, creates
separate disposable migration and pytest databases, migrates an empty database
to head, checks the actual migrated constraints/indexes/types, downgrades and
re-upgrades the disposable migration database, runs schema-drift checks, and
runs the complete backend suite on PostgreSQL. The SQLite suite remains
in-memory and separate. CI tears down its PostgreSQL service and explicitly
drops both disposable databases, including after failed steps.

There is no browser-based E2E runner configured. Frontend tests use Vitest and
Testing Library; backend API integration tests exercise their matching server
flows. Add a browser E2E runner in a later phase if release requirements call
for real-browser verification.
