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

Never point tests or the backup/restore drill at production or a developer
database. Keep provider-managed point-in-time recovery enabled where available;
also take logical backups on a schedule appropriate to the recovery-point
objective. A `pg_dump` custom archive is not encrypted by itself. Use TLS for
the database connection, encrypt the archive with the organization's approved
KMS/backup service before upload, restrict read/write access to the backup
identity and recovery operators, and enforce documented retention and deletion
periods. Never store archives, database credentials, or unredacted connection
URLs in the repository, build logs, or public artifacts.

Configure libpq access through a protected service definition and a
secret-managed password file (for example, a `PGSERVICEFILE` and
`PGPASSFILE` readable only by the backup account); do not put passwords in
command-line arguments. Set a restrictive umask and write the archive to a
private directory. Example Bash commands, with the service and paths supplied
by the deployment secret manager:

```bash
umask 077
export PGSERVICE=teamflow-production-backup
backup_file="/secure-temporary/teamflow-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --no-owner --no-privileges --file="$backup_file"
pg_restore --list "$backup_file" >/dev/null
sha256sum "$backup_file"
```

Encrypt the verified archive before transferring it to access-controlled
backup storage; the example deliberately does not specify a storage vendor or
credentials. Record the checksum, backup time, application release and schema
revision in the restricted recovery inventory. A successful `pg_restore
--list` validates archive readability, not that a recovery works; periodically
restore into a separate, empty, disposable PostgreSQL database and validate
the schema and representative application relationships. Do not use a
production database as the restore target.

For a recovery drill, provision a new empty database with a restricted restore
role, configure a separate libpq service name/secret for it, and restore
without cleaning or dropping objects in an existing database:

```bash
export PGSERVICE=teamflow-disposable-restore
pg_restore --exit-on-error --no-owner --no-privileges \
  --dbname="service=teamflow-disposable-restore" "$backup_file"
```

After restore, compare `alembic_version` with the release's migration head;
run `flask db check` against the restored database using a non-production
verification environment; and check representative user, membership,
workspace, project, task, comment/activity, and notification relationships.
Validate application readiness and a read-only workflow in an isolated
environment. A database archive does not include PostgreSQL cluster roles or
their passwords; recover those separately from the secret manager/provider
procedure. The deployment provider is not specified here, so its snapshot,
encryption, retention, and point-in-time recovery setup remain operator tasks.

CI includes a disposable PostgreSQL backup/restore drill. It seeds only
synthetic records in the dedicated `teamflow_migration_check` database,
creates a mode-restricted custom archive in the runner's temporary directory,
restores into a separate empty `teamflow_backup_restore_check` database, and
checks the current Alembic head plus linked membership, project, task,
comment, activity, and notification records and UTC timestamps. It removes
the archive and drops only those disposable CI databases. A green CI drill is
evidence for this synthetic PostgreSQL restore path, not proof of a live
provider's backup policies or a production disaster-recovery process.

The current Alembic head is `d2c4b91e7a63`. First verify the release image's
head and live database revision; then apply the forward migration as a
separately controlled release step:

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
the incident plan and only to a separate recovery target before any controlled
cutover. If a migration or release fails, stop the rollout, retain the failed
release and logs, inspect the database revision and migration's transactional
behavior, and rehearse a forward fix or restore using a separate database.
Never blindly downgrade, drop objects, or restore over the production database.
Review each migration's downgrade before considering it.

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
drops the migration, test, and restore databases, including after failed steps.

Frontend tests/build and Playwright/Chromium browser E2E run in separate CI
jobs, with browser E2E depending on the frontend checks. E2E uses a fresh
temporary SQLite database; its invitation journey uses only the development
in-memory invitation outbox. Playwright traces and video are disabled to avoid
retaining one-time invitation URLs. This verifies browser journeys against the
local Flask/Vite processes, not browser behavior against a deployed origin.
PostgreSQL backend and restore checks run in a separate PostgreSQL CI job. No
email provider or external notification delivery is configured.
