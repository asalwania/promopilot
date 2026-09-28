import { describe, expect, it } from "vitest";

import {
  composeBrief,
  EMPTY_CONSTRAINTS,
  validateConstraints,
  type ConstraintValues,
} from "@/lib/brief-constraints";

function values(overrides: Partial<ConstraintValues>): ConstraintValues {
  return { ...EMPTY_CONSTRAINTS, ...overrides };
}

describe("composeBrief", () => {
  it("sends the brief alone when no constraint is set", () => {
    expect(
      composeBrief("  Diwali push for Snacks  ", {
        regions: [],
        categories: [],
      }),
    ).toBe("Diwali push for Snacks");
  });

  it("adds every set constraint as a sentence the Context agent reads", () => {
    const constraints = validateConstraints(
      values({
        budgetLakh: "8",
        minMarginPct: "18",
        regions: ["West", "North"],
        categories: ["Snacks", "Beverages"],
        holiday: "Diwali",
        clearanceProduct: "400g namkeen",
        clearancePct: "60",
      }),
    );
    expect(constraints.ok).toBe(true);
    if (!constraints.ok) return;

    expect(composeBrief("Target families.", constraints.value)).toBe(
      "Target families.\n\nConstraints: Marketing budget ₹8 lakh. " +
        "Keep margin above 18%. Regions: North and West. " +
        "Categories: Snacks and Beverages. Run it for Diwali. " +
        "Clear at least 60% of 400g namkeen stock.",
    );
  });

  it("lists three or more names with commas", () => {
    const constraints = validateConstraints(
      values({ regions: ["South", "East", "North"], budgetLakh: "2.5" }),
    );
    if (!constraints.ok) throw new Error("expected valid constraints");

    expect(composeBrief("Push", constraints.value)).toBe(
      "Push\n\nConstraints: Marketing budget ₹2.5 lakh. " +
        "Regions: North, South and East.",
    );
  });
});

describe("validateConstraints", () => {
  it("accepts an empty form", () => {
    expect(validateConstraints(EMPTY_CONSTRAINTS)).toEqual({
      ok: true,
      value: {
        regions: [],
        categories: [],
      },
    });
  });

  it.each([
    ["budgetLakh", "0", "Enter a budget above ₹0."],
    ["budgetLakh", "1001", "Enter a budget of at most ₹1000 lakh."],
    ["budgetLakh", "abc", "Enter a budget above ₹0."],
    ["minMarginPct", "-1", "Enter a margin from 0% to 60%."],
    ["minMarginPct", "61", "Enter a margin from 0% to 60%."],
  ] as const)("rejects %s = %s", (field, input, message) => {
    const result = validateConstraints(values({ [field]: input }));
    expect(result).toEqual({ ok: false, errors: { [field]: message } });
  });

  it("needs a product and a percentage together for a clearance target", () => {
    expect(validateConstraints(values({ clearancePct: "60" }))).toEqual({
      ok: false,
      errors: { clearanceProduct: "Name the product to clear." },
    });
    expect(
      validateConstraints(values({ clearanceProduct: "400g namkeen" })),
    ).toEqual({
      ok: false,
      errors: { clearancePct: "Enter a sell-through from 1% to 100%." },
    });
    expect(
      validateConstraints(
        values({ clearanceProduct: "400g namkeen", clearancePct: "101" }),
      ),
    ).toEqual({
      ok: false,
      errors: { clearancePct: "Enter a sell-through from 1% to 100%." },
    });
  });

  it("limits the clearance product to 80 characters", () => {
    const result = validateConstraints(
      values({ clearanceProduct: "x".repeat(81), clearancePct: "50" }),
    );
    expect(result).toEqual({
      ok: false,
      errors: { clearanceProduct: "Keep the product to 80 characters." },
    });
  });
});
