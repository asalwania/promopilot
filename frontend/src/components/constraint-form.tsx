"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  CATEGORIES,
  CLEARANCE_PRODUCT_MAX_CHARS,
  HOLIDAYS,
  REGIONS,
  type ConstraintErrors,
  type ConstraintValues,
} from "@/lib/brief-constraints";

type Props = {
  values: ConstraintValues;
  errors: ConstraintErrors;
  onChange: (field: keyof ConstraintValues, values: ConstraintValues) => void;
};

type TextField =
  "budgetLakh" | "minMarginPct" | "clearanceProduct" | "clearancePct";

// The optional constraints next to the brief (SPEC §11, ADR 0058). A controlled
// fieldset: the composer owns the values, validates them and adds them to the brief.
export function ConstraintForm({ values, errors, onChange }: Props) {
  function set<K extends keyof ConstraintValues>(
    field: K,
    value: ConstraintValues[K],
  ) {
    onChange(field, { ...values, [field]: value });
  }

  function toggle(field: "regions" | "categories", name: string) {
    const current: string[] = values[field];
    const next = current.includes(name)
      ? current.filter((item) => item !== name)
      : [...current, name];
    set(field, next as ConstraintValues[typeof field]);
  }

  function textInput(
    field: TextField,
    label: string,
    props: React.ComponentProps<"input"> = {},
  ) {
    const id = `constraint-${field}`;
    const error = errors[field];
    return (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id}>{label}</Label>
        <Input
          id={id}
          type="text"
          value={values[field]}
          onChange={(event) => set(field, event.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          {...props}
        />
        {error && (
          <p id={`${id}-error`} className="text-destructive text-xs">
            {error}
          </p>
        )}
      </div>
    );
  }

  function checkboxes(
    field: "regions" | "categories",
    legend: string,
    names: readonly string[],
  ) {
    const chosen: string[] = values[field];
    return (
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">{legend}</legend>
        <div className="grid grid-cols-2 gap-x-3 gap-y-2">
          {names.map((name) => (
            <Label key={name} className="font-normal">
              <Checkbox
                checked={chosen.includes(name)}
                onCheckedChange={() => toggle(field, name)}
              />
              {name}
            </Label>
          ))}
        </div>
      </fieldset>
    );
  }

  return (
    <fieldset className="flex flex-col gap-4">
      <legend className="mb-2 text-sm font-semibold">
        Constraints (optional)
      </legend>
      {textInput("budgetLakh", "Marketing budget (₹ lakh)", {
        inputMode: "decimal",
        placeholder: "e.g. 8",
      })}
      {textInput("minMarginPct", "Minimum margin (%)", {
        inputMode: "decimal",
        placeholder: "e.g. 18",
      })}
      {checkboxes("regions", "Regions", REGIONS)}
      {checkboxes("categories", "Categories", CATEGORIES)}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="constraint-holiday">Promo window</Label>
        <select
          id="constraint-holiday"
          value={values.holiday}
          onChange={(event) => set("holiday", event.target.value)}
          className="border-input focus-visible:border-ring focus-visible:ring-ring/50 dark:bg-input/30 h-8 rounded-lg border bg-transparent px-2 text-sm outline-none focus-visible:ring-3"
        >
          <option value="">Let the agent choose</option>
          {HOLIDAYS.map((holiday) => (
            <option key={holiday} value={holiday}>
              {holiday}
            </option>
          ))}
        </select>
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">Clearance target</legend>
        {textInput("clearanceProduct", "Product to clear", {
          maxLength: CLEARANCE_PRODUCT_MAX_CHARS,
          placeholder: "e.g. 400g namkeen",
        })}
        {textInput("clearancePct", "Sell-through (%)", {
          inputMode: "decimal",
          placeholder: "e.g. 60",
        })}
      </fieldset>
      <p className="text-muted-foreground text-xs">
        Constraints are added to your brief. Without an API key, only the
        example briefs replay exactly; other briefs still plan, with rule-based
        reading.
      </p>
    </fieldset>
  );
}
