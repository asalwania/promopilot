import { expect, test } from "@playwright/test";

test("home page shows the API as healthy", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "PromoPilot" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText(/API healthy/);
});
