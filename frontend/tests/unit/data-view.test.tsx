import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataView } from "@/components/data-view";

import { gaps, inventory, products, regions } from "./fixtures/catalog";

type Answer = () => Response | Promise<Response>;

const BODIES: Record<string, unknown> = {
  "/api/catalog/products": { products },
  "/api/catalog/regions": { regions },
  "/api/inventory": inventory,
  "/api/competitors/gaps": gaps,
};

// Every endpoint answers its fixture unless a test overrides it; each call to
// an overridden endpoint takes its next answer, and the last one repeats.
function stubDataApi(overrides: Record<string, Answer[]> = {}) {
  const requested: string[] = [];
  const calls: Record<string, number> = {};
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);
    const answers = overrides[url];
    if (answers) {
      calls[url] = (calls[url] ?? 0) + 1;
      return answers[Math.min(calls[url], answers.length) - 1]();
    }
    return Response.json(BODIES[url]);
  });
  return requested;
}

function renderDataView() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <DataView />
    </QueryClientProvider>,
  );
}

// Each body row's cells as text, header row left out.
async function rowsOf(name: string): Promise<string[][]> {
  const table = await screen.findByRole("table", { name });
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent ?? ""),
    );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("DataView", () => {
  it("shows products with their prices and KVI flag", async () => {
    stubDataApi();
    renderDataView();

    expect(await rowsOf("Products")).toEqual([
      [
        "SKU0007",
        "Crunchy Namkeen 400g",
        "Crunchy",
        "Snacks / Namkeen",
        "400g",
        "₹110.00",
        "₹72.50",
        "",
      ],
      [
        "SKU0101",
        "Annapurna Atta 5kg",
        "Annapurna",
        "Staples / Atta",
        "5kg",
        "₹280.00",
        "₹231.00",
        "KVI",
      ],
      [
        "SKU0102",
        "Kisan Gold Rice 1kg",
        "Kisan Gold",
        "Staples / Rice",
        "1kg",
        "₹100.00",
        "₹82.00",
        "KVI",
      ],
    ]);
  });

  it("shows pooled inventory with an Overstocked badge and the as-of caption", async () => {
    stubDataApi();
    renderDataView();

    expect(await rowsOf("Inventory")).toEqual([
      [
        "SKU0007",
        "Crunchy Namkeen 400g",
        "North",
        "1,200",
        "150",
        "0",
        "1,050",
        "71.4",
        "Overstocked",
      ],
      [
        "SKU0007",
        "Crunchy Namkeen 400g",
        "South",
        "400",
        "120",
        "60",
        "280",
        "20.0",
        "",
      ],
      [
        "SKU0101",
        "Annapurna Atta 5kg",
        "North",
        "300",
        "90",
        "40",
        "210",
        "14.3",
        "",
      ],
    ]);
    expect(
      screen.getByText(
        "As of W105 · stock at end of W104 · overstock above 56 days",
      ),
    ).toBeInTheDocument();
  });

  it("shows competitor gaps with Undercut and On promo badges, and the undercut callout", async () => {
    stubDataApi();
    renderDataView();

    expect(await rowsOf("Competitor gaps")).toEqual([
      [
        "SKU0101",
        "Annapurna Atta 5kg",
        "North",
        "₹280.00",
        "₹252.00On promo",
        "W103",
        "0.900",
        "10.0%",
        "Undercut",
      ],
      [
        "SKU0007",
        "Crunchy Namkeen 400g",
        "West",
        "₹110.00",
        "₹93.50On promo",
        "W103",
        "0.850",
        "15.0%",
        "",
      ],
      [
        "SKU0102",
        "Kisan Gold Rice 1kg",
        "South",
        "₹100.00",
        "₹94.90",
        "W103",
        "0.949",
        "5.1%",
        "Undercut",
      ],
      [
        "SKU0103",
        "Desi Harvest Dal 1kg",
        "North",
        "₹100.00",
        "₹95.10",
        "W103",
        "0.951",
        "4.9%",
        "",
      ],
    ]);
    const callout = screen.getByRole("note", { name: "Competitor undercuts" });
    expect(within(callout).getAllByRole("listitem")).toHaveLength(2);
  });

  it("names the source tool on every number", async () => {
    stubDataApi();
    renderDataView();

    const productsTable = await screen.findByRole("table", {
      name: "Products",
    });
    expect(within(productsTable).getByText("₹72.50")).toHaveAttribute(
      "title",
      "Source: get_scope_data",
    );
    const inventoryTable = await screen.findByRole("table", {
      name: "Inventory",
    });
    expect(within(inventoryTable).getByText("1,050")).toHaveAttribute(
      "title",
      "Source: get_inventory_status · stock at end of W104",
    );
    const gapsTable = await screen.findByRole("table", {
      name: "Competitor gaps",
    });
    expect(within(gapsTable).getByText("0.949")).toHaveAttribute(
      "title",
      "Source: get_competitor_gaps · as of W105",
    );
  });

  it("filters inventory and gaps by region, and every list by category", async () => {
    stubDataApi();
    renderDataView();
    await screen.findByRole("option", { name: "South" });

    fireEvent.change(screen.getByRole("combobox", { name: "Region" }), {
      target: { value: "North" },
    });

    expect((await rowsOf("Inventory")).map((row) => row[2])).toEqual([
      "North",
      "North",
    ]);
    expect((await rowsOf("Competitor gaps")).map((row) => row[0])).toEqual([
      "SKU0101",
      "SKU0103",
    ]);
    expect(await rowsOf("Products")).toHaveLength(3);

    fireEvent.change(screen.getByRole("combobox", { name: "Category" }), {
      target: { value: "Snacks" },
    });

    expect((await rowsOf("Products")).map((row) => row[0])).toEqual([
      "SKU0007",
    ]);
    expect((await rowsOf("Inventory")).map((row) => row[0])).toEqual([
      "SKU0007",
    ]);
    expect(
      screen.queryByRole("table", { name: "Competitor gaps" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("No competitor gaps match these filters."),
    ).toBeInTheDocument();
  });

  it("narrows to overstocked SKUs and to undercut KVIs", async () => {
    stubDataApi();
    renderDataView();
    await screen.findByRole("table", { name: "Inventory" });

    fireEvent.click(screen.getByRole("checkbox", { name: "Overstocked only" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Undercut KVIs only" }),
    );

    expect((await rowsOf("Inventory")).map((row) => row.slice(0, 3))).toEqual([
      ["SKU0007", "Crunchy Namkeen 400g", "North"],
    ]);
    expect((await rowsOf("Competitor gaps")).map((row) => row[0])).toEqual([
      "SKU0101",
      "SKU0102",
    ]);
  });

  it("shows a panel's failure with the API's reason and a Retry that recovers, leaving the others", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const noData = () =>
      Response.json(
        { detail: "no sales history is loaded; run `make data`" },
        { status: 409 },
      );
    const requested = stubDataApi({
      "/api/inventory": [
        noData,
        noData,
        noData,
        () => Response.json(inventory),
      ],
    });
    renderDataView();
    await act(() => vi.advanceTimersByTimeAsync(5000));

    expect(screen.getByText("Couldn't load inventory")).toBeInTheDocument();
    expect(requested.filter((url) => url === "/api/inventory")).toHaveLength(3);
    expect(
      screen.getByText("no sales history is loaded; run `make data`"),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("table", { name: "Products" }),
    ).toBeInTheDocument();

    await act(() => screen.getByRole("button", { name: "Retry" }).click());

    expect(
      await screen.findByRole("table", { name: "Inventory" }),
    ).toBeInTheDocument();
  });

  it("shows loading states until the data arrives", async () => {
    stubDataApi({ "/api/competitors/gaps": [() => new Promise(() => {})] });
    renderDataView();

    expect(screen.getByText("Loading competitor gaps…")).toBeInTheDocument();
    await screen.findByRole("table", { name: "Products" });
    expect(screen.getByText("Loading competitor gaps…")).toBeInTheDocument();
  });
});
