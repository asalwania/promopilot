import type { PlanningRequest, PlanRevision } from "@/lib/api/sessions";
import { formatBasisPoints, formatMoney, formatPrice } from "@/lib/format";

type BindingConstraint = PlanRevision["binding_constraints"][number];
export type ConstraintKind = BindingConstraint["kind"];
type OpenIssue = PlanRevision["open_issues"][number];
export type Violation = Extract<OpenIssue, { kind: "violation" }>;
type ViolationCode = Violation["code"];

// What a constraint is called, scoped to its SKU, region or category when it has one
// (ADR 0038, ADR 0044).
export function constraintLabel(constraint: {
  kind: ConstraintKind;
  sku_id?: string | null;
  region?: string | null;
  category?: string | null;
}): string {
  const inRegion = constraint.region ? ` in ${constraint.region}` : "";
  switch (constraint.kind) {
    case "marketing_budget":
      return "Marketing budget";
    case "regional_budget":
      return `Budget cap${inRegion}`;
    case "minimum_margin":
      return "Minimum margin";
    case "margin_floor":
      return "Company-policy margin floor";
    case "max_promoted_skus":
      return constraint.category
        ? `Promoted ${constraint.category} SKUs${inRegion}`
        : `Promoted SKUs per category and region${inRegion}`;
    case "kvi_price_tolerance":
      return "KVI price tolerance";
    case "clearance_target":
      return `Clearance target for ${constraint.sku_id ?? "a SKU"}${inRegion}`;
    case "strong_substitutes":
      return "Strong substitutes kept apart";
  }
}

const MONEY: ReadonlySet<ConstraintKind> = new Set([
  "marketing_budget",
  "regional_budget",
]);

// A constraint's value as its kind reads: rupees for a budget, a SKU count for the
// promoted-SKU cap, the least estimated θ of a strong substitute pair (ADR 0075), and a
// share, to a basis point, for the rest.
export function formatConstraintValue(
  kind: ConstraintKind,
  value: number,
): string {
  if (MONEY.has(kind)) return formatMoney(value);
  if (kind === "max_promoted_skus") return String(value);
  if (kind === "strong_substitutes") return `θ ≥ ${value.toFixed(2)}`;
  return formatBasisPoints(value);
}

// The exact value behind a rounded budget, for its tooltip; none for the rest.
export function exactConstraintValue(
  kind: ConstraintKind,
  value: number,
): string | undefined {
  return MONEY.has(kind) ? `exactly ${formatPrice(value)}` : undefined;
}

export const CHECKS = [
  "Budget",
  "Minimum margin",
  "Stock",
  "Clearance",
  "Policy",
] as const;
export type CheckName = (typeof CHECKS)[number];

// Every hard constraint validate_plan checks (ADR 0028) belongs to one checklist row.
const CHECK_OF: Record<ViolationCode, CheckName> = {
  BUDGET: "Budget",
  REGIONAL_BUDGET: "Budget",
  MIN_MARGIN: "Minimum margin",
  MARGIN_FLOOR: "Minimum margin",
  STOCK: "Stock",
  CLEARANCE_TARGET: "Clearance",
  MAX_DISCOUNT: "Policy",
  BELOW_COST: "Policy",
  WINDOW: "Policy",
  MAX_SKUS: "Policy",
  KVI_TOLERANCE: "Policy",
  STRONG_SUBSTITUTES: "Policy",
  DUPLICATE_LINE: "Policy",
};

export type CheckResult = "pass" | "fail" | "not_set";

export type ConstraintCheck = {
  name: CheckName;
  result: CheckResult;
  // The row's broken constraints, as validate_plan wrote them.
  violations: Violation[];
};

// The checklist from what is stored, computing nothing (ADR 0067): the Critic keeps every
// violation validate_plan finds on the revision it hands on (ADR 0051), so a row fails when
// one of its violations is open and passes otherwise. Clearance also fails on the
// optimiser's shortfalls, and is not set when the brief names no target.
export function constraintChecks(
  revision: PlanRevision,
  request: PlanningRequest | null,
): ConstraintCheck[] {
  const violations = revision.open_issues.filter(
    (issue): issue is Violation => issue.kind === "violation",
  );
  return CHECKS.map((name) => {
    const broken = violations.filter(
      (violation) => CHECK_OF[violation.code] === name,
    );
    let result: CheckResult = broken.length > 0 ? "fail" : "pass";
    if (name === "Clearance") {
      if (revision.clearance_shortfalls.length > 0) result = "fail";
      else if (
        result === "pass" &&
        (request?.clearance_targets.length ?? 0) === 0
      )
        result = "not_set";
    }
    return { name, result, violations: broken };
  });
}
