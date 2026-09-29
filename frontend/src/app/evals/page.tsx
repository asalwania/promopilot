import { EvalsView } from "@/components/evals-view";

export default function EvalsPage() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold tracking-tight">Evals</h1>
      <EvalsView />
    </main>
  );
}
