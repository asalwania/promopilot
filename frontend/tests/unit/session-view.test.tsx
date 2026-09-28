import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionView } from "@/components/session-view";
import type { Session } from "@/lib/api/sessions";

import { FakeEventSource } from "./fixtures/fake-event-source";
import {
  amendedSession,
  approvedSession,
  awaitingApprovalSession,
  awaitingClarificationSession,
  planningSession,
  rejectedSession,
  replanningSession,
  SESSION_ID,
  undercutGaps,
} from "./fixtures/sessions";
import { traceEvents } from "./fixtures/trace";

// Each session read from the stubbed proxy takes the next answer; the last one
// repeats. Competitor gaps (the plan's undercut callouts) are answered apart.
function stubSessionApi(
  answers: Array<() => Response>,
  gaps: () => Response = () =>
    Response.json({
      as_of_week: 104,
      undercut_threshold: 0.05,
      kvi_price_tolerance: 0.05,
      gaps: undercutGaps,
    }),
) {
  const requested: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).startsWith("/api/competitors/gaps")) return gaps();
      requested.push(String(input));
      const answer = answers[Math.min(requested.length, answers.length) - 1];
      return answer();
    }),
  );
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
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// Reads take the next session in turn (the last repeats); a POST to /clarify takes `clarify`.
function stubClarifyApi(reads: Session[], clarify: () => Response) {
  const posted: unknown[] = [];
  let read = 0;
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      // The plan's undercut callouts read gaps; they are not a session read.
      if (String(input).startsWith("/api/competitors/gaps")) {
        return Response.json({ detail: "no gaps here" }, { status: 404 });
      }
      if (String(input).endsWith("/clarify")) {
        posted.push(JSON.parse(String(init?.body)));
        return clarify();
      }
      read += 1;
      return Response.json(reads[Math.min(read, reads.length) - 1]);
    },
  );
  return posted;
}

