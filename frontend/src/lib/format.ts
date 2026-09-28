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

const LAKH = 100_000;
const CRORE = 10_000_000;
const indianWhole = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0,
});
const croreFormat = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

// Money as the Explainer cites it (ADR 0050 D2, guardrails' format_rupees):
// whole rupees below ₹1 lakh, then lakh or crore to at most two decimals,
// e.g. ₹18,250, ₹1.72 lakh, ₹1.25 crore. The plan area shows money this way,
// so a table figure reads as the rationale next to it does (ADR 0060).
export function formatMoney(amount: number): string {
  const size = Math.abs(amount);
  let shown: string;
  if (Math.round(size) < LAKH) {
    shown = indianWhole.format(Math.round(size));
  } else if (Number((size / LAKH).toFixed(2)) < CRORE / LAKH) {
    shown = `${trimmed((size / LAKH).toFixed(2))} lakh`;
  } else {
    shown = `${trimmed(croreFormat.format(size / CRORE))} crore`;
  }
  return `${sign(amount, shown)}₹${shown}`;
}

// A fraction as a percentage to at most one decimal, e.g. 0.2237 is 22.4%.
export function formatShare(fraction: number): string {
  const shown = trimmed((Math.abs(fraction) * 100).toFixed(1));
  return `${sign(fraction, shown)}${shown}%`;
}

// An uplift already in percent, signed, e.g. +62.5% or -12.3%.
export function formatUplift(pct: number): string {
  const shown = trimmed(Math.abs(pct).toFixed(1));
  const signed = sign(pct, shown) || (/[1-9]/.test(shown) ? "+" : "");
  return `${signed}${shown}%`;
}

// Drop trailing zeros after the point: a shorter number only widens its rounding.
function trimmed(number: string): string {
  return number.includes(".") ? number.replace(/\.?0+$/, "") : number;
}

function sign(value: number, shown: string): string {
  return value < 0 && /[1-9]/.test(shown) ? "-" : "";
}

export function formatWeek(weekId: number): string {
  return `W${weekId}`;
}

const dateTimeFormat = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
});

// In the browser's time zone, e.g. "26 Sept 2026, 12:00 pm".
export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso));
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

const priceFormat = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

// Shelf prices keep their paise: ₹94.90 against ₹95 is the gap a shopper sees.
export function formatPrice(amount: number): string {
  return priceFormat.format(amount);
}

const tokenFormat = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0,
});

// LLM token counts, grouped the Indian way, e.g. 12,34,567.
export function formatTokens(count: number): string {
  return tokenFormat.format(count);
}

const usdFormat = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

// LLM cost in dollars: a session costs cents, so four decimals, e.g. $0.5081.
export function formatUsd(amount: number): string {
  return usdFormat.format(amount);
}

// How long a graph node ran, e.g. "300 ms", "42.0 s" or "2 min 5 s".
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

const clockFormat = new Intl.DateTimeFormat("en-IN", { timeStyle: "medium" });

// The time of day in the browser's time zone, e.g. "3:30:05 pm".
export function formatClockTime(iso: string): string {
  return clockFormat.format(new Date(iso));
}
