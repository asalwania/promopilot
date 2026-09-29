import { describe, expect, it } from "vitest";

import { EvalsRequestError, getLatestEvalReport } from "@/lib/api/evals";

import recorded from "./fixtures/eval-report.json";
import { recordedReport } from "./fixtures/evals";

type Call = { url: string; init?: RequestInit };

function recordingFetch(response: () => Response) {
  const calls: Call[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    return response();
  };
  return { calls, fetchImpl };
}

describe("getLatestEvalReport", () => {
  it("reads the latest report through the same-origin proxy", async () => {
    const { calls, fetchImpl } = recordingFetch(() => Response.json(recorded));

    const result = await getLatestEvalReport(fetchImpl);

    expect(result).toEqual({ kind: "report", report: recordedReport });
    expect(calls[0].url).toBe("/api/evals/latest");
    expect(calls[0].init?.cache).toBe("no-store");
  });

  it("answers 'no report' with the API's reason on a 404", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        { detail: "No eval report yet: run `make eval`." },
        { status: 404 },
      ),
    );

    await expect(getLatestEvalReport(fetchImpl)).resolves.toEqual({
      kind: "none",
      detail: "No eval report yet: run `make eval`.",
    });
  });

  it("throws with the reason and the reference id on any other failure", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        {
          detail: "The API failed.",
          code: "internal_error",
          reference_id: "req-42",
        },
        { status: 500 },
      ),
    );

    const failure = getLatestEvalReport(fetchImpl);

    await expect(failure).rejects.toEqual(
      new EvalsRequestError("The API failed.", "req-42"),
    );
    await expect(failure).rejects.toHaveProperty("referenceId", "req-42");
  });

  it("throws on a body that is not an eval report", async () => {
    const { fetchImpl } = recordingFetch(() => Response.json({ metrics: 3 }));

    await expect(getLatestEvalReport(fetchImpl)).rejects.toEqual(
      new EvalsRequestError("unexpected eval report"),
    );
  });
});
