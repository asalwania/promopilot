import { formatRupees } from "@/lib/format";
import { SOURCES } from "@/lib/sources";
import { cn } from "@/lib/utils";

// One SKU a plan line moves in its region, as the relations calculators return it
// (ADR 0033): units_change_pct of its baseline over the promo weeks, profit_change in rupees.
export type CrossEffect = {
  sku_id: string;
  units_change_pct: number;
  profit_change: number;
};

// Effects smaller than 1% of the SKU's units are noise to a manager; the top 3 by profit
// are listed and the rest counted (ADR 0033).
const MIN_PCT = 1;
const SHOWN = 3;

type CalloutProps = { promoted: string; effects: CrossEffect[] };

export function CannibalisationCallout({ promoted, effects }: CalloutProps) {
  return (
    <Callout
      title="Cannibalisation"
      tone="border-amber-500/40 bg-amber-500/5"
      effects={effects.filter((effect) => effect.units_change_pct <= -MIN_PCT)}
      describe={(effect) =>
        `Promoting ${promoted} reduces ${effect.sku_id}'s units by ${percent(effect)} ` +
        `(−${formatRupees(Math.abs(effect.profit_change))} profit)`
      }
    />
  );
}

export function HaloCallout({ promoted, effects }: CalloutProps) {
  return (
    <Callout
      title="Halo"
      tone="border-emerald-500/40 bg-emerald-500/5"
      effects={effects.filter((effect) => effect.units_change_pct >= MIN_PCT)}
      describe={(effect) =>
        `Promoting ${promoted} lifts ${effect.sku_id}'s units by ${percent(effect)} ` +
        `(+${formatRupees(Math.abs(effect.profit_change))} profit)`
      }
    />
  );
}

function Callout({
  title,
  tone,
  effects,
  describe,
}: {
  title: string;
  tone: string;
  effects: CrossEffect[];
  describe: (effect: CrossEffect) => string;
}) {
  if (effects.length === 0) return null;
  const ranked = [...effects].sort(
    (a, b) => Math.abs(b.profit_change) - Math.abs(a.profit_change),
  );
  const hidden = ranked.length - SHOWN;
  return (
    <section
      aria-label={title}
      className={cn("rounded-lg border px-3 py-2 text-sm", tone)}
    >
      <h3 className="font-medium">{title}</h3>
      <ul className="mt-1 space-y-0.5">
        {ranked.slice(0, SHOWN).map((effect) => (
          <li
            key={effect.sku_id}
            title={`Source: ${SOURCES.crossEffects} · relations model`}
          >
            {describe(effect)}
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <p className="text-muted-foreground mt-1">+{hidden} more</p>
      )}
    </section>
  );
}

function percent(effect: CrossEffect): string {
  return `${Math.round(Math.abs(effect.units_change_pct))}%`;
}
