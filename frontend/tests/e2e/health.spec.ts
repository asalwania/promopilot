import { expect, test } from "@playwright/test";

test("home page shows the API as healthy via the same-origin proxy", async ({
  page,
  baseURL,
}) => {
  const healthResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/health",
  );

  await page.goto("/");

  const response = await healthResponse;
  expect(new URL(response.url()).origin).toBe(new URL(baseURL!).origin);
  await expect(page.getByRole("heading", { name: "PromoPilot" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText(/API healthy/);
});
