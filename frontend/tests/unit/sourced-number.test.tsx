import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourcedNumber } from "@/components/sourced-number";
import { formatPrice } from "@/lib/format";

describe("SourcedNumber", () => {
  it("shows the formatted value with a tooltip naming its source tool", () => {
    render(
      <SourcedNumber
        value={94.9}
        format={formatPrice}
        source="get_competitor_gaps"
      />,
    );

    expect(screen.getByText("₹94.90")).toHaveAttribute(
      "title",
      "Source: get_competitor_gaps",
    );
  });

  it("adds the optional detail to the tooltip", () => {
    render(
      <SourcedNumber
        value={1200}
        source="get_inventory_status"
        detail="stock at end of W104"
      />,
    );

    expect(
      screen.getByTitle("Source: get_inventory_status · stock at end of W104"),
    ).toHaveTextContent("1,200");
  });
});
