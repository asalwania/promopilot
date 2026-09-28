import { SourcedNumber } from "@/components/sourced-number";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SessionUsage } from "@/lib/api/sessions";
import { formatPrice, formatTokens, formatUsd } from "@/lib/format";

// The read model sums the session's token-usage trace events (ADR 0047).
const SOURCE = {
  source: "LLM usage meter",
  detail: "sum of the session's token-usage trace events",
};

// What planning has cost so far (user story 21): rupees first, dollars second.
export function UsageMeter({ usage }: { usage: SessionUsage }) {
  return (
    <Card role="region" aria-labelledby="usage-meter-title" size="sm">
      <CardHeader>
        <CardTitle id="usage-meter-title">LLM usage</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        {usage.calls === 0 ? (
          <p className="text-muted-foreground">No LLM calls yet.</p>
        ) : (
          <dl className="grid grid-cols-4 gap-4">
            <Term label="LLM calls">
              <SourcedNumber value={usage.calls} {...SOURCE} />
            </Term>
            <Term label="Input tokens">
              <SourcedNumber
                value={usage.input_tokens}
                format={formatTokens}
                {...SOURCE}
              />
            </Term>
            <Term label="Output tokens">
              <SourcedNumber
                value={usage.output_tokens}
                format={formatTokens}
                {...SOURCE}
              />
            </Term>
            <Term label="Cost">
              <span className="flex items-baseline gap-2">
                <SourcedNumber
                  value={usage.cost_inr}
                  format={formatPrice}
                  {...SOURCE}
                />
                <span className="text-muted-foreground text-xs">
                  <SourcedNumber
                    value={usage.cost_usd}
                    format={formatUsd}
                    {...SOURCE}
                  />
                </span>
              </span>
            </Term>
          </dl>
        )}
        {usage.unpriced_models.map((model) => (
          <p key={model} className="text-muted-foreground text-xs">
            {model}: tokens only, no price set
          </p>
        ))}
      </CardContent>
    </Card>
  );
}

function Term({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-base font-medium">{children}</dd>
    </div>
  );
}
