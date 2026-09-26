import { describe, expect, it } from "vitest";

import {
  createSession,
  getSession,
  SessionLoadError,
} from "@/lib/api/sessions";

import { awaitingApprovalSession, SESSION_ID } from "./fixtures/sessions";

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
