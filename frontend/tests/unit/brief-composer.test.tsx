import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BriefComposer } from "@/components/brief-composer";

import { SESSION_ID } from "./fixtures/sessions";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

type Call = { url: string; body: unknown };

function stubCreateSession(response: () => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: JSON.parse(String(init?.body)) });
      return response();
    },
  );
  return calls;
}

function typeBrief(brief: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Brief" }), {
    target: { value: brief },
  });
}

beforeEach(() => {
  push.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("BriefComposer", () => {
  it("starts a session from the brief and opens its page", async () => {
    const calls = stubCreateSession(() =>
      Response.json({ session_id: SESSION_ID }, { status: 202 }),
    );
    render(<BriefComposer />);

    typeBrief("Diwali push for Snacks in North, budget 2 lakh");
    fireEvent.click(screen.getByRole("button", { name: "Plan it" }));

    await vi.waitFor(() =>
      expect(push).toHaveBeenCalledWith(`/sessions/${SESSION_ID}`),
    );
    expect(calls).toEqual([
      {
        url: "/api/sessions",
        body: { brief: "Diwali push for Snacks in North, budget 2 lakh" },
      },
    ]);
  });

  it("keeps Plan it disabled until the brief has text, and counts characters", () => {
    render(<BriefComposer />);
    const planIt = screen.getByRole("button", { name: "Plan it" });

    expect(planIt).toBeDisabled();
    typeBrief("   ");
    expect(planIt).toBeDisabled();
    typeBrief("Diwali push");
    expect(planIt).toBeEnabled();
    expect(screen.getByText("11 / 2000")).toBeInTheDocument();
  });

  it("shows why the session could not start and stays on the page", async () => {
    stubCreateSession(() =>
      Response.json({ detail: "API unreachable" }, { status: 502 }),
    );
    render(<BriefComposer />);

    typeBrief("Diwali push");
    fireEvent.click(screen.getByRole("button", { name: "Plan it" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't start planning: HTTP 502",
    );
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Plan it" })).toBeEnabled();
  });
});
