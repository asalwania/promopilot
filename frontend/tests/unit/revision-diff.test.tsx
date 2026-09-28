import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RevisionDiffView } from "@/components/revision-diff";
import type { PlanRevision, RevisionDiff } from "@/lib/api/sessions";

import { amendedSession } from "./fixtures/sessions";

const revision = amendedSession.plan_revision as PlanRevision;
const diff = revision.diff as RevisionDiff;
const amendment = amendedSession.amendments[0];

function renderDiff(
  props: Partial<Parameters<typeof RevisionDiffView>[0]> = {},
) {
  return render(
    <RevisionDiffView
      diff={diff}
      explanation={revision.explanation}
      amendment={amendment}
      {...props}
    />,
  );
}

describe("RevisionDiffView", () => {
  it("names the revision it compares against and the amendment that led here", () => {
    renderDiff();

    const section = screen.getByRole("region", {
      name: "What changed from plan revision 1",
    });
    expect(section).toHaveTextContent(
      "After your amendment “Budget cut to ₹1.5 lakh”",
    );
  });

  it("says what changed and why in the Explainer's words", () => {
    renderDiff();

    expect(
      screen.getByText(/The marketing budget went from ₹2 lakh to ₹1.5 lakh/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Template explanation")).not.toBeInTheDocument();
  });

  it("marks a change explanation the template wrote", () => {
    renderDiff({
      explanation: {
        ...revision.explanation!,
        source: "template",
        fallback_reason: "llm_unavailable",
      },
    });

    expect(screen.getByText("Template explanation")).toBeInTheDocument();
  });

  it("lists each planning-request change before and after", () => {
    renderDiff();

    const changes = screen.getByRole("list", { name: "Request changes" });
    expect(within(changes).getByRole("listitem")).toHaveTextContent(
      "Marketing budget: ₹2 lakh → ₹1.5 lakh",
    );
  });

  it("shows the objective and promo cost before, after and their change, each sourced", () => {
    renderDiff();

    const totals = screen.getByRole("table", { name: "Plan totals" });
    const objective = within(totals).getByRole("row", { name: /^Objective/ });
    expect(objective).toHaveTextContent("₹12,731₹9,800-₹2,931");
    expect(within(objective).getByText("-₹2,931")).toHaveAttribute(
      "title",
      expect.stringMatching(/^Source: run_optimizer/),
    );
    const cost = within(totals).getByRole("row", { name: /^Promo cost/ });
    expect(cost).toHaveTextContent("₹1.46 lakh₹22,600-₹1.24 lakh");
    expect(within(cost).getByText("₹22,600")).toHaveAttribute(
      "title",
      expect.stringMatching(/^Source: generate_candidates/),
    );
  });

  it("signs a rise and dashes an objective one revision lacks", () => {
    renderDiff({
      diff: {
        ...diff,
        objective_before: null,
        objective_delta: null,
        promo_cost_delta: 5000,
      },
    });

    const totals = screen.getByRole("table", { name: "Plan totals" });
    expect(
      within(totals).getByRole("row", { name: /^Objective/ }),
    ).toHaveTextContent("—₹9,800—");
    expect(
      within(totals).getByRole("row", { name: /^Promo cost/ }),
    ).toHaveTextContent("+₹5,000");
  });

  it("lists the added, removed and changed plan lines, and counts the rest", () => {
    renderDiff();

    const added = screen.getByRole("table", { name: "Added plan lines" });
    expect(within(added).getAllByRole("row")).toHaveLength(2);
    expect(
      within(added).getByRole("row", { name: /SKU0020/ }),
    ).toHaveTextContent(
      "SKU0020North% off10%W1053 wkAll customers₹4,500₹2,600",
    );
    const removed = screen.getByRole("table", { name: "Removed plan lines" });
    expect(
      within(removed).getByRole("row", { name: /SKU0011/ }),
    ).toHaveTextContent("SKU0011West");
    const changed = screen.getByRole("table", { name: "Changed plan lines" });
    expect(
      within(changed).getByRole("row", { name: /SKU0003/ }),
    ).toHaveTextContent("SKU0003NorthDepth 20% → 15%");
    expect(screen.getByText("1 plan line unchanged.")).toBeInTheDocument();
  });

  it("gives every decision number in the line tables its tool", () => {
    renderDiff();

    const changed = screen.getByRole("table", { name: "Changed plan lines" });
    expect(within(changed).getByText("15%")).toHaveAttribute(
      "title",
      expect.stringMatching(/^Source: run_optimizer/),
    );
    const added = screen.getByRole("table", { name: "Added plan lines" });
    expect(within(added).getByText("₹2,600")).toHaveAttribute(
      "title",
      expect.stringMatching(/^Source: generate_candidates/),
    );
  });

  it("shows every changed field of a line, a bundle partner included", () => {
    const [change] = diff.changed;
    renderDiff({
      diff: {
        ...diff,
        changed: [
          {
            ...change,
            fields: ["mechanism", "bundle_partner_sku_id", "target_segment"],
            after: {
              ...change.after,
              line: {
                ...change.after.line,
                mechanism: "BUNDLE",
                bundle_partner_sku_id: "SKU0042",
                target_segment: "Families",
              },
            },
          },
        ],
      },
    });

    const row = within(
      screen.getByRole("table", { name: "Changed plan lines" }),
    ).getByRole("row", { name: /SKU0003/ });
    expect(row).toHaveTextContent("Mechanism % off → Bundle");
    expect(row).toHaveTextContent("Bundle partner none → SKU0042");
    expect(row).toHaveTextContent("Target segment All customers → Families");
  });

  it("says so when no plan line changed", () => {
    renderDiff({
      diff: { ...diff, added: [], removed: [], changed: [], unchanged: 3 },
    });

    expect(screen.getByText("No plan line changed.")).toBeInTheDocument();
    expect(screen.getByText("3 plan lines unchanged.")).toBeInTheDocument();
    expect(
      screen.queryByRole("table", { name: "Added plan lines" }),
    ).not.toBeInTheDocument();
  });

  it("works without the amendment or the explanation", () => {
    renderDiff({ amendment: undefined, explanation: null });

    expect(
      screen.getByRole("region", { name: "What changed from plan revision 1" }),
    ).not.toHaveTextContent("After your amendment");
    expect(screen.getByRole("table", { name: "Plan totals" })).toBeVisible();
  });
});
