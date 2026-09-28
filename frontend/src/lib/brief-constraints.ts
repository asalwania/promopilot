import { z } from "zod";

import type { components } from "@/lib/api/schema";

// The home page's optional constraint form (ADR 0058). The API takes a brief only
// (SPEC §10), so each constraint set here becomes one plain sentence after the brief,
// worded so that both the Context agent's LLM reading and its rules fallback read it
// (ADR 0048, ADR 0053). Nothing is computed here: the numbers go out as typed.

type Region = components["schemas"]["Region"];

export const REGIONS: readonly Region[] = ["North", "South", "East", "West"];

// The synthetic world's categories, in catalogue order (datagen/config.yaml).
export const CATEGORIES = [
  "Snacks",
  "Beverages",
  "Dairy",
  "Personal Care",
  "Home Care",
  "Staples",
  "Frozen",
  "Bakery",
] as const;

// Holidays in the calendar (datagen/config.yaml): each one names its promo weeks.
export const HOLIDAYS = [
  "Diwali",
  "Christmas",
  "New Year",
  "Holi",
  "Eid",
] as const;

export const BUDGET_MAX_LAKH = 1000;
export const MIN_MARGIN_MAX_PCT = 60;
export const CLEARANCE_PRODUCT_MAX_CHARS = 80;

/** The form's raw values: text inputs as typed, ticked boxes and the chosen holiday. */
export type ConstraintValues = {
  budgetLakh: string;
  minMarginPct: string;
  regions: Region[];
  categories: string[];
  holiday: string;
  clearanceProduct: string;
  clearancePct: string;
};

export const EMPTY_CONSTRAINTS: ConstraintValues = {
  budgetLakh: "",
  minMarginPct: "",
  regions: [],
  categories: [],
  holiday: "",
  clearanceProduct: "",
  clearancePct: "",
};

export type Constraints = {
  budgetLakh?: number;
  minMarginPct?: number;
  regions: Region[];
  categories: string[];
  holiday?: (typeof HOLIDAYS)[number];
  clearance?: { product: string; pct: number };
};

export type ConstraintErrors = Partial<Record<keyof ConstraintValues, string>>;

export type ConstraintsResult =
  { ok: true; value: Constraints } | { ok: false; errors: ConstraintErrors };

// A blank input is unset; anything else must be a number that `problem` accepts.
function optionalNumber(problem: (value: number) => string | null) {
  return z
    .string()
    .trim()
    .transform((text, ctx) => {
      if (text === "") return undefined;
      // Not a number is NaN, which every range check rejects.
      const value = Number(text);
      const message = problem(value);
      if (message !== null) {
        ctx.addIssue({ code: "custom", message });
        return z.NEVER;
      }
      return value;
    });
}

const BUDGET_TOO_LOW = "Enter a budget above ₹0.";
const MARGIN_RANGE = `Enter a margin from 0% to ${MIN_MARGIN_MAX_PCT}%.`;
const CLEARANCE_RANGE = "Enter a sell-through from 1% to 100%.";

const constraintsSchema = z.object({
  budgetLakh: optionalNumber((lakh) => {
    if (!(lakh > 0)) return BUDGET_TOO_LOW;
    if (lakh > BUDGET_MAX_LAKH)
      return `Enter a budget of at most ₹${BUDGET_MAX_LAKH} lakh.`;
    return null;
  }),
  minMarginPct: optionalNumber((pct) =>
    pct >= 0 && pct <= MIN_MARGIN_MAX_PCT ? null : MARGIN_RANGE,
  ),
  regions: z.array(z.enum(REGIONS as [Region, ...Region[]])),
  categories: z.array(z.enum(CATEGORIES)),
  holiday: z.union([z.enum(HOLIDAYS), z.literal("")]),
  clearanceProduct: z
    .string()
    .trim()
    .max(CLEARANCE_PRODUCT_MAX_CHARS, {
      message: `Keep the product to ${CLEARANCE_PRODUCT_MAX_CHARS} characters.`,
    }),
  clearancePct: optionalNumber((pct) =>
    pct >= 1 && pct <= 100 ? null : CLEARANCE_RANGE,
  ),
});

/** Checks the form and returns the constraints it sets, or one message per bad field. */
export function validateConstraints(
  values: ConstraintValues,
): ConstraintsResult {
  const parsed = constraintsSchema.safeParse(values);
  const errors: ConstraintErrors = {};
  for (const issue of parsed.error?.issues ?? []) {
    const field = issue.path[0] as keyof ConstraintValues;
    errors[field] ??= issue.message;
  }
  // A clearance target needs both halves; checked apart from the schema so that it
  // shows alongside any other field's error.
  const product = values.clearanceProduct.trim() !== "";
  const pct = values.clearancePct.trim() !== "";
  if (pct && !product) errors.clearanceProduct ??= "Name the product to clear.";
  if (product && !pct) errors.clearancePct ??= CLEARANCE_RANGE;
  if (!parsed.success || Object.keys(errors).length > 0) {
    return { ok: false, errors };
  }
  const form = parsed.data;
  const value: Constraints = {
    regions: REGIONS.filter((region) => form.regions.includes(region)),
    categories: CATEGORIES.filter((category) =>
      form.categories.includes(category),
    ),
  };
  if (form.budgetLakh !== undefined) value.budgetLakh = form.budgetLakh;
  if (form.minMarginPct !== undefined) value.minMarginPct = form.minMarginPct;
  if (form.holiday !== "") value.holiday = form.holiday;
  if (form.clearancePct !== undefined && form.clearanceProduct !== "") {
    value.clearance = {
      product: form.clearanceProduct,
      pct: form.clearancePct,
    };
  }
  return { ok: true, value };
}

function listed(names: readonly string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

/** The text sent as the brief: the brief, then one sentence per constraint set. */
export function composeBrief(brief: string, constraints: Constraints): string {
  const sentences: string[] = [];
  if (constraints.budgetLakh !== undefined) {
    sentences.push(`Marketing budget ₹${constraints.budgetLakh} lakh.`);
  }
  if (constraints.minMarginPct !== undefined) {
    sentences.push(`Keep margin above ${constraints.minMarginPct}%.`);
  }
  if (constraints.regions.length > 0) {
    sentences.push(`Regions: ${listed(constraints.regions)}.`);
  }
  if (constraints.categories.length > 0) {
    sentences.push(`Categories: ${listed(constraints.categories)}.`);
  }
  if (constraints.holiday !== undefined) {
    sentences.push(`Run it for ${constraints.holiday}.`);
  }
  if (constraints.clearance !== undefined) {
    const { product, pct } = constraints.clearance;
    sentences.push(`Clear at least ${pct}% of ${product} stock.`);
  }
  const text = brief.trim();
  if (sentences.length === 0) return text;
  return `${text}\n\nConstraints: ${sentences.join(" ")}`;
}
