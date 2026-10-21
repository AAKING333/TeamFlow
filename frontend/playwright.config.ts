import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: [["list"], ["html", {
    outputFolder: process.env.TEAMFLOW_E2E_ARTIFACT_DIR
      ? `${process.env.TEAMFLOW_E2E_ARTIFACT_DIR}/playwright-report`
      : "playwright-report",
    open: "never",
  }]],
  outputDir: process.env.TEAMFLOW_E2E_ARTIFACT_DIR
    ? `${process.env.TEAMFLOW_E2E_ARTIFACT_DIR}/test-results`
    : "test-results",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "node e2e/start.mjs",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
