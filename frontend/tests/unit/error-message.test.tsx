import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ErrorMessage } from "@/components/error-message";

const REFERENCE = "6f1c2a7e-0b1d-4c55-9a0e-3d2b1f0c9e11";

describe("ErrorMessage", () => {
  it("shows the message and the reference id to quote (ADR 0071)", () => {
    render(
      <ErrorMessage
        message="Couldn't approve: plan revision 1 is approved and final"
        referenceId={REFERENCE}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "Couldn't approve: plan revision 1 is approved and final",
    );
    expect(alert).toHaveTextContent(`Reference: ${REFERENCE}`);
  });

  it("shows only the message when there is no reference id", () => {
    render(<ErrorMessage message="Couldn't start planning: fetch failed" />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Couldn't start planning: fetch failed");
    expect(alert).not.toHaveTextContent("Reference");
  });
});
