import { Badge } from "@/components/ui/badge";
import type { PlanExplanation } from "@/lib/api/sessions";

const FALLBACK_REASONS: Record<
  NonNullable<PlanExplanation["fallback_reason"]>,
  string
> = {
  llm_unavailable: "the language model was unavailable",
  ungrounded: "the language model's numbers did not match the tools",
  invalid_answer: "the language model's answer was incomplete",
};

// The Explainer's plan summary (ADR 0050). A template summary says why the
// language model's own was not used.
export function PlanSummary({ explanation }: { explanation: PlanExplanation }) {
  const reason = explanation.fallback_reason;
  return (
    <section aria-label="Plan summary" className="flex flex-col gap-1 text-sm">
      <p>{explanation.summary}</p>
      {explanation.source === "template" && (
        <p className="text-muted-foreground flex flex-wrap items-center gap-2">
          <Badge variant="outline">Template explanation</Badge>
          {reason && `Written from a template: ${FALLBACK_REASONS[reason]}.`}
        </p>
      )}
    </section>
  );
}
