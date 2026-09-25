import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { HealthResult } from "@/lib/api/health";

export function HealthStatus({ result }: { result: HealthResult }) {
  if (!result.reachable) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle role="status">API unreachable</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">{result.reason}</p>
        </CardContent>
      </Card>
    );
  }

  const { health } = result;
  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle
          role="status"
          className="flex items-center justify-between gap-2"
        >
          <span>{health.status === "ok" ? "API healthy" : "API degraded"}</span>
          <Badge variant="secondary">v{health.version}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-y-1 text-sm">
          {Object.entries(health.checks).map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="text-muted-foreground">{name}</dt>
              <dd>
                <Badge variant={value === "error" ? "destructive" : "outline"}>
                  {value}
                </Badge>
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
