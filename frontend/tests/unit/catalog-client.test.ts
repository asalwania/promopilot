import { describe, expect, it } from "vitest";

import {
  CatalogRequestError,
  getCompetitorGaps,
  getInventory,
  listProducts,
  listRegions,
} from "@/lib/api/catalog";

import { gaps, inventory, products, regions } from "./fixtures/catalog";

type Call = { url: string; init?: RequestInit };

function recordingFetch(response: () => Response) {
  const calls: Call[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    return response();
  };
  return { calls, fetchImpl };
}

describe("the data explorer's reads", () => {
  it.each([
    [
      "listProducts",
      listProducts,
      "/api/catalog/products",
      { products },
      products,
    ],
    ["listRegions", listRegions, "/api/catalog/regions", { regions }, regions],
    ["getInventory", getInventory, "/api/inventory", inventory, inventory],
    [
      "getCompetitorGaps",
      getCompetitorGaps,
      "/api/competitors/gaps",
      gaps,
      gaps,
    ],
  ] as const)(
    "%s reads through the same-origin proxy",
    async (_, read, url, body, expected) => {
      const { calls, fetchImpl } = recordingFetch(() => Response.json(body));

      expect(await read(fetchImpl)).toEqual(expected);
      expect(calls[0].url).toBe(url);
      expect(calls[0].init?.cache).toBe("no-store");
    },
  );

  it("asks for one as-of week's KVI gaps when the session page names them", async () => {
    const { calls, fetchImpl } = recordingFetch(() => Response.json(gaps));

    expect(
      await getCompetitorGaps(fetchImpl, { asOfWeek: 104, kviOnly: true }),
    ).toEqual(gaps);
    expect(calls[0].url).toBe(
      "/api/competitors/gaps?as_of_week=104&kvi_only=true",
    );
  });

  it("throws with the API's reason when it gives one", async () => {
    const { fetchImpl } = recordingFetch(() =>
      Response.json(
        { detail: "no sales history is loaded; run `make data`" },
        { status: 409 },
      ),
    );

    await expect(getInventory(fetchImpl)).rejects.toEqual(
      new CatalogRequestError("no sales history is loaded; run `make data`"),
    );
  });

  it("throws with the status when there is no reason", async () => {
    const { fetchImpl } = recordingFetch(
      () => new Response("boom", { status: 500 }),
    );

    await expect(listProducts(fetchImpl)).rejects.toEqual(
      new CatalogRequestError("HTTP 500"),
    );
  });

  it("throws on an unexpected response", async () => {
    const { fetchImpl } = recordingFetch(() => Response.json({ rows: [] }));

    await expect(listRegions(fetchImpl)).rejects.toEqual(
      new CatalogRequestError("unexpected response from /api/catalog/regions"),
    );
  });
});
