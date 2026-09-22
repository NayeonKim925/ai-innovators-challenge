import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

const frontendDir = process.cwd();
const repoRoot = resolve(frontendDir, "..");
const backendPort = Number(process.env.BACKEND_TEST_PORT || 4188);
const frontendPort = Number(process.env.UI_TEST_PORT || 4187);
const e2eActorId = process.env.E2E_ACTOR_ID || "e2e-shift-a";
const e2eActorRole = process.env.E2E_ACTOR_ROLE || "operator";
const reuseExistingServer = process.env.REUSE_E2E_SERVER === "true";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: process.env.UI_TEST_URL || `http://127.0.0.1:${frontendPort}`,
    headless: true,
    extraHTTPHeaders: {
      "X-Actor-Id": e2eActorId,
      "X-Actor-Role": e2eActorRole,
    },
    launchOptions: process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : {},
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: "list",
  webServer: [
    {
      command: [
        "PYTHONPATH=backend",
        "RUNTIME_DATA_DIR=data/runtime",
        "DEPLOYMENT_ENV=production",
        "API_AUTH_TOKEN=e2e-token",
        "ACTOR_CONTEXT_REQUIRED=true",
        ".venv/bin/python -m uvicorn app.main:app --app-dir backend",
        `--host 127.0.0.1 --port ${backendPort}`,
      ].join(" "),
      cwd: repoRoot,
      url: `http://127.0.0.1:${backendPort}/api/health`,
      timeout: 120000,
      reuseExistingServer,
    },
    {
      command: [
        "npm run build",
        "&&",
        `PORT=${frontendPort}`,
        `BACKEND_URL=http://127.0.0.1:${backendPort}`,
        "BACKEND_API_TOKEN=e2e-token",
        "node server.mjs",
      ].join(" "),
      cwd: frontendDir,
      url: `http://127.0.0.1:${frontendPort}/healthz`,
      timeout: 120000,
      reuseExistingServer,
    },
  ],
});
