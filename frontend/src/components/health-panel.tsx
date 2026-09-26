"use client";

import { useEffect, useState } from "react";

import { HealthStatus } from "@/components/health-status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { getHealth, type HealthResult } from "@/lib/api/health";

export function HealthPanel() {
  const [result, setResult] = useState<HealthResult | null>(null);

  useEffect(() => {
    let active = true;
    getHealth().then((health) => {
      if (active) setResult(health);
    });
    return () => {
      active = false;
    };
  }, []);

  if (result === null) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle role="status">Checking API…</CardTitle>
        </CardHeader>
      </Card>
    );
  }
  return <HealthStatus result={result} />;
}
