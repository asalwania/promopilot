import { expect, test } from "@playwright/test";

// `make demo` with no API key replays the recorded sessions only (ADR 0073). A brief of the
// judge's own is explained as outside the demo recordings, before and after planning, and
// never shown as an error. This brief names nothing the rules can read, so the session stops
// at Clarify instead of planning in the background while the other journeys run.
const OWN_BRIEF = "Help me plan something for next month.";

test("a brief that is not recorded shows the demo's limits, not an error", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("Demo mode")).toBeVisible();
  await expect(
    page.getByText(/replaying recorded sessions, no API key/),
  ).toBeVisible();

  await page.getByLabel("Brief").fill(OWN_BRIEF);
  const before = page.getByRole("note", { name: "Not in the demo recordings" });
  await expect(before).toContainText("without the language model");
  await page.getByRole("button", { name: "Plan it" }).click();

  await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
  const after = page.getByRole("note", { name: "Not in the demo recordings" });
  await expect(after).toBeVisible({ timeout: 30_000 });
  await expect(after).toContainText("OPENAI_API_KEY");
  // No error component in the page (Next.js's route announcer, outside <main>, is an alert too).
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("Session not found")).toHaveCount(0);
});
