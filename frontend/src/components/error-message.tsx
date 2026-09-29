import { cn } from "@/lib/utils";

// A failed request as a page holds it: the message to show and the reference id.
export type ShownError = { message: string; referenceId?: string };

type ErrorMessageProps = {
  message: string;
  referenceId?: string | null;
  className?: string;
};

// The shared way a page shows a failed request (ADR 0071): the message inline,
// as ADR 0066 D8 has it, and the reference id to quote when reporting it.
export function ErrorMessage({
  message,
  referenceId,
  className,
}: ErrorMessageProps) {
  return (
    <p role="alert" className={cn("text-destructive text-sm", className)}>
      {message}
      <ReferenceId referenceId={referenceId} />
    </p>
  );
}

// The reference id line alone, for an alert that lays out its own message.
export function ReferenceId({ referenceId }: { referenceId?: string | null }) {
  if (!referenceId) return null;
  return (
    <span className="text-muted-foreground mt-0.5 block text-xs">
      Reference: <span className="font-mono select-all">{referenceId}</span>
    </span>
  );
}
