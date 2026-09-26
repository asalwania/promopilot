import { z } from "zod";

const errorDetailSchema = z.object({ detail: z.string() });

// Why a request failed: the API's (or the proxy's) `detail` when it gives one,
// otherwise the HTTP status.
export async function responseReason(response: Response): Promise<string> {
  try {
    const parsed = errorDetailSchema.safeParse(await response.json());
    if (parsed.success) return parsed.data.detail;
  } catch {
    // Not JSON: fall back to the status.
  }
  return `HTTP ${response.status}`;
}
