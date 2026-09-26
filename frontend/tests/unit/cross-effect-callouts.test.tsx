import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  CannibalisationCallout,
  HaloCallout,
} from "@/components/cross-effect-callouts";

import { crossEffects } from "./fixtures/cross-effects";

function itemsOf(name: string) {
  const callout = screen.getByRole("region", { name });
  return within(callout)
    .getAllByRole("listitem")
    .map((item) => item.textContent);
}

describe("CannibalisationCallout", () => {
  it("warns about the three costliest substitutes of at least 1%, then counts the rest", () => {
    render(
      <CannibalisationCallout promoted="SKU0003" effects={crossEffects} />,
    );

    // SKU0004 moves by only 0.6%, so it is left out despite its profit.
    expect(itemsOf("Cannibalisation")).toEqual([
      "Promoting SKU0003 reduces SKU0005's units by 3% (−₹9,800 profit)",
      "Promoting SKU0003 reduces SKU0007's units by 12% (−₹4,521 profit)",
      "Promoting SKU0003 reduces SKU0002's units by 7% (−₹1,200 profit)",
    ]);
    expect(screen.getByText("+1 more")).toBeInTheDocument();
  });

  it("renders nothing when no substitute moves by 1% or more", () => {
    const { container } = render(
      <CannibalisationCallout
        promoted="SKU0003"
        effects={crossEffects.filter((effect) => effect.sku_id === "SKU0004")}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

describe("HaloCallout", () => {
  it("shows the halo gains of at least 1%", () => {
    render(<HaloCallout promoted="SKU0003" effects={crossEffects} />);

    expect(itemsOf("Halo")).toEqual([
      "Promoting SKU0003 lifts SKU0031's units by 8% (+₹2,150 profit)",
    ]);
    expect(screen.queryByText(/more$/)).not.toBeInTheDocument();
  });

  it("renders nothing without a halo effect", () => {
    const { container } = render(
      <HaloCallout promoted="SKU0003" effects={[]} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
