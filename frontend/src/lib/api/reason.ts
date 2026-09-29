import { z } from "zod";

// Every API error answers one schema (ADR 0071): `detail` is the message to show,
// `code` the kind of error and `reference_id` the request's id, which is also
// its X-Request-ID header. FastAPI's older validation list is still read.
const errorBodySchema = z.object({
  detail: z.union([
    z.string().min(1),
    z.array(z.object({ msg: z.string() })).min(1),
  ]),
  code: z.string().optional(),
  reference_id: z.string().optional(),
});

// Why a request failed: the message to show, the error's code when the API
// gave one, and the reference id to quote when there is one.
export type ApiFailure = {
  message: string;
  code: string | null;
  referenceId?: string;
  status: number;
};

export async function apiError(response: Response): Promise<ApiFailure> {
  const header = response.headers.get("x-request-id") ?? undefined;
  let body: unknown = undefined;
  try {
    body = await response.json();
  } catch {
    // Not JSON: fall back to the status.
  }
  const parsed = errorBodySchema.safeParse(body);
  const failure: ApiFailure = {
    message: `HTTP ${response.status}`,
    code: null,
    status: response.status,
  };
  if (parsed.success) {
    const { detail, code, reference_id } = parsed.data;
    failure.message = typeof detail === "string" ? detail : detail[0].msg;
    failure.code = code ?? null;
    if (reference_id) failure.referenceId = reference_id;
  }
  if (!failure.referenceId && header) failure.referenceId = header;
  return failure;
}

// A failed request thrown for TanStack Query to surface, with the reference id
// the page shows next to its message.
export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly referenceId?: string,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export function referenceIdOf(error: unknown): string | undefined {
  return error instanceof ApiRequestError ? error.referenceId : undefined;
}
