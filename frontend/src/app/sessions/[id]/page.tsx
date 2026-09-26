import Link from "next/link";

import { SessionView } from "@/components/session-view";

export default async function SessionPage({
  params,
}: PageProps<"/sessions/[id]">) {
  const { id } = await params;
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 p-8">
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
      <SessionView sessionId={id} />
    </main>
  );
}
