"use client";

import { useQuery } from "@tanstack/react-query";

import { BriefComposer } from "@/components/brief-composer";
import { LLMModeBadge } from "@/components/llm-mode-badge";
import { getHealth } from "@/lib/api/health";

// The composer, told whether the stack replays the demo recordings (ADR 0073).
export function HomeComposer() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => getHealth() });
  const llm = health.data?.reachable ? health.data.health.llm : undefined;
  return (
    <>
      {llm && <LLMModeBadge llm={llm} />}
      <BriefComposer llm={llm} />
    </>
  );
}
