import Link from "next/link";

import { SessionView } from "@/components/session-view";

export default async function SessionPage({
  params,
}: PageProps<"/sessions/[id]">) {
  const { id } = await params;
  // Wide enough for the trace timeline beside the session at ≥ 1280px (ADR 0057).
  return (
    <main className="mx-auto flex w-full max-w-screen-2xl flex-1 flex-col gap-6 p-8">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">
          Planning session
        </h1>
        <Link
          href="/"
          className="text-muted-foreground text-sm hover:underline"
        >
          New brief
        </Link>
      </div>
      {/* Keyed so another session starts with a fresh trace. */}
      <SessionView key={id} sessionId={id} />
    </main>
  );
}
