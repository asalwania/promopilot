import { SourcedNumber } from "@/components/sourced-number";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { PlanningRequest, PlanRevision } from "@/lib/api/sessions";
import {
  constraintChecks,
  type CheckResult,
  type ConstraintCheck,
} from "@/lib/constraints";
import { formatMoney, formatShare } from "@/lib/format";
import { SOURCES } from "@/lib/sources";

const RESULT_BADGES: Record<
  CheckResult,
  { label: string; variant: "secondary" | "destructive" | "outline" }
> = {
  pass: { label: "Pass", variant: "secondary" },
  fail: { label: "Fail", variant: "destructive" },
  not_set: { label: "Not set", variant: "outline" },
};

// Pass or fail per constraint, so the manager can verify a plan at a glance (SPEC §11,
// ADR 0067). Every result is read from the revision: the UI computes nothing.
export function ConstraintChecklist({
  revision,
  request,
}: {
  revision: PlanRevision;
  request: PlanningRequest | null;
}) {
  const checks = constraintChecks(revision, request);
  const failing = checks.filter((check) => check.result === "fail").length;
  return (
    <Card role="region" aria-labelledby="checklist-title">
      <CardHeader>
        <CardTitle id="checklist-title">Constraint checklist</CardTitle>
        <CardDescription>
          {failing === 0
            ? "Every constraint passes"
            : `${failing} ${failing === 1 ? "constraint fails" : "constraints fail"}`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <table aria-label="Constraint checklist" className="w-full text-sm">
          <thead>
            <tr className="border-b">
              {["Constraint", "Result", "Details"].map((heading) => (
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
          <tbody>
            {checks.map((check) => (
              <tr key={check.name} className="border-b align-top">
                <th scope="row" className="px-2 py-2 text-left font-medium">
                  {check.name}
                </th>
                <td className="px-2 py-2">
                  <Badge variant={RESULT_BADGES[check.result].variant}>
                    {RESULT_BADGES[check.result].label}
                  </Badge>
                </td>
                <td className="px-2 py-2">
                  <div className="flex flex-col gap-1">
                    <CheckDetails
                      check={check}
                      revision={revision}
                      request={request}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function CheckDetails({
  check,
  revision,
  request,
}: {
  check: ConstraintCheck;
  revision: PlanRevision;
  request: PlanningRequest | null;
}) {
  return (
    <>
      {check.violations.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {check.violations.map((violation, index) => (
            <li key={index}>
              <span title={`Source: ${SOURCES.checks}`}>
                {violation.message}
              </span>
            </li>
          ))}
        </ul>
      ) : check.name === "Clearance" && check.result === "fail" ? (
        <Shortfalls revision={revision} />
      ) : (
        <p>{passText(check, request)}</p>
      )}
      {check.name === "Policy" &&
        revision.policy_findings.map((finding) => (
          <p
            key={finding.field}
            role="note"
            className="text-muted-foreground text-xs"
          >
            Policy kept: {finding.message}
          </p>
        ))}
    </>
  );
}

function limit(value: number, format: (n: number) => string, detail: string) {
  return (
    <SourcedNumber
      value={value}
      format={format}
      source={SOURCES.checks}
      detail={detail}
    />
  );
}

function passText(
  check: ConstraintCheck,
  request: PlanningRequest | null,
): React.ReactNode {
  switch (check.name) {
    case "Budget": {
      const caps = Object.keys(request?.regional_budget_caps ?? {}).length > 0;
      return (
        <>
          Within the marketing budget
          {request && (
            <>
              {" of "}
              {limit(
                request.marketing_budget,
                formatMoney,
                "the planning request's marketing budget",
              )}
            </>
          )}
          {caps && " and each regional budget cap"}.
        </>
      );
    }
    case "Minimum margin":
      return request?.min_margin != null ? (
        <>
          Blended expected margin at or above the brief&apos;s minimum margin of{" "}
          {limit(
            request.min_margin,
            formatShare,
            "the planning request's minimum margin",
          )}
          .
        </>
      ) : (
        "Blended expected margin at or above the company-policy margin floor."
      );
    case "Stock":
      return "Every line's P90 units fit its available stock.";
    case "Clearance": {
      const targets = request?.clearance_targets ?? [];
      if (check.result === "not_set" || targets.length === 0) {
        return "The brief sets no clearance target.";
      }
      return (
        <>
          Every clearance target is met:{" "}
          {targets.map((target, index) => (
            <span key={target.sku_id}>
              {index > 0 && ", "}
              {target.sku_id} at{" "}
              {limit(
                target.sell_through,
                formatShare,
                "the planning request's clearance target",
              )}{" "}
              sell-through
            </span>
          ))}
          .
        </>
      );
    }
    case "Policy":
      return "Within company policy: maximum discount, unit cost, promo window, promoted-SKU cap, KVI price tolerance and strong substitutes kept apart.";
  }
}

// An infeasible revision's shortfalls, when validate_plan left no violation of its own.
function Shortfalls({ revision }: { revision: PlanRevision }) {
  return (
    <ul className="flex flex-col gap-1">
      {revision.clearance_shortfalls.map((shortfall) => (
        <li key={`${shortfall.sku_id}-${shortfall.region}`}>
          {shortfall.sku_id} in {shortfall.region}: expected{" "}
          <SourcedNumber
            value={shortfall.expected_sell_through}
            format={formatShare}
            source={SOURCES.relaxation}
          />{" "}
          sell-through against a{" "}
          <SourcedNumber
            value={shortfall.target}
            format={formatShare}
            source={SOURCES.relaxation}
          />{" "}
          target,{" "}
          <SourcedNumber
            value={shortfall.shortfall_units}
            format={(units) => Math.round(units).toLocaleString("en-IN")}
            source={SOURCES.relaxation}
          />{" "}
          units short
        </li>
      ))}
    </ul>
  );
}
