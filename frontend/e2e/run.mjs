import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve, sep } from "node:path";
import process from "node:process";

const frontendRoot = resolve(import.meta.dirname, "..");
const dataDirectory = mkdtempSync(join(tmpdir(), "teamflow-playwright-e2e-"));
const databasePath = join(dataDirectory, "teamflow.db");
const databaseUrl = `sqlite:///${databasePath.split(sep).join("/")}`;

function removeDataDirectory() {
  if (
    dirname(dataDirectory) === tmpdir() &&
    basename(dataDirectory).startsWith("teamflow-playwright-e2e-")
  ) {
    rmSync(dataDirectory, { recursive: true, force: true });
  }
}

async function main() {
  const playwrightCli = resolve(frontendRoot, "node_modules", "@playwright", "test", "cli.js");
  const runner = spawn(
    process.execPath,
    [playwrightCli, "test", ...process.argv.slice(2)],
    {
      cwd: frontendRoot,
      env: {
        ...process.env,
        TEAMFLOW_E2E_DATABASE_URL: databaseUrl,
      },
      stdio: "inherit",
    },
  );

  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.once(signal, () => runner.kill(signal));
  }

  return await new Promise((resolveExit, reject) => {
    runner.once("error", reject);
    runner.once("exit", (code, signal) => {
      resolveExit(code ?? (signal ? 1 : 0));
    });
  });
}

try {
  process.exitCode = await main();
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
} finally {
  removeDataDirectory();
}