function answerQuestions() {
  fireEvent.change(
    screen.getByRole("textbox", {
      name: "What marketing budget should the plan's promo cost stay within, in rupees?",
    }),
    { target: { value: "₹2 lakh" } },
  );
  fireEvent.change(
    screen.getByRole("textbox", {
      name: 'Which product categories does "snak stuff" mean?',
    }),
    { target: { value: "Snacks" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Answer and resume planning" }),
  );
}

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
    expect(
      screen.getByRole("table", { name: "Plan lines in North" }),
    ).toBeVisible();

    await advance(5000);
    expect(requested).toEqual(Array(3).fill(`/api/sessions/${SESSION_ID}`));
  });

  it("sends the answers, then polls the resumed planning through to the plan", async () => {
    const posted = stubClarifyApi(
      [awaitingClarificationSession, planningSession, awaitingApprovalSession],
      () => Response.json(planningSession, { status: 202 }),
    );

    renderSessionView();
    expect(
      await screen.findByText("Awaiting clarification"),
    ).toBeInTheDocument();
    answerQuestions();

    // The 202 carries the session back in planning: the form goes at once.
    expect(await screen.findByText("Planning…")).toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Clarification questions" }),
    ).not.toBeInTheDocument();
    expect(posted).toEqual([
      {
        answers: { marketing_budget: "₹2 lakh", "scope.categories": "Snacks" },
      },
    ]);

    await advance(1000);
    await advance(1000);
    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Plan lines in North" }),
    ).toBeVisible();
  });

  it("says the questions were already answered and reloads the session", async () => {
    stubClarifyApi([awaitingClarificationSession, planningSession], () =>
      Response.json(
        {
          detail:
            "the session is planning: only a session awaiting clarification can be answered",
        },
        { status: 409 },
      ),
    );

    renderSessionView();
    expect(
      await screen.findByText("Awaiting clarification"),
    ).toBeInTheDocument();
    answerQuestions();

    expect(await screen.findByText("Planning…")).toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Clarification questions" }),
    ).not.toBeInTheDocument();
  });

  it("streams the agent trace next to the session and its LLM usage", async () => {
    stubSessionApi([answer(awaitingApprovalSession)]);

    renderSessionView();
    const source = FakeEventSource.latest();
    expect(source.url).toBe(`/api/sessions/${SESSION_ID}/events`);
    act(() => {
      source.open();
      traceEvents.forEach((event) => source.send(event));
    });

    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
    const timeline = screen.getByRole("list", { name: "Trace timeline" });
    expect(timeline).toHaveTextContent("Context agent");
    expect(timeline).toHaveTextContent("get_inventory_status");
    expect(screen.getByRole("region", { name: "LLM usage" })).toBeVisible();
  });

  it("shows the trace while the session is still loading", () => {
    stubSessionApi([() => new Promise<Response>(() => {}) as never]);

    renderSessionView();
    act(() => {
      FakeEventSource.latest().open();
      FakeEventSource.latest().send(traceEvents[0]);
    });

    expect(screen.getByRole("status")).toHaveTextContent("Loading session…");
    expect(
      screen.getByRole("list", { name: "Trace timeline" }),
    ).toHaveTextContent("Context agent");
  });

  it("says the session is not found without retrying", async () => {
    const requested = stubSessionApi([
      () => Response.json({ detail: "Session not found" }, { status: 404 }),
    ]);

    renderSessionView();

    expect(await screen.findByText("Session not found")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Agent trace" }),
    ).not.toBeInTheDocument();
    expect(FakeEventSource.latest().closed).toBe(true);
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

  it("marks undercut lines from the KVI gaps at the request's as-of week", async () => {
    const fetched: string[] = [];
    stubSessionApi([answer(awaitingApprovalSession)], () => {
      fetched.push("gaps");
      return Response.json({
        as_of_week: 104,
        undercut_threshold: 0.05,
        kvi_price_tolerance: 0.05,
        gaps: undercutGaps,
      });
    });
    const spy = vi.mocked(fetch);

    renderSessionView();

    const north = await screen.findByRole("table", {
      name: "Plan lines in North",
    });
    expect(await within(north).findByText("Undercut")).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith(
      "/api/competitors/gaps?as_of_week=104&kvi_only=true",
      { cache: "no-store" },
    );
    expect(fetched).toHaveLength(1);
  });

  it("still shows the plan when the competitor gaps cannot be read", async () => {
    stubSessionApi(
      [answer(awaitingApprovalSession)],
      () => new Response("down", { status: 502 }),
    );

    renderSessionView();

    const north = await screen.findByRole("table", {
      name: "Plan lines in North",
    });
    await advance(10_000);
    expect(within(north).queryByText("Undercut")).not.toBeInTheDocument();
  });

  it("shows the re-planning at once after an amendment, then the new revision's diff", async () => {
    const posted = stubActionApi(
      [awaitingApprovalSession, replanningSession, amendedSession],
      { amend: () => Response.json(replanningSession, { status: 202 }) },
    );

    renderSessionView();
    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Amend the brief" }), {
      target: { value: "Budget cut to ₹1.5 lakh" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Amend and re-plan" }));

    // The 202 carries the session back in planning: the review goes at once.
    expect(await screen.findByText("Planning…")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: /^Review plan revision/ }),
    ).not.toBeInTheDocument();
    expect(posted).toEqual([
      { action: "amend", body: { text: "Budget cut to ₹1.5 lakh" } },
    ]);

    await advance(1000);
    await advance(1000);
    expect(
      await screen.findByRole("region", {
        name: "What changed from plan revision 1",
      }),
    ).toBeVisible();
    expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
  });

  it("approves the shown revision and shows the session as final", async () => {
    const posted = stubActionApi([awaitingApprovalSession], {
      approve: () => Response.json(approvedSession),
    });

    renderSessionView();
    fireEvent.click(
      await screen.findByRole("button", { name: "Approve plan revision 1" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));

    expect(await screen.findByText("Final")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Approved");
    expect(
      screen.queryByRole("region", { name: /^Review plan revision/ }),
    ).not.toBeInTheDocument();
    expect(posted).toEqual([
      { action: "approve", body: { revision_number: 1 } },
    ]);
  });

  it("rejects with the reason and keeps the session open for an amendment", async () => {
    const posted = stubActionApi([awaitingApprovalSession], {
      reject: () => Response.json(rejectedSession),
    });

    renderSessionView();
    fireEvent.click(
      await screen.findByRole("button", { name: "Reject plan revision 1" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", {
        name: "Why are you rejecting plan revision 1?",
      }),
      { target: { value: "Too deep on Beverages in West." } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send rejection" }));

    expect(await screen.findByText("Rejected")).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Amend the brief" })).toBeVisible();
    expect(posted).toEqual([
      {
        action: "reject",
        body: { revision_number: 1, reason: "Too deep on Beverages in West." },
      },
    ]);
  });

  it("shows the API's reason for a conflict and reloads the session", async () => {
    stubActionApi([awaitingApprovalSession, approvedSession], {
      reject: () =>
        Response.json(
          {
            detail:
              "the session is approved: only a session awaiting approval can be rejected",
          },
          { status: 409 },
        ),
    });

    renderSessionView();
    fireEvent.click(
      await screen.findByRole("button", { name: "Reject plan revision 1" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", {
        name: "Why are you rejecting plan revision 1?",
      }),
      { target: { value: "Too deep." } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send rejection" }));

    // Reloaded, the session is approved elsewhere: final, with nothing to decide.
    expect(await screen.findByText("Final")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: /^Review plan revision/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps the review and shows the reason when a conflict leaves the session as it was", async () => {
    stubActionApi([awaitingApprovalSession], {
      approve: () =>
        Response.json(
          {
            detail: "plan revision 1 is not the session's latest plan revision",
          },
          { status: 409 },
        ),
    });

    renderSessionView();
    fireEvent.click(
      await screen.findByRole("button", { name: "Approve plan revision 1" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't approve plan revision 1: plan revision 1 is not the session's latest plan revision",
    );
  });
});

// Reads take the next session in turn (the last repeats); a POST to an action takes
// that action's answer. Returns what was posted, in order.
function stubActionApi(
  reads: Session[],
  actions: Partial<Record<"amend" | "approve" | "reject", () => Response>>,
) {
  const posted: Array<{ action: string; body: unknown }> = [];
  let read = 0;
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/competitors/gaps")) {
        return Response.json({ detail: "no gaps here" }, { status: 404 });
      }
      const action = url.split("/").pop() as keyof typeof actions;
      if (init?.method === "POST" && actions[action]) {
        posted.push({ action, body: JSON.parse(String(init.body)) });
        return actions[action]();
      }
      read += 1;
      return Response.json(reads[Math.min(read, reads.length) - 1]);
    },
  );
  return posted;
}
