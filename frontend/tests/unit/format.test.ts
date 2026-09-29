import { describe, expect, it } from "vitest";

import {
  formatBasisPoints,
  formatMoney,
  formatShare,
  formatUplift,
} from "@/lib/format";

describe("formatMoney", () => {
  // The Explainer's formats (ADR 0050 D2), so the table reads as the rationales do.
  it.each([
    [0, "₹0"],
    [18250, "₹18,250"],
    [-13812.5, "-₹13,813"],
    [99_999.4, "₹99,999"],
    [99_999.6, "₹1 lakh"],
    [100_000, "₹1 lakh"],
    [171_845, "₹1.72 lakh"],
    [-123_456.4, "-₹1.23 lakh"],
    [210_000, "₹2.1 lakh"],
    [9_999_999, "₹1 crore"],
    [12_500_000, "₹1.25 crore"],
    [12_345_678_900, "₹1,234.57 crore"],
    [-0.2, "₹0"],
  ])("shows %d as %s", (amount, shown) => {
    expect(formatMoney(amount)).toBe(shown);
  });
});

describe("formatShare", () => {
  it.each([
    [0.31, "31%"],
    [0.2237, "22.4%"],
    [0, "0%"],
    [1, "100%"],
  ])("shows the fraction %d as %s", (fraction, shown) => {
    expect(formatShare(fraction)).toBe(shown);
  });
});

describe("formatBasisPoints", () => {
  // A relaxation is exact to a basis point (ADR 0044).
  it.each([
    [0.5993, "59.93%"],
    [0.6, "60%"],
    [0.7027, "70.27%"],
    [0.03, "3%"],
  ])("shows the fraction %d as %s", (fraction, shown) => {
    expect(formatBasisPoints(fraction)).toBe(shown);
  });
});

describe("formatUplift", () => {
  it.each([
    [62.5, "+62.5%"],
    [40, "+40%"],
    [-12.34, "-12.3%"],
    [0.01, "0%"],
  ])("shows %d percent as %s", (pct, shown) => {
    expect(formatUplift(pct)).toBe(shown);
  });
});
