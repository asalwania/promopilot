import { expect, test } from "@playwright/test";

// The api image bakes in the recorded full eval run, so `/evals` is never empty on the
// composed stack (ADR 0073). The dashboard's details are proven by Vitest (ADR 0072).
test("the evals page shows the recorded full eval run", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Evals" })
    .click();

  await expect(page).toHaveURL(/\/evals$/);
  await expect(page.getByRole("heading", { name: "Evals" })).toBeVisible();
  await expect(page.getByLabel("Report provenance")).toContainText(
    "seed-42 world",
  );
  const scenarios = page.getByRole("table", { name: "Scenarios" });
  await expect(scenarios).toBeVisible();
  await expect(scenarios.getByRole("row").nth(1)).toBeVisible();
  await expect(page.getByText("No eval report yet")).toHaveCount(0);
});
