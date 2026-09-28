"use client";

import { useQuery } from "@tanstack/react-query";

import { getCompetitorGaps } from "@/lib/api/catalog";

const MAX_RETRIES = 2;

// The KVI competitor gaps at a planning request's as-of week: the prices the
// planner saw (ADR 0031). The plan's undercut callouts read them, and the
// competitor panel (#63) can share the same cached query (ADR 0060).
export function useCompetitorGaps(asOfWeek: number | undefined) {
  return useQuery({
    queryKey: ["competitors", "gaps", { asOfWeek, kviOnly: true }],
    queryFn: () => getCompetitorGaps(fetch, { asOfWeek, kviOnly: true }),
    enabled: asOfWeek !== undefined,
    // Prices before a past as-of week never change.
    staleTime: Infinity,
    retry: MAX_RETRIES,
  });
}
