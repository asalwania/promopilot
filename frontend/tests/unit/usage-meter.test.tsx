import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UsageMeter } from "@/components/usage-meter";

const usage = {
  calls: 12,
  input_tokens: 1_234_567,
  output_tokens: 8910,
  cost_usd: 0.5081,
  cost_inr: 48.78,
  unpriced_models: [],
};

function termsOf(meter: HTMLElement) {
  return Object.fromEntries(
    within(meter)
      .getAllByRole("term")
      .map((term) => [term.textContent, term.nextElementSibling?.textContent]),
  );
}

describe("UsageMeter", () => {
  it("shows the session's calls, tokens and cost in rupees then dollars", () => {
    render(<UsageMeter usage={usage} />);

    const meter = screen.getByRole("region", { name: "LLM usage" });
    expect(termsOf(meter)).toEqual({
      "LLM calls": "12",
      "Input tokens": "12,34,567",
      "Output tokens": "8,910",
      Cost: "₹48.78$0.5081",
    });
  });

  it("names where each number comes from", () => {
    render(<UsageMeter usage={usage} />);

    for (const shown of ["12,34,567", "₹48.78", "$0.5081"]) {
      expect(screen.getByText(shown)).toHaveAttribute(
        "title",
        "Source: LLM usage meter · sum of the session's token-usage trace events",
      );
    }
  });

  it("lists models it has no price for", () => {
    render(
      <UsageMeter usage={{ ...usage, unpriced_models: ["local-model"] }} />,
    );

    expect(
      screen.getByText("local-model: tokens only, no price set"),
    ).toBeInTheDocument();
  });

  it("says when no LLM call has been made yet", () => {
    render(
      <UsageMeter
        usage={{
          calls: 0,
          input_tokens: 0,
          output_tokens: 0,
          cost_usd: 0,
          cost_inr: 0,
          unpriced_models: [],
        }}
      />,
    );

    const meter = screen.getByRole("region", { name: "LLM usage" });
    expect(meter).toHaveTextContent("No LLM calls yet.");
    expect(within(meter).queryByRole("term")).not.toBeInTheDocument();
  });
});
