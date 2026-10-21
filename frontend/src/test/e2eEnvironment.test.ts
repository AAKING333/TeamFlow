import { describe, expect, it } from "vitest";

import runSource from "../../e2e/run.mjs?raw";
import startSource from "../../e2e/start.mjs?raw";
import {
  MAIL_ENVIRONMENT_NAMES,
  buildBackendServerEnvironment,
  buildFrontendServerEnvironment,
  buildRunnerEnvironment,
} from "../../e2e/environment.mjs";

const leakedShell = {
  PATH: "C:\\tools",
  SystemRoot: "C:\\Windows",
  INVITATION_EMAIL_PROVIDER: "smtp",
  INVITATION_EMAIL_FROM: "Real <real.person@gmail.com>",
  RESEND_API_KEY: "re_real_key_value",
  SMTP_HOST: "smtp.gmail.com",
  SMTP_PORT: "587",
  SMTP_SECURITY: "starttls",
  SMTP_USERNAME: "real.person@gmail.com",
  SMTP_PASSWORD: "abcd efgh ijkl mnop",
  DATABASE_URL: "postgresql+psycopg://user@localhost/teamflow_dev",
  FLASK_SKIP_DOTENV: "0",
};

function expectNoMailSettings(environment: Record<string, string>) {
  for (const name of MAIL_ENVIRONMENT_NAMES) {
    expect(environment[name] ?? "").toBe("");
  }
  expect(JSON.stringify(environment)).not.toContain("real.person");
  expect(JSON.stringify(environment)).not.toContain("abcd");
  expect(JSON.stringify(environment)).not.toContain("re_real_key_value");
}

describe("isolated E2E environment", () => {
  it("never passes mail settings or credentials to the Playwright runner", () => {
    const environment = buildRunnerEnvironment(leakedShell);

    expect(environment.PATH).toBe("C:\\tools");
    expect(environment).not.toHaveProperty("INVITATION_EMAIL_PROVIDER");
    expect(environment).not.toHaveProperty("DATABASE_URL");
    expectNoMailSettings(environment);
  });

  it("never passes mail settings or credentials to the frontend server", () => {
    const environment = buildFrontendServerEnvironment(leakedShell);

    expect(environment.PATH).toBe("C:\\tools");
    expectNoMailSettings(environment);
  });

  it("forces the local outbox, skips backend/.env and blanks every mail variable", () => {
    const environment = buildBackendServerEnvironment(
      leakedShell,
      "sqlite:///C:/temp/teamflow.db",
    );

    expect(environment.APP_CONFIG).toBe("development");
    expect(environment.INVITATION_EMAIL_PROVIDER).toBe("development");
    expect(environment.DATABASE_URL).toBe("sqlite:///C:/temp/teamflow.db");
    expect(environment.FLASK_SKIP_DOTENV).toBe("1");
    expectNoMailSettings(environment);
    for (const name of MAIL_ENVIRONMENT_NAMES) {
      expect(environment).toHaveProperty(name, "");
    }
  });

  it("covers every SMTP and provider variable the backend reads", () => {
    expect([...MAIL_ENVIRONMENT_NAMES].sort()).toEqual(
      [
        "INVITATION_EMAIL_FROM",
        "RESEND_API_KEY",
        "SMTP_HOST",
        "SMTP_PASSWORD",
        "SMTP_PORT",
        "SMTP_SECURITY",
        "SMTP_USERNAME",
      ].sort(),
    );
  });

  it("builds every spawned environment through the allowlist helpers", () => {
    for (const source of [startSource, runSource]) {
      expect(source).toContain('from "./environment.mjs"');
      expect(source).not.toMatch(/\.\.\.\s*process\.env/);
    }
    expect(startSource).toContain("buildBackendServerEnvironment(process.env");
    expect(startSource).toContain("buildFrontendServerEnvironment(process.env");
    expect(runSource).toContain("buildRunnerEnvironment(process.env)");
  });
});
