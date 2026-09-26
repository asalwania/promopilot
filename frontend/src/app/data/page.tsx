import { DataView } from "@/components/data-view";

export default function DataPage() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold tracking-tight">Data</h1>
      <DataView />
    </main>
  );
}
