// Pure environment builders for the isolated browser E2E run. They take the source
// environment as an argument so a unit test can prove that no mail setting or
// credential from a developer's shell can reach the E2E processes.

// Only these names are ever copied from the caller's environment.
export const RUNNER_ENVIRONMENT_ALLOWLIST = [
  "PATH",
  "SystemRoot",
  "WINDIR",
  "TEMP",
  "TMP",
  "CI",
  "E2E_PYTHON",
  "PYTHON",
  "PLAYWRIGHT_BROWSERS_PATH",
];

export const SERVER_ENVIRONMENT_ALLOWLIST = [
  "PATH",
  "SystemRoot",
  "WINDIR",
  "TEMP",
  "TMP",
  "CI",
  "PLAYWRIGHT_BROWSERS_PATH",
];

// Mail settings that must never be non-empty in an E2E process.
export const MAIL_ENVIRONMENT_NAMES = [
  "INVITATION_EMAIL_FROM",
  "RESEND_API_KEY",
  "SMTP_HOST",
  "SMTP_PORT",
  "SMTP_SECURITY",
  "SMTP_USERNAME",
  "SMTP_PASSWORD",
];

export function pickEnvironment(source, names) {
  return Object.fromEntries(
    names.filter((name) => source[name] !== undefined).map((name) => [name, source[name]]),
  );
}

export function buildRunnerEnvironment(source) {
  return pickEnvironment(source, RUNNER_ENVIRONMENT_ALLOWLIST);
}

export function buildFrontendServerEnvironment(source) {
  return {
    ...pickEnvironment(source, SERVER_ENVIRONMENT_ALLOWLIST),
    VITE_API_BASE_URL: "http://127.0.0.1:5000/api/v1",
  };
}

export function buildBackendServerEnvironment(source, databaseUrl) {
  return {
    ...pickEnvironment(source, SERVER_ENVIRONMENT_ALLOWLIST),
    APP_CONFIG: "development",
    DATABASE_URL: databaseUrl,
    FRONTEND_ORIGIN: "http://127.0.0.1:5173",
    // The explicit in-memory outbox: the E2E backend can never send email.
    INVITATION_EMAIL_PROVIDER: "development",
    // Never read backend/.env (python-dotenv and the Flask CLI both honor this) and
    // pre-set every mail variable to empty so nothing can be loaded into it either.
    FLASK_SKIP_DOTENV: "1",
    ...Object.fromEntries(MAIL_ENVIRONMENT_NAMES.map((name) => [name, ""])),
    VITE_API_BASE_URL: "http://127.0.0.1:5000/api/v1",
  };
}
