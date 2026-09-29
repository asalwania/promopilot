"use client";

import { useId, useState } from "react";

import { type ActionOutcome } from "@/components/amend-box";
import { SourcedNumber } from "@/components/sourced-number";
import { Button } from "@/components/ui/button";
import type { PlanRevision } from "@/lib/api/sessions";
import {
  constraintLabel,
  exactConstraintValue,
  formatConstraintValue,
  type ConstraintKind,
} from "@/lib/constraints";
import { formatShare } from "@/lib/format";
import { SOURCES } from "@/lib/sources";

type Relaxation = NonNullable<PlanRevision["relaxation"]>;

// Accepts the revision's relaxation as an amendment (ADR 0052 D7): SessionDetails
// calls `actions.amend({ acceptRelaxation: true })` (ADR 0066).
export type AcceptRelaxation = () => Promise<ActionOutcome>;

// Whether the revision needs the panel: an infeasible request, or one whose solve ran
// out of time with a shortfall and so carries an unproven relaxation (ADR 0044).
export function needsRelaxation(revision: PlanRevision): boolean {
  return revision.solver_status === "INFEASIBLE" || revision.relaxation != null;
}

// Why no plan reaches every clearance target, and the smallest change to the brief that
// would, with a one-click amend that accepts it (AG-06, ADR 0044, ADR 0067).
export function InfeasibilityPanel({
  revision,
  canAccept,
  onAcceptRelaxation,
}: {
  revision: PlanRevision;
  // Only a session paused at approval can be amended (ADR 0052 D1).
  canAccept: boolean;
  onAcceptRelaxation: AcceptRelaxation;
}) {
  const titleId = useId();
  const infeasible = revision.solver_status === "INFEASIBLE";
  const binding = revision.binding_constraints.filter(
    (constraint) => constraint.evidence === "infeasible",
  );
  const relaxation = revision.relaxation;
  return (
    <section
      aria-labelledby={titleId}
      className="border-destructive/40 flex flex-col gap-3 rounded-lg border p-3"
    >
      <p id={titleId} role="alert" className="text-destructive text-sm">
        {infeasible
          ? "Infeasible: no plan reaches every clearance target within the brief's constraints."
          : "Not proven feasible: the plan misses a clearance target, and the solver ran out of time before settling whether any plan reaches it."}
      </p>
      {revision.clearance_shortfalls.length > 0 && (
        <ShortfallTable revision={revision} />
      )}
      {binding.length > 0 && (
        <div className="flex flex-col gap-1 text-sm">
          <h3 className="font-medium">Binding constraints</h3>
          <ul aria-label="Binding constraints" className="list-disc pl-5">
            {binding.map((constraint, index) => (
              <li key={index}>
                {constraintLabel(constraint)}:{" "}
                <Value kind={constraint.kind} value={constraint.limit} /> (
                {constraint.source === "brief" ? "brief" : "company policy"})
              </li>
            ))}
          </ul>
        </div>
      )}
      {relaxation && relaxation.changes.length > 0 && (
        <RelaxationTable relaxation={relaxation} />
      )}
      {relaxation?.policy_binds && (
        <p role="note" className="text-sm">
          Company policy binds: no change to the budget, caps, minimum margin or
          KVI price tolerance alone reaches every clearance target, so a target
          must come down.
        </p>
      )}
      {relaxation && !relaxation.proven && (
        <p role="note" className="text-muted-foreground text-sm">
          Not proven smallest: the solver ran out of time, so a smaller change
          may exist.
        </p>
      )}
      {canAccept && relaxation && relaxation.changes.length > 0 && (
        <AcceptButton onAccept={onAcceptRelaxation} />
      )}
    </section>
  );
}

function AcceptButton({ onAccept }: { onAccept: AcceptRelaxation }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accept = async () => {
    setPending(true);
    setError(null);
    const outcome = await onAccept();
    setPending(false);
    if (!outcome.ok) setError(outcome.reason);
  };
  return (
    <div className="flex flex-col items-start gap-2">
      {/* One click, no confirmation: re-planning keeps this revision (ADR 0067). */}
      <Button disabled={pending} onClick={accept}>
        {pending
          ? "Accepting the relaxation…"
          : "Accept the relaxation and re-plan"}
      </Button>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          Couldn&apos;t accept the relaxation: {error}
        </p>
      )}
    </div>
  );
}

function Value({ kind, value }: { kind: ConstraintKind; value: number }) {
  return (
    <SourcedNumber
      value={value}
      format={(n) => formatConstraintValue(kind, n)}
      source={SOURCES.relaxation}
      detail={exactConstraintValue(kind, value)}
    />
  );
}

function Header({ columns }: { columns: string[] }) {
  return (
    <thead>
      <tr className="border-b">
        {columns.map((heading) => (
          <th
            key={heading}
            scope="col"
            className="text-muted-foreground px-2 py-2 text-left font-medium"
          >
            {heading}
          </th>
        ))}
      </tr>
    </thead>
  );
}

function ShortfallTable({ revision }: { revision: PlanRevision }) {
  const share = (value: number) => (
    <SourcedNumber
      value={value}
      format={formatShare}
      source={SOURCES.relaxation}
    />
  );
  return (
    <table aria-label="Clearance shortfalls" className="w-full text-sm">
      <Header
        columns={[
          "SKU",
          "Region",
          "Target",
          "Expected sell-through",
          "Units short",
        ]}
      />
      <tbody>
        {revision.clearance_shortfalls.map((shortfall) => (
          <tr
            key={`${shortfall.sku_id}-${shortfall.region}`}
            className="border-b"
          >
            <th scope="row" className="px-2 py-2 text-left font-medium">
              {shortfall.sku_id}
            </th>
            <td className="px-2 py-2">{shortfall.region}</td>
            <td className="px-2 py-2">{share(shortfall.target)}</td>
            <td className="px-2 py-2">
              {share(shortfall.expected_sell_through)}
            </td>
            <td className="px-2 py-2">
              <SourcedNumber
                value={shortfall.shortfall_units}
                format={(units) => Math.round(units).toLocaleString("en-IN")}
                source={SOURCES.relaxation}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// A dropped constraint has no value: a clearance target is dropped, a tolerance off.
function Relaxed({ change }: { change: Relaxation["changes"][number] }) {
  if (change.relaxed == null) {
    return <>{change.kind === "kvi_price_tolerance" ? "Off" : "Dropped"}</>;
  }
  return <Value kind={change.kind} value={change.relaxed} />;
}

function RelaxationTable({ relaxation }: { relaxation: Relaxation }) {
  return (
    <div className="flex flex-col gap-1 text-sm">
      <h3 className="font-medium">Proposed relaxation</h3>
      <table aria-label="Proposed relaxation" className="w-full text-sm">
        <Header
          columns={[
            "Constraint",
            "Brief value",
            "Relaxed to",
            "Change",
            "Policy allows",
          ]}
        />
        <tbody>
          {relaxation.changes.map((change, index) => (
            <tr key={index} className="border-b">
              <th scope="row" className="px-2 py-2 text-left font-medium">
                {constraintLabel(change)}
              </th>
              <td className="px-2 py-2">
                <Value kind={change.kind} value={change.current} />
              </td>
              <td className="px-2 py-2">
                <Relaxed change={change} />
              </td>
              <td className="px-2 py-2">
                <SourcedNumber
                  value={change.change}
                  format={formatShare}
                  source={SOURCES.relaxation}
                  detail="the change as a share of the brief's value"
                />
              </td>
              <td className="px-2 py-2">
                {change.policy_allows != null ? (
                  <Value kind={change.kind} value={change.policy_allows} />
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
