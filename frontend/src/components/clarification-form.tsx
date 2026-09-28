"use client";

import { useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Clarification, ClarificationQuestion } from "@/lib/api/sessions";
import { fieldLabel } from "@/lib/assumptions";

// Mirrors the API's answer limit (ADR 0048 D5); the API still validates.
const ANSWER_MAX_CHARS = 2000;

const REASON_LABELS: Record<ClarificationQuestion["reason"], string> = {
  missing: "Missing",
  low_confidence: "Low confidence",
  ambiguous: "Ambiguous",
};

export type SubmitAnswers = (
  answers: Record<string, string>,
) => Promise<{ ok: true } | { ok: false; reason: string }>;

// The Context agent's open questions, answered in place (AG-02, SPEC §11). Every
// answer is free text keyed by its question id, sent together (ADR 0048 D5, ADR 0061).
// The page keys the form by round, so a question asked again starts empty.
export function ClarificationForm({
  questions,
  clarifications,
  onSubmit,
}: {
  questions: ClarificationQuestion[];
  clarifications: Clarification[];
  onSubmit: SubmitAnswers;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [missing, setMissing] = useState<Set<string>>(new Set());
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The latest answer given to each question id, for a question asked again.
  const previous = new Map(
    clarifications.map((c) => [c.question.id, c.answer] as const),
  );

  function change(id: string, value: string) {
    setAnswers((current) => ({ ...current, [id]: value }));
    if (value.trim() !== "") {
      setMissing((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const blank = questions
      .map((question) => question.id)
      .filter((id) => (answers[id] ?? "").trim() === "");
    setMissing(new Set(blank));
    if (blank.length > 0) return;

    setSending(true);
    setError(null);
    const result = await onSubmit(
      Object.fromEntries(
        questions.map((question) => [question.id, answers[question.id].trim()]),
      ),
    );
    if (!result.ok) {
      setError(`Couldn't send the answers: ${result.reason}`);
      setSending(false);
    }
  }

  return (
    <Card role="region" aria-labelledby="clarification-title">
      <CardHeader>
        <CardTitle id="clarification-title">
          The agent needs your answers
        </CardTitle>
        <CardDescription>
          Planning resumes once every question is answered.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          aria-label="Clarification questions"
          onSubmit={submit}
          noValidate
          className="flex flex-col gap-4"
        >
          {questions.map((question) => (
            <QuestionField
              key={question.id}
              question={question}
              value={answers[question.id] ?? ""}
              previous={previous.get(question.id)}
              missing={missing.has(question.id)}
              onChange={(value) => change(question.id, value)}
            />
          ))}
          <div className="flex items-center justify-end">
            <Button type="submit" disabled={sending}>
              Answer and resume planning
            </Button>
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

function QuestionField({
  question,
  value,
  previous,
  missing,
  onChange,
}: {
  question: ClarificationQuestion;
  value: string;
  previous: string | undefined;
  missing: boolean;
  onChange: (value: string) => void;
}) {
  // Question ids are field names, e.g. `scope.regions` or `clearance_targets.0`.
  const id = `answer-${question.id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
  const described = [
    previous !== undefined && `${id}-previous`,
    missing && `${id}-error`,
  ].filter(Boolean);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-start justify-between gap-3">
        <Label htmlFor={id} className="leading-snug">
          {question.question}
        </Label>
        <Badge variant="outline">{REASON_LABELS[question.reason]}</Badge>
      </div>
      {previous !== undefined && (
        <p id={`${id}-previous`} className="text-muted-foreground text-xs">
          You answered: “{previous}”
        </p>
      )}
      <Input
        id={id}
        type="text"
        value={value}
        maxLength={ANSWER_MAX_CHARS}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={missing || undefined}
        aria-describedby={
          described.length > 0 ? described.join(" ") : undefined
        }
      />
      {missing && (
        <p id={`${id}-error`} className="text-destructive text-xs">
          Answer this question.
        </p>
      )}
      {question.suggestions.length > 0 && (
        <div
          role="group"
          aria-label={`Suggestions for ${fieldLabel(question.field)}`}
          className="flex flex-wrap gap-1.5"
        >
          {question.suggestions.map((suggestion) => (
            <Button
              key={suggestion}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onChange(suggestion)}
            >
              {suggestion}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
