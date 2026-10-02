import Link from "next/link";

import { SessionView } from "@/components/session-view";

export default async function SessionPage({
  params,
}: PageProps<"/sessions/[id]">) {
  const { id } = await params;
  // Wide enough for the trace timeline beside the session at ≥ 1280px (ADR 0057).
  return (
    <main className="mx-auto flex w-full max-w-screen-2xl flex-1 flex-col gap-8 px-8 pt-10 pb-16">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-4xl font-medium tracking-tight">
          Planning session
        </h1>
        <Link
          href="/"
          className="border-input bg-card text-foreground hover:bg-muted rounded-full border px-4 py-1.5 text-sm font-medium shadow-xs transition-colors"
        >
          New brief
        </Link>
      </div>
      {/* Keyed so another session starts with a fresh trace. */}
      <SessionView key={id} sessionId={id} />
    </main>
  );
}
