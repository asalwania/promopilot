import { describe, expect, it } from "vitest";

import {
  amendSession,
  approveSession,
  clarifySession,
  createSession,
  getSession,
  rejectSession,
  SessionLoadError,
} from "@/lib/api/sessions";

import {
  approvedSession,
  awaitingApprovalSession,
  infeasibleSession,
  openIssuesSession,
  planningSession,
  rejectedSession,
  SESSION_ID,
} from "./fixtures/sessions";

type Call = { url: string; init?: RequestInit };

function recordingFetch(response: () => Response) {
  const calls: Call[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    return response();
  };
  return { calls, fetchImpl };
}

describe("createSession", () => {
  it("posts the brief to the same-origin proxy and returns the new session id", async () => {
    const { calls, fetchImpl } = recordingFetch(() =>
      Response.json({ session_id: SESSION_ID }, { status: 202 }),
    );

    const result = await createSession("Diwali push for snacks", fetchImpl);

    expect(result).toEqual({ ok: true, sessionId: SESSION_ID });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/sessions");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      brief: "Diwali push for snacks",
    });
  });

  it("reports the API's validation message when the brief is rejected", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        {
          detail: [
            {
              loc: ["body", "brief"],
              msg: "Value error, the brief is empty",
              type: "value_error",
            },
          ],
        },
        { status: 422 },
      ),
    );

    const result = await createSession("   ", fetchImpl);

    expect(result).toEqual({
      ok: false,
      reason: "Value error, the brief is empty",
    });
  });

  it("reports the API as unreachable when the proxy answers 502", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json({ detail: "API unreachable" }, { status: 502 }),
    );

    const result = await createSession("Diwali push", fetchImpl);

    expect(result).toEqual({ ok: false, reason: "HTTP 502" });
  });

  it("reports the network error when the request cannot be sent", async () => {
    const failingFetch: typeof fetch = async () => {
      throw new TypeError("fetch failed");
    };

    const result = await createSession("Diwali push", failingFetch);

    expect(result).toEqual({ ok: false, reason: "fetch failed" });
  });

  it("fails plainly when the created session breaks the contract", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json({ id: 7 }, { status: 202 }),
    );

    const result = await createSession("Diwali push", fetchImpl);

    expect(result).toEqual({
      ok: false,
      reason: "unexpected session response",
    });
  });
});

describe("getSession", () => {
  it("reads the session from the same-origin proxy", async () => {
    const { calls, fetchImpl } = recordingFetch(() =>
      Response.json(awaitingApprovalSession),
    );

    const session = await getSession(SESSION_ID, fetchImpl);

    expect(session).toEqual(awaitingApprovalSession);
    expect(calls.map((call) => call.url)).toEqual([
      `/api/sessions/${SESSION_ID}`,
    ]);
  });

  it("reads an infeasible session with its binding constraints and relaxation", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(infeasibleSession),
    );

    const session = await getSession(SESSION_ID, fetchImpl);

    expect(session).toEqual(infeasibleSession);
    expect(session.plan_revision?.relaxation?.changes[0].relaxed).toBe(214500);
  });

  it("reads a revision's open issues: violations and the Critic's risk findings", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(openIssuesSession),
    );

    const session = await getSession(SESSION_ID, fetchImpl);

    expect(session).toEqual(openIssuesSession);
    expect(
      session.plan_revision?.open_issues.map((issue) => [
        issue.kind,
        issue.code,
      ]),
    ).toEqual([
      ["violation", "BUDGET"],
      ["risk", "STOCKOUT_RISK"],
    ]);
  });

  it("fails as not found when the API does not know the session", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json({ detail: "Session not found" }, { status: 404 }),
    );

    const failure = await getSession(SESSION_ID, fetchImpl).catch((e) => e);

    expect(failure).toBeInstanceOf(SessionLoadError);
    expect(failure).toMatchObject({
      message: "Session not found",
      notFound: true,
    });
  });

  it("fails with the HTTP status when the proxy answers 502", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json({ detail: "API unreachable" }, { status: 502 }),
    );

    const failure = await getSession(SESSION_ID, fetchImpl).catch((e) => e);

    expect(failure).toMatchObject({ message: "HTTP 502", notFound: false });
  });

  it("fails when the session breaks the contract", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json({ ...awaitingApprovalSession, status: "sideways" }),
    );

    const failure = await getSession(SESSION_ID, fetchImpl).catch((e) => e);

    expect(failure).toMatchObject({
      message: "unexpected session response",
      notFound: false,
    });
  });
});

