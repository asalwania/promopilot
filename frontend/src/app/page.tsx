import { HealthPanel } from "@/components/health-panel";
import { HomeComposer } from "@/components/home-composer";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 p-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold tracking-tight">PromoPilot</h1>
        <p className="text-muted-foreground">
          Agentic retail promotion planner. Try an example, or write your own
          brief and add constraints.
        </p>
      </header>
      <HomeComposer />
      <HealthPanel />
    </main>
  );
}
