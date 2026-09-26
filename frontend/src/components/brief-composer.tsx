"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { createSession } from "@/lib/api/sessions";

// Mirrors the API's brief limits (ADR 0020); the API still validates.
const BRIEF_MAX_CHARS = 2000;

export function BriefComposer() {
  const router = useRouter();
  const [brief, setBrief] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await createSession(brief);
    if (result.ok) {
      router.push(`/sessions/${result.sessionId}`);
      return;
    }
    setError(`Couldn't start planning: ${result.reason}`);
    setSubmitting(false);
  }

  return (
    <form onSubmit={submit} className="flex w-full max-w-2xl flex-col gap-3">
      <label htmlFor="brief" className="text-sm font-medium">
        Brief
      </label>
      <textarea
        id="brief"
        value={brief}
        onChange={(event) => setBrief(event.target.value)}
        maxLength={BRIEF_MAX_CHARS}
        rows={5}
        placeholder="e.g. Plan a Diwali push for Snacks in North and West over the next four weeks with a budget of 2 lakh."
        className="border-input bg-background focus-visible:border-ring focus-visible:ring-ring/50 rounded-lg border px-3 py-2 text-sm outline-none focus-visible:ring-3"
      />
      <div className="flex items-center justify-between gap-4">
        <span className="text-muted-foreground text-xs tabular-nums">
          {brief.length} / {BRIEF_MAX_CHARS}
        </span>
        <Button type="submit" disabled={submitting || brief.trim() === ""}>
          Plan it
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </form>
  );
}
