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

test("a typed brief becomes a plan table with no API key", async ({ page }) => {
  await page.goto("/");
  // Health is fetched in the browser, so seeing it means the page has hydrated
  // and the composer's handlers are attached.
  await expect(page.getByRole("status")).toHaveText(/API healthy/);

  await page.getByLabel("Brief").fill(brief);
  await page.getByRole("button", { name: "Plan it" }).click();

  await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
  const plan = page.getByRole("table", { name: "Plan lines" });
  await expect(plan).toBeVisible();
  await expect(plan.getByRole("row").nth(1)).toBeVisible();
});
