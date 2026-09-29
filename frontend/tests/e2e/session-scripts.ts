import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, type Page } from "@playwright/test";

export type SessionScript = {
  name: string;
  brief: string;
  steps?: Array<{
    answers?: Record<string, string>;
    amend?: string;
    approve?: boolean;
  }>;
};

// The session scripts `make record-cassettes` recorded (ADR 0054): the composed api
// replays every LLM call of these sessions, so the journeys need no API key.
export function sessionScript(name: string): SessionScript {
  const scripts = JSON.parse(
    readFileSync(
      join(__dirname, "../../../backend/cassettes/sessions.json"),
      "utf-8",
    ),
  ) as SessionScript[];
  const script = scripts.find((candidate) => candidate.name === name);
  if (!script) {
    throw new Error(`backend/cassettes/sessions.json has no ${name} session`);
  }
  return script;
}

// The planner agent calls the optimiser and the simulator (ADR 0049): on the seed-42
// world a planning round takes tens of seconds on a CI runner.
export const PLANNING_MS = 120_000;

// Types the brief on the home page and waits for its first plan revision.
export async function planBrief(page: Page, brief: string) {
  await page.goto("/");
  // Health is fetched in the browser, so seeing it means the page has hydrated.
  await expect(page.getByRole("status")).toHaveText(/API healthy/);
  await page.getByLabel("Brief").fill(brief);
  await page.getByRole("button", { name: "Plan it" }).click();
  await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
  await expect(page.getByRole("status")).toHaveText("Awaiting approval", {
    timeout: PLANNING_MS,
  });
}

// The session as the API holds it, read through the proxy.
export async function readSession<T>(page: Page): Promise<T> {
  const sessionId = new URL(page.url()).pathname.split("/").pop();
  const response = await page.request.get(`/api/sessions/${sessionId}`);
  expect(response.ok()).toBe(true);
  return (await response.json()) as T;
}
