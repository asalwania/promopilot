import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModelsView } from "@/components/models-view";
import type { ModelEntry } from "@/lib/api/models";

import { demandV1, demandV2, demandV3 } from "./fixtures/models";

type Answer = () => Response | Promise<Response>;

// Each call to an endpoint takes its next answer; the last one repeats.
function stubModelsApi(answers: { list: Answer[]; retrain?: Answer[] }) {
  const requested: string[] = [];
  let lists = 0;
  let retrains = 0;
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = `${init?.method ?? "GET"} ${String(input)}`;
      requested.push(request);
      if (request === "POST /api/models/retrain") {
        const retrain = answers.retrain ?? [];
        return retrain[Math.min(++retrains, retrain.length) - 1]();
      }
      return answers.list[Math.min(++lists, answers.list.length) - 1]();
    },
  );
  return requested;
}

const listing = (models: ModelEntry[]) => () => Response.json({ models });

function renderModelsView() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ModelsView />
    </QueryClientProvider>,
  );
}

async function advance(ms: number) {
  await act(() => vi.advanceTimersByTimeAsync(ms));
}

const retrainButton = () => screen.getByRole("button", { name: /Retrain/ });

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ModelsView", () => {
  it("loads the registry once when the page opens", async () => {
    const requested = stubModelsApi({ list: [listing([demandV2, demandV1])] });

    renderModelsView();

    expect(
      await screen.findByRole("table", { name: "Demand model versions" }),
    ).toBeVisible();
    await advance(60_000);
    expect(requested).toEqual(["GET /api/models"]);
  });

  it("gives up after retries with the reason and a Retry button that recovers", async () => {
    const unreachable = () =>
      Response.json({ detail: "API unreachable" }, { status: 502 });
    const requested = stubModelsApi({
      list: [unreachable, unreachable, unreachable, listing([demandV2])],
    });

    renderModelsView();
    await advance(5000);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Couldn't load models",
    );
    expect(screen.getByText("API unreachable")).toBeInTheDocument();
    expect(requested).toHaveLength(3);

    await act(() => screen.getByRole("button", { name: "Retry" }).click());

    expect(
      await screen.findByRole("table", { name: "Demand model versions" }),
    ).toBeVisible();
  });

  it("retrains with a timer, then says the new version is live and reloads the list", async () => {
    let finish: (response: Response) => void = () => {};
    const requested = stubModelsApi({
      list: [listing([demandV2, demandV1]), listing([demandV3, demandV2])],
      retrain: [() => new Promise((resolve) => (finish = resolve))],
    });
    renderModelsView();
    await screen.findByRole("table", { name: "Demand model versions" });

    await act(() => retrainButton().click());

    expect(retrainButton()).toBeDisabled();
    expect(retrainButton()).toHaveTextContent("Retraining…");
    expect(
      screen.getByRole("progressbar", { name: "Retraining in progress" }),
    ).toBeInTheDocument();
    await advance(37_000);
    expect(screen.getByText(/0:37 elapsed/)).toBeInTheDocument();

    await act(async () => finish(Response.json(demandV3, { status: 201 })));

    expect(await screen.findByText("Version 3 is live")).toBeInTheDocument();
    expect(retrainButton()).toBeEnabled();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    const table = await screen.findByRole("table", {
      name: "Demand model versions",
    });
    await vi.waitFor(() =>
      expect(within(table).getByText("v3")).toBeInTheDocument(),
    );
    expect(requested).toEqual([
      "GET /api/models",
      "POST /api/models/retrain",
      "GET /api/models",
    ]);
  });

  it("shows the API's reason when a retrain conflicts", async () => {
    stubModelsApi({
      list: [listing([demandV2])],
      retrain: [
        () =>
          Response.json(
            {
              detail:
                "a retrain is already running; try again when it finishes",
            },
            { status: 409 },
          ),
      ],
    });
    renderModelsView();
    await screen.findByRole("table", { name: "Demand model versions" });

    await act(() => retrainButton().click());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't retrain: a retrain is already running; try again when it finishes",
    );
    expect(retrainButton()).toBeEnabled();
  });

  it("shows the network error when the retrain request fails", async () => {
    stubModelsApi({
      list: [listing([demandV2])],
      retrain: [() => Promise.reject(new TypeError("Failed to fetch"))],
    });
    renderModelsView();
    await screen.findByRole("table", { name: "Demand model versions" });

    await act(() => retrainButton().click());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't retrain: Failed to fetch",
    );
  });
});
