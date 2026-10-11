"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { ConstraintForm } from "@/components/constraint-form";
import { DemoRecordingNote } from "@/components/demo-recording-note";
import { ErrorMessage, type ShownError } from "@/components/error-message";
import { ExampleBriefs } from "@/components/example-briefs";
import { Button } from "@/components/ui/button";
import type { LLMStatus } from "@/lib/api/health";
import { createSession } from "@/lib/api/sessions";
import {
  composeBrief,
  EMPTY_CONSTRAINTS,
  validateConstraints,
  type ConstraintErrors,
  type ConstraintValues,
} from "@/lib/brief-constraints";
import { EXAMPLE_BRIEFS, type ExampleBrief } from "@/lib/example-briefs";
import { BRIEF_MAX_CHARS } from "@/lib/input-limits";

export function BriefComposer({ llm }: { llm?: LLMStatus }) {
  const router = useRouter();
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const [brief, setBrief] = useState("");
  const [constraints, setConstraints] =
    useState<ConstraintValues>(EMPTY_CONSTRAINTS);
  const [constraintErrors, setConstraintErrors] = useState<ConstraintErrors>(
    {},
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ShownError | null>(null);

  // What is sent: the brief plus a sentence per valid constraint (ADR 0058). While a
  // field is invalid, the preview and the count fall back to the brief alone.
  const checked = validateConstraints(constraints);
  const composed = checked.ok ? composeBrief(brief, checked.value) : brief;
  const addsConstraints = checked.ok && composed !== brief.trim();
  const tooLong = composed.length > BRIEF_MAX_CHARS;
  // With no API key only the example briefs replay, word for word (ADR 0058, ADR 0073).
  const unrecorded =
    llm?.mode === "replay" &&
    composed.trim() !== "" &&
    !EXAMPLE_BRIEFS.some((example) => example.brief === composed);

  function changeConstraint(
    field: keyof ConstraintValues,
    values: ConstraintValues,
  ) {
    setConstraints(values);
    // Editing a field clears its error; the next Plan it checks it again.
    setConstraintErrors((errors) => {
      const rest = { ...errors };
      delete rest[field];
      return rest;
    });
  }

  // An example replays only as recorded, so it replaces the brief and clears the form.
  function pickExample(example: ExampleBrief) {
    setBrief(example.brief);
    setConstraints(EMPTY_CONSTRAINTS);
    setConstraintErrors({});
    setError(null);
    briefRef.current?.focus();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!checked.ok) {
      setConstraintErrors(checked.errors);
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await createSession(composed);
    if (result.ok) {
      router.push(`/sessions/${result.sessionId}`);
      return;
    }
    setError({
      message: `Couldn't start planning: ${result.reason}`,
      referenceId: result.referenceId,
    });
    setSubmitting(false);
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      className="grid w-full gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]"
    >
      <div className="flex min-w-0 flex-col gap-6">
        <ExampleBriefs examples={EXAMPLE_BRIEFS} onPick={pickExample} />
        <div className="bg-card shadow-soft flex flex-col gap-3 rounded-2xl border p-6">
          <label htmlFor="brief" className="text-sm font-medium">
            Brief
          </label>
          <textarea
            id="brief"
            ref={briefRef}
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            maxLength={BRIEF_MAX_CHARS}
            rows={5}
            placeholder="e.g. Plan a Diwali push for Snacks in North and West over the next four weeks with a budget of 2 lakh."
            className="border-input focus-visible:border-ring focus-visible:ring-ring/30 rounded-xl border bg-[#fdfcf9] px-4 py-3 text-base leading-relaxed outline-none focus-visible:ring-4"
          />
          {addsConstraints && (
            <div className="flex flex-col gap-1">
              <span id="composed-label" className="text-sm font-medium">
                PromoPilot will read
              </span>
              <p
                aria-labelledby="composed-label"
                role="note"
                className="bg-muted rounded-xl px-4 py-3 text-sm whitespace-pre-wrap"
              >
                {composed}
              </p>
            </div>
          )}
          {unrecorded && <DemoRecordingNote planned={false} />}
          <div className="flex items-center justify-between gap-4">
            <span
              className={
                tooLong
                  ? "text-destructive text-xs tabular-nums"
                  : "text-muted-foreground text-xs tabular-nums"
              }
            >
              {composed.length} / {BRIEF_MAX_CHARS}
              {tooLong && " (shorten the brief or remove constraints)"}
            </span>
            <Button
              size="lg"
              type="submit"
              disabled={submitting || brief.trim() === "" || tooLong}
            >
              Plan it
              <ArrowRight aria-hidden data-icon="inline-end" />
            </Button>
          </div>
          {error && (
            <ErrorMessage
              message={error.message}
              referenceId={error.referenceId}
            />
          )}
        </div>
      </div>
      <aside className="bg-card shadow-soft h-fit rounded-2xl border p-5">
        <ConstraintForm
          values={constraints}
          errors={constraintErrors}
          onChange={changeConstraint}
        />
      </aside>
    </form>
  );
}
