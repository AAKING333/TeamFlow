import { spawn } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve, sep } from "node:path";
import process from "node:process";
import { buildRunnerEnvironment } from "./environment.mjs";

const frontendRoot = resolve(import.meta.dirname, "..");
const dataDirectory = mkdtempSync(join(tmpdir(), "teamflow-playwright-e2e-"));
const artifactDirectory = join(dataDirectory, "artifacts");
const databasePath = join(dataDirectory, "teamflow.db");
const databaseUrl = `sqlite:///${databasePath.split(sep).join("/")}`;
mkdirSync(artifactDirectory);

const bearerPatterns = [
  /(?:\?|&|%3f|%26|&amp;|&amp%3b)token(?:=|%3d)/i,
  /(?:["']|&quot;)token(?:["']|&quot;)\s*(?::|%3a)\s*(?:["']|&quot;)/i,
];
const bearerSentinels = [
  "https://example.test/accept-invitation?token=TEAMFLOW_SENTINEL",
  "https://example.test/accept-invitation&token=TEAMFLOW_SENTINEL",
  "https://example.test/accept-invitation%3Ftoken%3DTEAMFLOW_SENTINEL",
  "https://example.test/accept-invitation%26token%3DTEAMFLOW_SENTINEL",
  "{&quot;token&quot;:&quot;TEAMFLOW_SENTINEL&quot;}",
];
if (bearerSentinels.some((sentinel) => !bearerPatterns.some((pattern) => pattern.test(sentinel)))) {
  throw new Error("The E2E bearer-artifact scanner self-check failed.");
}

// Allowlist only: mail settings and credentials (SMTP_*, INVITATION_EMAIL_FROM,
// RESEND_API_KEY) from the caller's shell never reach the Playwright runner.
function ownedRunnerEnvironment() {
  return buildRunnerEnvironment(process.env);
}

function findBearerArtifact(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const entryPath = join(directory, entry.name);
    if (entry.isDirectory()) {
      const match = findBearerArtifact(entryPath);
      if (match) return match;
      continue;
    }
    if (!entry.isFile()) continue;
    const contents = readFileSync(entryPath, "utf8");
    if (bearerPatterns.some((pattern) => pattern.test(contents))) return entryPath;
  }
  return null;
}

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
        ...ownedRunnerEnvironment(),
        TEAMFLOW_E2E_DATABASE_URL: databaseUrl,
        TEAMFLOW_E2E_ARTIFACT_DIR: artifactDirectory,
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
  const bearerArtifact = findBearerArtifact(artifactDirectory);
  if (bearerArtifact) {
    process.stderr.write(`Invitation bearer pattern found in owned E2E artifact: ${bearerArtifact}\n`);
    process.exitCode = 1;
    rmSync(artifactDirectory, { recursive: true, force: true });
  }
  removeDataDirectory();
}
