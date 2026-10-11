import { HealthPanel } from "@/components/health-panel";
import { HomeComposer } from "@/components/home-composer";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-10 px-8 pt-16 pb-20">
      <header className="flex max-w-3xl flex-col gap-4">
        <span className="text-primary text-xs font-semibold tracking-[0.14em] uppercase">
          Agentic promotion planner
        </span>
        <h1 className="text-5xl font-medium tracking-tight md:text-6xl">
          PromoPilot
        </h1>
        <p className="text-muted-foreground text-lg leading-relaxed">
          Plan your next promotion in plain words. Try an example, or write your
          own brief and add constraints.
        </p>
      </header>
      <HomeComposer />
      <HealthPanel />
    </main>
  );
}
