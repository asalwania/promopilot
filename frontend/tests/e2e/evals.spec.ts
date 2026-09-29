import { expect, test } from "@playwright/test";

// The composed stack mounts no eval report (ADR 0069 D7), so `/evals` shows its
// empty state there (ADR 0072). The dashboard itself is proven by Vitest.
test("the evals page says to run make eval when there is no report", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Evals" })
    .click();

  await expect(page).toHaveURL(/\/evals$/);
  await expect(page.getByRole("heading", { name: "Evals" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("No eval report yet");
  await expect(
    page.getByText("No eval report yet: run `make eval`."),
  ).toBeVisible();
  await expect(page.getByText(/make eval SMOKE=1/)).toBeVisible();
});
