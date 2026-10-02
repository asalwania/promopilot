import { ModelsView } from "@/components/models-view";

export default function ModelsPage() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-8 pt-12 pb-16">
      <h1 className="text-4xl font-medium tracking-tight">Models</h1>
      <ModelsView />
    </main>
  );
}
