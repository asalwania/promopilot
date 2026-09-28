import { describe, expect, it } from "vitest";

import {
  clarifySession,
  createSession,
  getSession,
  SessionLoadError,
} from "@/lib/api/sessions";

import {
  awaitingApprovalSession,
  infeasibleSession,
  openIssuesSession,
  planningSession,
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
