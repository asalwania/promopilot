import { Badge } from "@/components/ui/badge";
import type { LLMStatus } from "@/lib/api/health";

// Which LLM plans: the recorded demo sessions with no key, or a live provider (ADR 0073).
export function LLMModeBadge({ llm }: { llm: LLMStatus }) {
  const replay = llm.mode === "replay";
  return (
    <p className="flex items-center gap-2 text-sm">
      <Badge variant={replay ? "secondary" : "outline"} className="gap-1.5">
        <span
          aria-hidden
          className={
            replay
              ? "bg-warning size-1.5 rounded-full"
              : "bg-success size-1.5 rounded-full"
          }
        />
        {replay ? "Demo mode" : "Live LLM"}
      </Badge>
      <span className="text-muted-foreground">
        {replay
          ? "replaying recorded sessions, no API key"
          : [llm.provider, llm.model].filter(Boolean).join(" ")}
      </span>
    </p>
  );
}
