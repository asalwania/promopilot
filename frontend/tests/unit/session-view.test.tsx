import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionView } from "@/components/session-view";
import type { Session } from "@/lib/api/sessions";

import {
  awaitingApprovalSession,
  planningSession,
  SESSION_ID,
} from "./fixtures/sessions";

// Each call to the stubbed proxy takes the next answer; the last one repeats.
function stubSessionApi(answers: Array<() => Response>) {
  const requested: string[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    requested.push(String(input));
    const answer = answers[Math.min(requested.length, answers.length) - 1];
    return answer();
  });
  return requested;
}

const answer = (session: Session) => () => Response.json(session);

function renderSessionView() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <SessionView sessionId={SESSION_ID} />
    </QueryClientProvider>,
  );
}

async function advance(ms: number) {
  await act(() => vi.advanceTimersByTimeAsync(ms));
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("SessionView", () => {
  it("polls while planning, shows the plan once ready, then stops polling", async () => {
    const requested = stubSessionApi([
      answer(planningSession),
      answer(planningSession),
      answer(awaitingApprovalSession),
    ]);

    renderSessionView();

    expect(await screen.findByText("Planning…")).toBeInTheDocument();
    await advance(1000);
    expect(screen.getByText("Planning…")).toBeInTheDocument();
    await advance(1000);
    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Plan lines" })).toBeVisible();

    await advance(5000);
    expect(requested).toEqual(Array(3).fill(`/api/sessions/${SESSION_ID}`));
  });

  it("says the session is not found without retrying", async () => {
    const requested = stubSessionApi([
      () => Response.json({ detail: "Session not found" }, { status: 404 }),
    ]);

    renderSessionView();

    expect(await screen.findByText("Session not found")).toBeInTheDocument();
    await advance(10_000);
    expect(requested).toHaveLength(1);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Retry" }),
    ).not.toBeInTheDocument();
  });

  it("gives up after retries with the reason and a Retry button that recovers", async () => {
    const unreachable = () =>
      Response.json({ detail: "API unreachable" }, { status: 502 });
    const requested = stubSessionApi([
      unreachable,
      unreachable,
      unreachable,
      answer(awaitingApprovalSession),
    ]);

    renderSessionView();
    await advance(5000);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Couldn't load the session",
    );
    expect(screen.getByText("HTTP 502")).toBeInTheDocument();
    expect(requested).toHaveLength(3);

    await act(() => screen.getByRole("button", { name: "Retry" }).click());

    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
  });

  it("stops the spinner and polling when the API drops mid-planning", async () => {
    const requested = stubSessionApi([
      answer(planningSession),
      () => Response.json({ detail: "API unreachable" }, { status: 502 }),
    ]);

    renderSessionView();
    expect(await screen.findByText("Planning…")).toBeInTheDocument();
    await advance(10_000);
    const settled = requested.length;
    await advance(10_000);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Couldn't load the session",
    );
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(requested).toHaveLength(settled);
  });
});
