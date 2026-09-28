import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { EXAMPLE_BRIEFS } from "@/lib/example-briefs";

type SessionScript = { name: string; brief: string };
type Manifest = { sessions: Record<string, { script: SessionScript }> };

// The frontend image is built from frontend/ alone, so the examples are a copy of the
// recorded scripts. These tests keep the copy exact: an example that drifts from its
// recording would miss every cassette and plan degraded with no key (ADR 0054, ADR 0058).
const cassettes = join(__dirname, "../../../backend/cassettes");
const scripts = JSON.parse(
  readFileSync(join(cassettes, "sessions.json"), "utf-8"),
) as SessionScript[];
const manifest = JSON.parse(
  readFileSync(join(cassettes, "manifest.json"), "utf-8"),
) as Manifest;

describe("example briefs", () => {
  it("offers four examples, one per recorded session", () => {
    expect(EXAMPLE_BRIEFS).toHaveLength(4);
    expect(new Set(EXAMPLE_BRIEFS.map((e) => e.session)).size).toBe(4);
  });

  it.each(EXAMPLE_BRIEFS.map((example) => [example.session, example]))(
    "the %s example is its session script's brief, word for word",
    (_, example) => {
      const script = scripts.find((s) => s.name === example.session);
      expect(script?.brief).toBe(example.brief);
    },
  );

  it.each(EXAMPLE_BRIEFS.map((example) => [example.session, example]))(
    "the %s example has a cassette recording of that brief",
    (_, example) => {
      const recorded = manifest.sessions[example.session];
      expect(recorded?.script.brief).toBe(example.brief);
    },
  );
});
