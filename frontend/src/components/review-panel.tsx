"use client";

import { useId, useState, type FormEvent } from "react";

import {
  AmendBox,
  type ActionOutcome,
  type SubmitAmendment,
} from "@/components/amend-box";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { PlanRevision } from "@/lib/api/sessions";

// Mirrors the API's reason limit (ADR 0046 D7); the API still validates.
const REASON_MAX_CHARS = 2000;

export type Approve = (revisionNumber: number) => Promise<ActionOutcome>;
export type Reject = (
  revisionNumber: number,
  reason: string,
) => Promise<ActionOutcome>;

type Step = "choose" | "confirm" | "reject";

// The manager's decision on the shown plan revision (SF-04, ADR 0066): approve it after
// a confirm, reject it with a reason, or amend the brief. A rejected revision can only
// be amended (ADR 0046 D6). One action at a time.
export function ReviewPanel({
  revision,
  status,
  onAmend,
  onApprove,
  onReject,
}: {
  revision: Pick<PlanRevision, "number" | "solver_status">;
  status: "awaiting_approval" | "rejected";
  onAmend: SubmitAmendment;
  onApprove: Approve;
  onReject: Reject;
}) {
  const titleId = useId();
  const [step, setStep] = useState<Step>("choose");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const shown = `plan revision ${revision.number}`;
  const infeasible = revision.solver_status === "INFEASIBLE";

  async function send(
    action: () => Promise<ActionOutcome>,
    failed: string,
  ): Promise<ActionOutcome> {
    setBusy(true);
    setError(null);
    const result = await action();
    setBusy(false);
    if (!result.ok) setError(`${failed}: ${result.reason}`);
    return result;
  }

  async function approve() {
    const result = await send(
      () => onApprove(revision.number),
      `Couldn't approve ${shown}`,
    );
    if (!result.ok) setStep("choose");
  }

  async function reject(trimmed: string) {
    await send(
      () => onReject(revision.number, trimmed),
      `Couldn't reject ${shown}`,
    );
  }

  const amend: SubmitAmendment = async (amendment) => {
    setBusy(true);
    const result = await onAmend(amendment);
    setBusy(false);
    return result;
  };

  return (
    <Card role="region" aria-labelledby={titleId}>
      <CardHeader>
        <CardTitle id={titleId}>
          Review plan revision {revision.number}
        </CardTitle>
        <CardDescription>
          {status === "rejected"
            ? `Plan revision ${revision.number} was rejected. Amend the brief to plan a new revision.`
            : "Approve it, reject it with a reason, or amend the brief to plan a new revision."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {status === "awaiting_approval" && step === "choose" && (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                disabled={busy || infeasible}
                onClick={() => setStep("confirm")}
              >
                Approve plan revision {revision.number}
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setStep("reject")}
              >
                Reject plan revision {revision.number}
              </Button>
            </div>
            {infeasible && (
              <p className="text-muted-foreground text-sm">
                An infeasible plan can&apos;t be approved: amend the brief
                first.
              </p>
            )}
          </div>
        )}
        {status === "awaiting_approval" && step === "confirm" && (
          <div className="flex flex-col gap-2">
            <p className="text-sm">
              Approving makes plan revision {revision.number} final: it
              can&apos;t be amended, approved or rejected afterwards.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button disabled={busy} onClick={approve}>
                Confirm approval
              </Button>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => setStep("choose")}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
        {status === "awaiting_approval" && step === "reject" && (
          <RejectForm
            revisionNumber={revision.number}
            reason={reason}
            onReasonChange={setReason}
            busy={busy}
            onSubmit={reject}
            onCancel={() => setStep("choose")}
          />
        )}
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <AmendBox onAmend={amend} disabled={busy} />
      </CardContent>
    </Card>
  );
}

function RejectForm({
  revisionNumber,
  reason,
  onReasonChange,
  busy,
  onSubmit,
  onCancel,
}: {
  revisionNumber: number;
  reason: string;
  onReasonChange: (reason: string) => void;
  busy: boolean;
  onSubmit: (reason: string) => Promise<void>;
  onCancel: () => void;
}) {
  const id = useId();
  const [blank, setBlank] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = reason.trim();
    setBlank(trimmed === "");
    if (trimmed !== "") await onSubmit(trimmed);
  }

  return (
    <form
      aria-label={`Reject plan revision ${revisionNumber}`}
      onSubmit={submit}
      noValidate
      className="flex flex-col gap-1.5"
    >
      <Label htmlFor={id}>
        Why are you rejecting plan revision {revisionNumber}?
      </Label>
      <Textarea
        id={id}
        rows={2}
        value={reason}
        maxLength={REASON_MAX_CHARS}
        onChange={(event) => {
          onReasonChange(event.target.value);
          if (event.target.value.trim() !== "") setBlank(false);
        }}
        aria-invalid={blank || undefined}
        aria-describedby={blank ? `${id}-error` : undefined}
      />
      {blank && (
        <p id={`${id}-error`} className="text-destructive text-xs">
          Give a reason for rejecting.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" variant="destructive" disabled={busy}>
          Send rejection
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={onCancel}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
