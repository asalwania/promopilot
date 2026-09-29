import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BriefComposer } from "@/components/brief-composer";
import { LLMModeBadge } from "@/components/llm-mode-badge";
import { SessionDetails } from "@/components/session-details";
import { EXAMPLE_BRIEFS } from "@/lib/example-briefs";

import { awaitingApprovalSession } from "./fixtures/sessions";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const REPLAY = { mode: "replay", provider: "replay", model: null } as const;
const LIVE = {
  mode: "live",
  provider: "openai",
  model: "gpt-4.1-mini",
} as const;

function typeBrief(brief: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Brief" }), {
    target: { value: brief },
  });
}

function demoHint() {
  return screen.queryByRole("note", { name: "Not in the demo recordings" });
}

// ADR 0073: with no API key the stack replays the recorded sessions, and says so.
describe("LLMModeBadge", () => {
  it("says the demo replays recorded sessions when there is no key", () => {
    render(<LLMModeBadge llm={REPLAY} />);

    expect(screen.getByText("Demo mode")).toBeInTheDocument();
    expect(
      screen.getByText(/replaying recorded sessions, no API key/),
    ).toBeInTheDocument();
  });

  it("names the live provider and model when a key is set", () => {
    render(<LLMModeBadge llm={LIVE} />);

    expect(screen.getByText("Live LLM")).toBeInTheDocument();
    expect(screen.getByText(/openai gpt-4\.1-mini/)).toBeInTheDocument();
  });
});

describe("BriefComposer in demo mode", () => {
  it("explains before planning that a brief of its own is not recorded", () => {
    render(<BriefComposer llm={REPLAY} />);

    typeBrief("Plan a Holi push for Dairy in East, budget 3 lakh");

    expect(demoHint()).toHaveTextContent(/plans it without the language model/);
    expect(demoHint()).toHaveTextContent(/Pick an example brief/);
  });

  it("says nothing for an example brief, which replays as recorded", () => {
    render(<BriefComposer llm={REPLAY} />);

    typeBrief(EXAMPLE_BRIEFS[0].brief);

    expect(demoHint()).not.toBeInTheDocument();
  });

  it("says nothing with a live LLM or before the mode is known", () => {
    const { rerender } = render(<BriefComposer llm={LIVE} />);
    typeBrief("Plan a Holi push for Dairy in East, budget 3 lakh");
    expect(demoHint()).not.toBeInTheDocument();

    rerender(<BriefComposer />);
    expect(demoHint()).not.toBeInTheDocument();
  });
});

describe("SessionDetails in demo mode", () => {
  it("explains the demo's limits for a session not in the recordings, not as an error", () => {
    render(
      <SessionDetails
        session={{
          ...awaitingApprovalSession,
          demo_recording: "not_in_demo_recordings",
        }}
      />,
    );

    const note = screen.getByRole("note", {
      name: "Not in the demo recordings",
    });
    expect(note).toHaveTextContent(/without the language model/);
    expect(note).toHaveTextContent(/OPENAI_API_KEY/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says nothing for a recorded or live session", () => {
    const { rerender } = render(
      <SessionDetails
        session={{ ...awaitingApprovalSession, demo_recording: "recorded" }}
      />,
    );
    expect(demoHint()).not.toBeInTheDocument();

    rerender(<SessionDetails session={awaitingApprovalSession} />);
    expect(demoHint()).not.toBeInTheDocument();
  });
});
