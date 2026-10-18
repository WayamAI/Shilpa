import { defineConfig } from "@playwright/test";

/**
 * End-to-end tests against the running local stack:
 *   uv run python -m shilpa.dev --no-studio   (API :8000, coordinator, CAD workers)
 *   npm run dev                               (this app on :3100)
 * Uses the installed Chrome, so no browser download is needed.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.SHILPA_WEB_URL ?? "http://localhost:3100",
    channel: "chrome",
    viewport: { width: 1600, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
