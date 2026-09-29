import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  AMENDMENT_MAX_CHARS,
  ANSWER_MAX_CHARS,
  BRIEF_MAX_CHARS,
  REASON_MAX_CHARS,
} from "@/lib/input-limits";

// The UI mirrors the API's input limits (ADR 0071); the committed OpenAPI
// contract (make api-types) is where the API states them.
type Schema = {
  maxLength?: number;
  anyOf?: Schema[];
  properties?: Record<string, Schema>;
  additionalProperties?: Schema;
};

const openapi = JSON.parse(
  readFileSync(join(process.cwd(), "..", "docs", "openapi.json"), "utf8"),
) as { components: { schemas: Record<string, Schema> } };

function property(schema: string, name: string): Schema {
  const found = openapi.components.schemas[schema].properties?.[name];
  if (!found) throw new Error(`${schema}.${name} is not in the contract`);
  return found;
}

function maxLength(schema: Schema): number | undefined {
  return schema.maxLength ?? schema.anyOf?.find((s) => s.maxLength)?.maxLength;
}

describe("input limits", () => {
  it("match the API's contract", () => {
    expect(maxLength(property("CreateSessionRequest", "brief"))).toBe(
      BRIEF_MAX_CHARS,
    );
    expect(maxLength(property("AmendRequest", "text"))).toBe(
      AMENDMENT_MAX_CHARS,
    );
    expect(maxLength(property("RejectRequest", "reason"))).toBe(
      REASON_MAX_CHARS,
    );
    expect(
      property("ClarifyRequest", "answers").additionalProperties?.maxLength,
    ).toBe(ANSWER_MAX_CHARS);
  });
});
