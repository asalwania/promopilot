import { BriefComposer } from "@/components/brief-composer";
import { HealthPanel } from "@/components/health-panel";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">PromoPilot</h1>
      <p className="text-muted-foreground">Agentic retail promotion planner</p>
      <BriefComposer />
      <HealthPanel />
    </main>
  );
}
