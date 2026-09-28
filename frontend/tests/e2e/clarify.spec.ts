import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

type SessionScript = {
  name: string;
  brief: string;
  steps?: Array<{ answers?: Record<string, string> }>;
};

// The recorded `clarify` session: the e2e brief without its budget. The Context agent
// asks for one, and the recorded answer resumes planning (ADR 0048, ADR 0054).
const scripts = JSON.parse(
  readFileSync(
    join(__dirname, "../../../backend/cassettes/sessions.json"),
    "utf-8",
  ),
) as SessionScript[];
const clarify = scripts.find((script) => script.name === "clarify");
const answers = clarify?.steps?.find((step) => step.answers)?.answers;
if (!clarify || !answers) {
  throw new Error("backend/cassettes/sessions.json has no clarify session");
}

// Reading the brief takes one replayed call; planning after the answer takes as long
// as the e2e journey's (ADR 0049).
const PLANNING_MS = 120_000;

test("a vague brief asks a question, and answering it resumes to a plan", async ({
  page,
}) => {
  test.setTimeout(PLANNING_MS + 60_000);
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText(/API healthy/);

  await page.getByLabel("Brief").fill(clarify.brief);
  await page.getByRole("button", { name: "Plan it" }).click();
  await expect(page).toHaveURL(/\/sessions\/[^/]+$/);

  // The session pauses at Clarify with the agent's question as a form (AG-02).
  await expect(page.getByRole("status")).toHaveText("Awaiting clarification", {
    timeout: PLANNING_MS,
  });
  const form = page.getByRole("form", { name: "Clarification questions" });
  await expect(form.getByRole("textbox")).toHaveCount(
    Object.keys(answers).length,
  );

  // What the agent read from the brief is already listed with its source (AG-01).
  const assumptions = page.getByRole("table", { name: "Assumptions" });
  await expect(
    assumptions.getByRole("row", { name: /^Regions North, West From brief/ }),
  ).toBeVisible();
  await expect(
    assumptions.getByRole("rowheader", { name: "Categories" }),
  ).toBeVisible();

  // Each recorded answer goes in its question's box: the box's id names the question.
  for (const [questionId, answer] of Object.entries(answers)) {
    await form
      .locator(
        `input[id="answer-${questionId.replace(/[^A-Za-z0-9_-]/g, "-")}"]`,
      )
      .fill(answer);
  }
  await form
    .getByRole("button", { name: "Answer and resume planning" })
    .click();

  await expect(form).toBeHidden();
  const plan = page.getByRole("table", { name: "Plan lines" });
  await expect(plan).toBeVisible({ timeout: PLANNING_MS });
  await expect(plan.getByRole("row").nth(1)).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Awaiting approval");

  // The answer became an assumption when the Context agent read the brief again.
  await expect(
    assumptions.getByRole("row", { name: /^Marketing budget ₹200,000/ }),
  ).toBeVisible();
});
