import { connection } from "next/server";

import { HealthStatus } from "@/components/health-status";
import { getHealth } from "@/lib/api/health";

export default async function Home() {
  await connection();
  const health = await getHealth(
    process.env.API_URL ?? "http://localhost:8000",
  );

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">PromoPilot</h1>
      <p className="text-muted-foreground">Agentic retail promotion planner</p>
      <HealthStatus result={health} />
    </main>
  );
}
