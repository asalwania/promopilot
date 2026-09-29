import { z } from "zod";

import { apiError, ApiRequestError } from "@/lib/api/reason";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

// `kind` is read as any string so a new model kind (relations, E5) renders
// without a frontend change (ADR 0030); every other field must match the
// OpenAPI-generated type (make api-types), or tsc fails here.
export const modelEntrySchema = z.object({
  model_id: z.string(),
  kind: z.string(),
  version: z.number(),
  trained_at: z.string(),
  as_of_week: z.number(),
  metrics: z.record(z.string(), z.number()),
  live: z.boolean(),
}) satisfies z.ZodType<Omit<Schemas["ModelEntry"], "kind"> & { kind: string }>;

const modelListSchema = z.object({ models: z.array(modelEntrySchema) });

export type ModelEntry = z.infer<typeof modelEntrySchema>;

// TanStack Query key for the registry list.
export const MODELS_QUERY_KEY = ["models"];

export class ModelsRequestError extends ApiRequestError {
  constructor(message: string, referenceId?: string) {
    super(message, referenceId);
    this.name = "ModelsRequestError";
  }
}

async function requestError(response: Response): Promise<ModelsRequestError> {
  const failure = await apiError(response);
  return new ModelsRequestError(failure.message, failure.referenceId);
}

// Browser-side: both go through the same-origin `/api/*` proxy (ADR 0018) and
// throw on any failure, so TanStack Query can surface it. Network errors from
// fetch propagate as they are.
export async function listModels(
  fetchImpl: typeof fetch = fetch,
): Promise<ModelEntry[]> {
  const response = await fetchImpl("/api/models", { cache: "no-store" });
  if (!response.ok) throw await requestError(response);
  const parsed = modelListSchema.safeParse(await response.json());
  if (!parsed.success) {
    throw new ModelsRequestError("unexpected models response");
  }
  return parsed.data.models;
}

// Holds until the new model is live, 40 to 90 seconds (ADR 0026).
export async function retrainModels(
  fetchImpl: typeof fetch = fetch,
): Promise<ModelEntry> {
  const response = await fetchImpl("/api/models/retrain", { method: "POST" });
  if (!response.ok) throw await requestError(response);
  const parsed = modelEntrySchema.safeParse(await response.json());
  if (!parsed.success) {
    throw new ModelsRequestError("unexpected retrain response");
  }
  return parsed.data;
}
