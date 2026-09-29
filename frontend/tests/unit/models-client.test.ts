import { describe, expect, it } from "vitest";

import {
  listModels,
  ModelsRequestError,
  retrainModels,
} from "@/lib/api/models";

import { demandV1, demandV2, relationsV1 } from "./fixtures/models";

type Call = { url: string; init?: RequestInit };

function recordingFetch(response: () => Response) {
  const calls: Call[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    return response();
  };
  return { calls, fetchImpl };
}

describe("listModels", () => {
  it("reads the registry through the same-origin proxy, any kind included", async () => {
    const { calls, fetchImpl } = recordingFetch(() =>
      Response.json({ models: [relationsV1, demandV2, demandV1] }),
    );

    const models = await listModels(fetchImpl);

    expect(models).toEqual([relationsV1, demandV2, demandV1]);
    expect(calls[0].url).toBe("/api/models");
    expect(calls[0].init?.cache).toBe("no-store");
  });

  it("throws with the API's reason when the read fails", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json({ detail: "API unreachable" }, { status: 502 }),
    );

    await expect(listModels(fetchImpl)).rejects.toEqual(
      new ModelsRequestError("API unreachable"),
    );
  });

  it("throws when the response breaks the contract", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json({ models: [{ version: "one" }] }),
    );

    await expect(listModels(fetchImpl)).rejects.toEqual(
      new ModelsRequestError("unexpected models response"),
    );
  });
});

describe("retrainModels", () => {
  it("posts to the retrain endpoint and returns the new live model", async () => {
    const { calls, fetchImpl } = recordingFetch(() =>
      Response.json(demandV2, { status: 201 }),
    );

    const model = await retrainModels(fetchImpl);

    expect(model).toEqual(demandV2);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/models/retrain");
    expect(calls[0].init?.method).toBe("POST");
  });

  it("throws the API's reason on a conflict", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        {
          detail: "a retrain is already running; try again when it finishes",
        },
        { status: 409 },
      ),
    );

    await expect(retrainModels(fetchImpl)).rejects.toEqual(
      new ModelsRequestError(
        "a retrain is already running; try again when it finishes",
      ),
    );
  });

  it("falls back to the status when the error has no reason", async () => {
    const { fetchImpl } = recordingFetch(
      () => new Response("Internal Server Error", { status: 500 }),
    );

    await expect(retrainModels(fetchImpl)).rejects.toEqual(
      new ModelsRequestError("HTTP 500"),
    );
  });
});
