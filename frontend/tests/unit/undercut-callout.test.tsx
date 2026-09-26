import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UndercutCallout } from "@/components/undercut-callout";

import { competitorGaps } from "./fixtures/competitors";

describe("UndercutCallout", () => {
  it("lists each undercut KVI with the gap, region and both prices", () => {
    render(<UndercutCallout gaps={competitorGaps} />);

    const callout = screen.getByRole("note", { name: "Competitor undercuts" });
    const items = within(callout)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(items).toEqual([
      "Competitor is 10.0% cheaper on Annapurna Atta 5kg in North (₹252.00 vs ₹280.00)On promo",
      "Competitor is 5.1% cheaper on Kisan Gold Rice 1kg in South (₹94.90 vs ₹100.00)",
    ]);
  });

  it("leaves out non-KVIs and gaps within the threshold", () => {
    render(<UndercutCallout gaps={competitorGaps} />);

    const callout = screen.getByRole("note", { name: "Competitor undercuts" });
    expect(callout).not.toHaveTextContent("Crunchy Namkeen");
    expect(callout).not.toHaveTextContent("Desi Harvest Dal");
  });

  it("marks only a competitor price that was a promo", () => {
    render(<UndercutCallout gaps={competitorGaps} />);

    expect(screen.getAllByText("On promo")).toHaveLength(1);
  });

  it("renders nothing when no KVI is undercut", () => {
    const { container } = render(
      <UndercutCallout gaps={competitorGaps.filter((gap) => !gap.undercut)} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
