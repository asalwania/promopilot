import { defineConfig, devices } from "@playwright/test";

// The deck's screenshot set (#78): every key screen at 1920x1080 against the demo stack
// (`make demo`), replaying the recorded example briefs, so it needs no API key. Run it with
// `make screenshots` (or `pnpm screenshots`); the PNGs land in frontend/screenshots/.
export default defineConfig({
  testDir: "tests/screenshots",
  // Each journey plans on the seed-42 world: a round takes tens of seconds.
  timeout: 10 * 60_000,
  // A missing element fails in a minute, not at the end of the test's budget.
  expect: { timeout: 30_000 },
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "off",
    actionTimeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1920, height: 1080 },
        deviceScaleFactor: 1,
      },
    },
  ],
});
