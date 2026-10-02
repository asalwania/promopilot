import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import type { ExampleBrief } from "@/lib/example-briefs";

type Props = {
  examples: readonly ExampleBrief[];
  onPick: (example: ExampleBrief) => void;
};

// The home page's one-click trials: each card fills the brief, and the manager plans it.
export function ExampleBriefs({ examples, onPick }: Props) {
  return (
    <section aria-labelledby="examples-heading" className="flex flex-col gap-3">
      <h2 id="examples-heading" className="text-xl font-medium tracking-tight">
        Try an example
      </h2>
      <ul
        aria-labelledby="examples-heading"
        className="grid grid-cols-1 gap-3 md:grid-cols-2"
      >
        {examples.map((example) => (
          <li key={example.session} className="flex">
            <Card
              size="sm"
              className="hover:border-input w-full transition-colors"
            >
              <CardHeader>
                <h3
                  id={`example-${example.session}-title`}
                  className="text-[0.95rem] font-semibold"
                >
                  {example.title}
                </h3>
                <CardAction>
                  <Button
                    id={`example-${example.session}-try`}
                    type="button"
                    variant="outline"
                    size="sm"
                    aria-labelledby={`example-${example.session}-try example-${example.session}-title`}
                    onClick={() => onPick(example)}
                  >
                    Try it
                  </Button>
                </CardAction>
                <CardDescription>
                  {example.description}
                  {example.tryNext && (
                    <span className="mt-1 block italic">{example.tryNext}</span>
                  )}
                </CardDescription>
              </CardHeader>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}
