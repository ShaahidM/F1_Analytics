import { defineConfig } from "@playwright/test";

// End-to-end tests against the real backend and real (cached) F1 data.
// Uses the locally installed Microsoft Edge, so no browser download is needed.
// First runs on a cold cache download telemetry from OpenF1 and can take several minutes.
export default defineConfig({
  testDir: "./e2e",
  timeout: 600_000,
  expect: { timeout: 300_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    channel: "msedge",
    headless: true,
    viewport: { width: 1680, height: 1300 },
  },
  webServer: [
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: process.platform === "win32"
        ? "..\\backend\\.venv\\Scripts\\python -m uvicorn app.main:app --port 8000"
        : "../backend/.venv/bin/python -m uvicorn app.main:app --port 8000",
      cwd: "../backend",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
