import type { PlanRevisionLine } from "@/lib/api/sessions";

type Mechanism = PlanRevisionLine["line"]["mechanism"];

const rupeeFormat = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

// Money is float rupees everywhere outside CP-SAT (ADR 0015).
export function formatRupees(amount: number): string {
  return rupeeFormat.format(amount);
}

export function formatWeek(weekId: number): string {
  return `W${weekId}`;
}

const MECHANISM_LABELS: Record<Mechanism, string> = {
  PCT_OFF: "% off",
  BOGO: "Buy one get one",
  BUNDLE: "Bundle",
  FIXED_PRICE: "Fixed price",
};

export function formatMechanism(mechanism: Mechanism): string {
  return MECHANISM_LABELS[mechanism];
}
