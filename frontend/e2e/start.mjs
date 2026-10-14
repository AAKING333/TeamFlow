import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import process from "node:process";

const frontendRoot = resolve(import.meta.dirname, "..");
const backendRoot = resolve(frontendRoot, "..", "backend");
const databaseUrl = process.env.TEAMFLOW_E2E_DATABASE_URL;
const virtualEnvironmentPythonPaths = process.platform === "win32"
  ? [".venv", ".VENV"].map((name) => resolve(backendRoot, name, "Scripts", "python.exe"))
  : [".venv", ".VENV"].map((name) => resolve(backendRoot, name, "bin", "python"));
const backendPython = virtualEnvironmentPythonPaths.find(existsSync);
const python = process.env.E2E_PYTHON || process.env.PYTHON || backendPython || (
  process.platform === "win32" ? "python" : "python3"
);

if (!databaseUrl?.startsWith("sqlite:///")) {
  throw new Error("The browser E2E server requires its generated SQLite database URL.");
}

const environment = {
  ...process.env,
  APP_CONFIG: "development",
  DATABASE_URL: databaseUrl,
  FRONTEND_ORIGIN: "http://127.0.0.1:5173",
  VITE_API_BASE_URL: "http://127.0.0.1:5000/api/v1",
};

for (const migrationCommand of [
  ["upgrade"],
  ["check"],
  ["downgrade", "207ee96fe320"],
  ["upgrade"],
  ["check"],
]) {
  const migration = spawnSync(
    python,
    ["-m", "flask", "--app", "run.py", "db", ...migrationCommand],
    { cwd: backendRoot, env: environment, stdio: "inherit" },
  );
  if (migration.error) throw migration.error;
  if (migration.status !== 0) {
    throw new Error(`The isolated E2E database migration command failed: ${migrationCommand.join(" ")}`);
  }
}

const children = [];
let stopping = false;

function stopChildren() {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) child.kill();
  }
}

process.once("SIGINT", stopChildren);
process.once("SIGTERM", stopChildren);

const backend = spawn(
  python,
  [
    "-m",
    "flask",
    "--app",
    "run.py",
    "run",
    "--host=127.0.0.1",
    "--port=5000",
    "--no-debugger",
    "--no-reload",
  ],
  {
    cwd: backendRoot,
    env: environment,
    stdio: "inherit",
  },
);
children.push(backend);

const vite = spawn(
  process.execPath,
  ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
  {
    cwd: frontendRoot,
    env: environment,
    stdio: "inherit",
  },
);
children.push(vite);

for (const child of children) {
  child.once("error", (error) => {
    process.stderr.write(`Could not start an E2E server: ${error.message}\n`);
    process.exitCode = 1;
    stopChildren();
  });
  child.once("exit", (code) => {
    if (!stopping) {
      process.stderr.write(`An E2E server exited unexpectedly (${code ?? "signal"}).\n`);
      process.exitCode = code || 1;
      stopChildren();
    }
  });
}
