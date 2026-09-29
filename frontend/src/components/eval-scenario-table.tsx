"use client";

import { Fragment, useId, useState } from "react";

import { SourcedNumber } from "@/components/sourced-number";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { EvalRun, EvalScenario } from "@/lib/api/evals";
import { evalSource, humanise, scenarioGroupLabel } from "@/lib/eval-metrics";
import {
  formatDuration,
  formatMoney,
  formatPrice,
  formatShare,
  formatWeek,
} from "@/lib/format";
import { cn } from "@/lib/utils";

// Where a scenario's file lives, for the reader who wants its brief and
// expectations (ADR 0072). It reads main, which may be newer than the report.
const SCENARIO_URL =
  "https://github.com/asalwania/promopilot/blob/main/backend/evals/scenarios";

const ALL = "all";

const COLUMNS = [
  "Scenario",
  "Group",
  "Week",
  "Result",
  "Outcome",
  "Constraints",
  "Oracle breaches",
  "Properties",
  "Against the baseline",
  "Regret",
  "Session time",
  "Cost",
  "Warnings",
  "",
];

// One row per scenario, in report order, showing its last run; "Details" opens
// every run's trace as the report holds it (ADR 0072). Eval sessions live in
// memory only (ADR 0056 D3), so there is no `/sessions/[id]` to link to.
export function EvalScenarioTable({
  scenarios,
}: {
  scenarios: EvalScenario[];
}) {
  const id = useId();
  const [failedOnly, setFailedOnly] = useState(false);
  const [group, setGroup] = useState(ALL);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());

  const groups = [...new Set(scenarios.map((s) => s.group))].sort();
  const shown = scenarios.filter(
    (s) => (!failedOnly || !s.passed) && (group === ALL || s.group === group),
  );
  const toggle = (name: string) => {
    const next = new Set(open);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setOpen(next);
  };

  return (
    <div className="flex flex-col gap-3">
      <div
        role="group"
        aria-label="Filters"
        className="flex flex-wrap items-center gap-6 text-sm"
      >
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={failedOnly}
            onChange={(event) => setFailedOnly(event.target.checked)}
          />
          Failed only
        </label>
        <label htmlFor={`${id}-group`} className="flex items-center gap-2">
          Group
          <select
            id={`${id}-group`}
            className="border-input bg-background h-8 rounded-md border px-2 text-sm"
            value={group}
            onChange={(event) => setGroup(event.target.value)}
          >
            <option value={ALL}>All groups</option>
            {groups.map((slug) => (
              <option key={slug} value={slug}>
                {scenarioGroupLabel(slug)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="overflow-x-auto">
        <table aria-label="Scenarios" className="w-full text-sm">
          <thead>
            <tr className="border-b">
              {COLUMNS.map((column, index) => (
                <th
                  key={index}
                  scope="col"
                  className="text-muted-foreground px-2 py-2 text-left font-medium whitespace-nowrap"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((scenario) => {
              const expanded = open.has(scenario.name);
              const detailsId = `${id}-${scenario.name}`;
              return (
                <Fragment key={scenario.name}>
                  <ScenarioRow
                    scenario={scenario}
                    expanded={expanded}
                    detailsId={detailsId}
                    onToggle={() => toggle(scenario.name)}
                  />
                  {expanded && (
                    <tr id={detailsId} className="bg-muted/30 border-b">
                      <td colSpan={COLUMNS.length} className="px-4 py-3">
                        <ScenarioDetails scenario={scenario} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {shown.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No scenario matches these filters.
        </p>
      )}
    </div>
  );
}

function ScenarioRow({
  scenario,
  expanded,
  detailsId,
  onToggle,
}: {
  scenario: EvalScenario;
  expanded: boolean;
  detailsId: string;
  onToggle: () => void;
}) {
  const run = scenario.runs.at(-1);
  const cell = "px-2 py-2 whitespace-nowrap";
  return (
    <tr className="border-b align-top">
      <th scope="row" className={cn(cell, "text-left font-mono font-normal")}>
        {scenario.name}
      </th>
      <td className={cell}>{scenarioGroupLabel(scenario.group)}</td>
      <td className={cell}>{formatWeek(scenario.as_of_week)}</td>
      <td className={cell}>
        <PassBadge passed={scenario.passed} short />
      </td>
      {run ? <RunCells run={run} /> : <td colSpan={9} className={cell} />}
      <td className={cell}>
        <Button
          variant="outline"
          size="sm"
          aria-expanded={expanded}
          aria-controls={expanded ? detailsId : undefined}
          aria-label={`Details for ${scenario.name}`}
          onClick={onToggle}
        >
          {expanded ? "Hide" : "Details"}
        </Button>
      </td>
    </tr>
  );
}

function RunCells({ run }: { run: EvalRun }) {
  const cell = "px-2 py-2 whitespace-nowrap";
  const passedProperties = run.properties.filter((p) => p.passed).length;
  const regret = run.quality?.regret;
  const warnings = [
    run.fallbacks.length > 0 &&
      plural(run.fallbacks.length, "fallback", "fallbacks"),
    run.cassette_misses.length > 0 &&
      plural(run.cassette_misses.length, "cassette miss", "cassette misses"),
  ].filter((warning): warning is string => Boolean(warning));
  return (
    <>
      <td className={cell}>{humanise(run.outcome)}</td>
      <td className={cell}>{humanise(run.constraints)}</td>
      <td className="px-2 py-2">
        {run.oracle
          ? run.oracle.breaches.map(humanise).join(", ") || "none"
          : "—"}
      </td>
      <td className={cell}>
        {run.properties.length > 0
          ? `${passedProperties}/${run.properties.length}`
          : "—"}
      </td>
      <td className={cell}>{run.quality?.versus_rule_based ?? "—"}</td>
      <td className={cell}>
        {regret == null ? (
          "—"
        ) : (
          <SourcedNumber
            value={regret}
            format={formatShare}
            source={evalSource("regret")}
            detail="against the best plan on true parameters"
          />
        )}
      </td>
      <td className={cell}>
        <SourcedNumber
          value={run.session_s}
          format={(s) => formatDuration(s * 1000)}
          source={evalSource("session_latency_p50")}
          detail="this session's wall-clock time"
        />
      </td>
      <td className={cell}>
        <SourcedNumber
          value={run.usage.cost_inr}
          format={formatPrice}
          source={evalSource("session_cost_p50")}
          detail={`${run.usage.calls} LLM calls`}
        />
      </td>
      <td className="px-2 py-2">
        <div className="flex flex-wrap gap-1">
          {warnings.map((warning) => (
            <Badge
              key={warning}
              className="bg-amber-500/10 text-amber-700 dark:text-amber-400"
            >
              {warning}
            </Badge>
          ))}
        </div>
      </td>
    </>
  );
}

function ScenarioDetails({ scenario }: { scenario: EvalScenario }) {
  return (
    <div className="flex flex-col gap-4">
      {scenario.runs.map((run) => (
        <RunDetails key={run.run} name={scenario.name} run={run} />
      ))}
      <a
        href={`${SCENARIO_URL}/${scenario.name}.yaml`}
        target="_blank"
        rel="noreferrer"
        aria-label={`Scenario YAML: ${scenario.name}`}
        className="w-fit text-sm underline underline-offset-4"
      >
        Scenario YAML
      </a>
    </div>
  );
}

function RunDetails({ name, run }: { name: string; run: EvalRun }) {
  const label = `${name} run ${run.run}`;
  const quality = run.quality;
  return (
    <section aria-label={label} className="flex flex-col gap-2 text-sm">
      <div className="flex items-center gap-2">
        <h3 className="font-medium">Run {run.run}</h3>
        <PassBadge passed={run.passed} />
      </div>
      {run.error && <p className="text-destructive">{run.error}</p>}
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
        <dt className="text-muted-foreground">Route</dt>
        <dd>
          <ol
            aria-label="Route"
            className="flex flex-wrap gap-x-1 font-mono text-xs"
          >
            {run.route.map((node, index) => (
              <li key={index}>
                {index > 0 && <span aria-hidden>→ </span>}
                {node}
              </li>
            ))}
          </ol>
        </dd>
        <Entry term="Questions asked" items={run.questions_asked} mono />
        <dt className="text-muted-foreground">Amendments applied</dt>
        <dd>{run.amendments_applied}</dd>
        <Entry term="Flagged" items={run.flagged} mono />
        <Entry term="Fallbacks" items={run.fallbacks} mono />
        <Entry term="Cassette misses" items={run.cassette_misses} mono />
        <dt className="text-muted-foreground">Plan</dt>
        <dd>
          {run.revision
            ? `Revision ${run.revision.number}: ${run.revision.lines} lines, ${run.revision.solver_status ?? "no status"}`
            : "No final plan"}
        </dd>
        {quality && (
          <>
            <dt className="text-muted-foreground">Oracle objective</dt>
            <dd>
              Ours <Money value={quality.objective} /> · rule-based{" "}
              <Money value={quality.rule_based.objective} /> · best{" "}
              {quality.best.objective == null ? (
                "infeasible"
              ) : (
                <Money value={quality.best.objective} />
              )}
              {quality.regret_rupees != null && (
                <>
                  {" "}
                  · regret <Money value={quality.regret_rupees} />
                </>
              )}
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">Violations</dt>
        <dd>
          {run.violations.length === 0 ? (
            "None"
          ) : (
            <ul aria-label="Violations" className="list-disc pl-4">
              {run.violations.map((violation, index) => (
                <li key={index}>{violation.message}</li>
              ))}
            </ul>
          )}
        </dd>
        <dt className="text-muted-foreground">Properties</dt>
        <dd>
          {run.properties.length === 0 ? (
            "None expected"
          ) : (
            <ul aria-label="Properties" className="flex flex-col gap-0.5">
              {run.properties.map((property) => (
                <li key={property.property}>
                  <span
                    className={
                      property.passed ? "text-emerald-700" : "text-destructive"
                    }
                  >
                    {property.passed ? "✓" : "✗"}
                  </span>{" "}
                  <span className="font-mono text-xs">{property.property}</span>{" "}
                  <span className="text-muted-foreground">
                    ({property.detail})
                  </span>
                </li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
    </section>
  );
}

function Entry({
  term,
  items,
  mono = false,
}: {
  term: string;
  items: string[];
  mono?: boolean;
}) {
  return (
    <>
      <dt className="text-muted-foreground">{term}</dt>
      <dd>
        {items.length === 0 ? (
          "None"
        ) : (
          <ul
            aria-label={term}
            className={cn(
              "flex flex-wrap gap-x-3",
              mono && "font-mono text-xs",
            )}
          >
            {items.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        )}
      </dd>
    </>
  );
}

function Money({ value }: { value: number }) {
  return (
    <SourcedNumber
      value={value}
      format={formatMoney}
      source={evalSource("plan_quality")}
      detail="the oracle's incremental profit plus clearance value"
    />
  );
}

function PassBadge({
  passed,
  short = false,
}: {
  passed: boolean;
  short?: boolean;
}) {
  const text = short
    ? passed
      ? "Pass"
      : "Fail"
    : passed
      ? "Passed"
      : "Failed";
  return (
    <Badge
      className={
        passed
          ? "bg-emerald-600/10 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400"
          : "bg-destructive/10 text-destructive"
      }
    >
      {text}
    </Badge>
  );
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}