describe("clarifySession", () => {
  const answers = { marketing_budget: "₹2 lakh" };

  it("posts every answer by question id and returns the resumed session", async () => {
    const { calls, fetchImpl } = recordingFetch(() =>
      Response.json(planningSession, { status: 202 }),
    );

    const result = await clarifySession(SESSION_ID, answers, fetchImpl);

    expect(result).toEqual({ ok: true, session: planningSession });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`/api/sessions/${SESSION_ID}/clarify`);
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ answers });
  });

  it("reports a conflict when the questions were already answered", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        {
          detail:
            "the session is planning: only a session awaiting clarification can be answered",
        },
        { status: 409 },
      ),
    );

    const result = await clarifySession(SESSION_ID, answers, fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: true,
      reason: "These questions were already answered.",
    });
  });

  it("reports the API's message when the answers do not match the questions", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        {
          detail:
            "answer every open question by its id; unanswered: scope.categories",
        },
        { status: 422 },
      ),
    );

    const result = await clarifySession(SESSION_ID, answers, fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: false,
      reason:
        "answer every open question by its id; unanswered: scope.categories",
    });
  });

  it("reports the first validation message when an answer is invalid", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        {
          detail: [
            {
              loc: ["body", "answers"],
              msg: "Value error, the answer to marketing_budget is empty",
              type: "value_error",
            },
          ],
        },
        { status: 422 },
      ),
    );

    const result = await clarifySession(SESSION_ID, answers, fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: false,
      reason: "Value error, the answer to marketing_budget is empty",
    });
  });

  it("reports why planning is unavailable", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        { detail: "planning is unavailable: no checkpoints" },
        { status: 503 },
      ),
    );

    const result = await clarifySession(SESSION_ID, answers, fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: false,
      reason: "planning is unavailable: no checkpoints",
    });
  });

  it("reports the HTTP status when the proxy answers without a message", async () => {
    const { fetchImpl } = recordingFetch(
      () => new Response("Bad Gateway", { status: 502 }),
    );

    const result = await clarifySession(SESSION_ID, answers, fetchImpl);

    expect(result).toEqual({ ok: false, conflict: false, reason: "HTTP 502" });
  });

  it("reports the network error when the answers cannot be sent", async () => {
    const failingFetch: typeof fetch = async () => {
      throw new TypeError("fetch failed");
    };

    const result = await clarifySession(SESSION_ID, answers, failingFetch);

    expect(result).toEqual({
      ok: false,
      conflict: false,
      reason: "fetch failed",
    });
  });

  it("fails plainly when the resumed session breaks the contract", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json({ status: "sideways" }, { status: 202 }),
    );

    const result = await clarifySession(SESSION_ID, answers, fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: false,
      reason: "unexpected session response",
    });
  });
});

describe("amendSession", () => {
  it("posts the amendment's text and returns the session, back in planning", async () => {
    const { calls, fetchImpl } = recordingFetch(() =>
      Response.json(planningSession, { status: 202 }),
    );

    const result = await amendSession(
      SESSION_ID,
      { text: "Budget cut to ₹6 lakh" },
      fetchImpl,
    );

    expect(result).toEqual({ ok: true, session: planningSession });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`/api/sessions/${SESSION_ID}/amend`);
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      text: "Budget cut to ₹6 lakh",
    });
  });

  it("accepts the latest revision's relaxation instead of text (ADR 0052 D7)", async () => {
    const { calls, fetchImpl } = recordingFetch(() =>
      Response.json(planningSession, { status: 202 }),
    );

    await amendSession(SESSION_ID, { acceptRelaxation: true }, fetchImpl);

    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      accept_relaxation: true,
    });
  });

  it("reports a conflict with the API's reason", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        {
          detail:
            "the session is approved: only a session awaiting approval, or rejected, can be amended",
        },
        { status: 409 },
      ),
    );

    const result = await amendSession(SESSION_ID, { text: "x" }, fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: true,
      reason:
        "the session is approved: only a session awaiting approval, or rejected, can be amended",
    });
  });

  it("reports the first validation message when the amendment is invalid", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        {
          detail: [
            {
              loc: ["body", "text"],
              msg: "Value error, an amendment needs text",
              type: "value_error",
            },
          ],
        },
        { status: 422 },
      ),
    );

    const result = await amendSession(SESSION_ID, { text: " " }, fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: false,
      reason: "Value error, an amendment needs text",
    });
  });

  it("reports the network error when the amendment cannot be sent", async () => {
    const failingFetch: typeof fetch = async () => {
      throw new TypeError("fetch failed");
    };

    const result = await amendSession(SESSION_ID, { text: "x" }, failingFetch);

    expect(result).toEqual({
      ok: false,
      conflict: false,
      reason: "fetch failed",
    });
  });
});

describe("approveSession", () => {
  it("approves the shown plan revision by its number", async () => {
    const { calls, fetchImpl } = recordingFetch(() =>
      Response.json(approvedSession),
    );

    const result = await approveSession(SESSION_ID, 1, fetchImpl);

    expect(result).toEqual({ ok: true, session: approvedSession });
    expect(calls[0].url).toBe(`/api/sessions/${SESSION_ID}/approve`);
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      revision_number: 1,
    });
  });

  it("reports a stale revision as a conflict with the API's reason", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        {
          detail: "plan revision 1 is not the session's latest plan revision",
        },
        { status: 409 },
      ),
    );

    const result = await approveSession(SESSION_ID, 1, fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: true,
      reason: "plan revision 1 is not the session's latest plan revision",
    });
  });

  it("reports why planning is unavailable", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        { detail: "planning is unavailable: no checkpoints" },
        { status: 503 },
      ),
    );

    const result = await approveSession(SESSION_ID, 1, fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: false,
      reason: "planning is unavailable: no checkpoints",
    });
  });
});

describe("rejectSession", () => {
  it("rejects the shown plan revision with the reason", async () => {
    const { calls, fetchImpl } = recordingFetch(() =>
      Response.json(rejectedSession),
    );

    const result = await rejectSession(
      SESSION_ID,
      1,
      "Too deep on Beverages in West.",
      fetchImpl,
    );

    expect(result).toEqual({ ok: true, session: rejectedSession });
    expect(calls[0].url).toBe(`/api/sessions/${SESSION_ID}/reject`);
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      revision_number: 1,
      reason: "Too deep on Beverages in West.",
    });
  });

  it("fails plainly when the decided session breaks the contract", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json({ status: "sideways" }),
    );

    const result = await rejectSession(SESSION_ID, 1, "No.", fetchImpl);

    expect(result).toEqual({
      ok: false,
      conflict: false,
      reason: "unexpected session response",
    });
  });
});
