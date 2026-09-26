import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

// The briefs `make record-cassettes` recorded: the composed api replays their LLM calls,
// so this journey needs no API key (ADR 0019).
const [brief] = JSON.parse(
  readFileSync(
    join(__dirname, "../../../backend/cassettes/briefs.json"),
    "utf-8",
  ),
) as string[];

// Planning generates every promo option and runs the optimiser (ADR 0038): on the
// seed-42 demo brief that takes tens of seconds on a CI runner.
const PLANNING_MS = 120_000;

test("a typed brief becomes a plan table with no API key", async ({ page }) => {
  test.setTimeout(PLANNING_MS + 30_000);
  await page.goto("/");
  // Health is fetched in the browser, so seeing it means the page has hydrated
  // and the composer's handlers are attached.
  await expect(page.getByRole("status")).toHaveText(/API healthy/);

  await page.getByLabel("Brief").fill(brief);
  await page.getByRole("button", { name: "Plan it" }).click();

  await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
  const plan = page.getByRole("table", { name: "Plan lines" });
  await expect(plan).toBeVisible({ timeout: PLANNING_MS });
  await expect(plan.getByRole("row").nth(1)).toBeVisible();
});
