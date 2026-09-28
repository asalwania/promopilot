"use client";

import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { AmendInput } from "@/lib/api/sessions";

// Mirrors the API's amendment limit (ADR 0052 D3); the API still validates.
const AMENDMENT_MAX_CHARS = 2000;

// What a session action told the page: done, or why not (ADR 0061, ADR 0066).
export type ActionOutcome = { ok: true } | { ok: false; reason: string };

// Sends an amendment in the manager's words, or accepts the latest relaxation (#62).
export type SubmitAmendment = (amendment: AmendInput) => Promise<ActionOutcome>;

// The amend box (AG-05, SPEC §11): a change to the brief in plain English, from which
// the agent plans a new revision. The text stays when sending fails (ADR 0066).
export function AmendBox({
  onAmend,
  disabled = false,
}: {
  onAmend: SubmitAmendment;
  // Another action on the session is being sent.
  disabled?: boolean;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const [blank, setBlank] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const amendment = text.trim();
    setBlank(amendment === "");
    if (amendment === "") return;

    setSending(true);
    setError(null);
    const result = await onAmend({ text: amendment });
    setSending(false);
    if (result.ok) {
      setText("");
    } else {
      setError(`Couldn't amend the brief: ${result.reason}`);
    }
  }

  return (
    <form
      aria-label="Amend the brief"
      onSubmit={submit}
      noValidate
      className="flex flex-col gap-1.5"
    >
      <Label htmlFor={id}>Amend the brief</Label>
      <Textarea
        id={id}
        rows={2}
        value={text}
        maxLength={AMENDMENT_MAX_CHARS}
        placeholder="e.g. Budget cut to ₹6 lakh, or Drop West"
        onChange={(event) => {
          setText(event.target.value);
          if (event.target.value.trim() !== "") setBlank(false);
        }}
        aria-invalid={blank || undefined}
        aria-describedby={blank ? `${id}-error` : undefined}
      />
      {blank && (
        <p id={`${id}-error`} className="text-destructive text-xs">
          Write the change you want.
        </p>
      )}
      <div className="flex items-center justify-end">
        <Button type="submit" variant="outline" disabled={disabled || sending}>
          Amend and re-plan
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
