const defaultFormat = new Intl.NumberFormat("en-IN");

export type SourcedNumberProps = {
  value: number;
  // Defaults to an en-IN number, e.g. 1,200.
  format?: (value: number) => string;
  // The deterministic tool the number came from, e.g. `get_inventory_status`.
  source: string;
  // What else the reader needs to trust it, e.g. "stock at end of W104".
  detail?: string;
};

// Every number the UI shows names the tool it came from (SPEC §11 UX rule).
// A native tooltip keeps long tables light; the plan table reuses this (#60).
export function SourcedNumber({
  value,
  format = (n) => defaultFormat.format(n),
  source,
  detail,
}: SourcedNumberProps) {
  const tooltip = detail
    ? `Source: ${source} · ${detail}`
    : `Source: ${source}`;
  return (
    <span
      title={tooltip}
      className="cursor-help tabular-nums underline decoration-dotted decoration-1 underline-offset-4"
    >
      {format(value)}
    </span>
  );
}
