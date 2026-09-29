import { useId } from "react";

// The demo's limits, explained rather than shown as an error (ADR 0073): with no API key
// only the recorded sessions replay; anything else still plans, without the LLM.
export function DemoRecordingNote({ planned }: { planned: boolean }) {
  const titleId = useId();
  return (
    <div
      role="note"
      aria-labelledby={titleId}
      className="flex flex-col gap-1 rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-950 dark:bg-sky-950 dark:text-sky-50"
    >
      <p id={titleId} className="font-medium">
        Not in the demo recordings
      </p>
      <p>
        {planned
          ? "This session is not one of the recorded demo sessions, so PromoPilot plans it without the language model"
          : "This brief is not one of the recorded demo briefs, so PromoPilot plans it without the language model"}
        : rules read the brief, the default sequence plans and a template
        explains. Pick an example brief to replay a recorded session, or set
        OPENAI_API_KEY in .env and run make demo again to plan your own.
      </p>
    </div>
  );
}
