import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BriefComposer } from "@/components/brief-composer";
import { EXAMPLE_BRIEFS } from "@/lib/example-briefs";

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

function stubCreated() {
  return stubCreateSession(() =>
    Response.json({ session_id: SESSION_ID }, { status: 202 }),
  );
}

function briefBox() {
  return screen.getByRole("textbox", { name: "Brief" });
}

function typeBrief(brief: string) {
  fireEvent.change(briefBox(), { target: { value: brief } });
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByRole("textbox", { name: label }), {
    target: { value },
  });
}

function planIt() {
  fireEvent.click(screen.getByRole("button", { name: "Plan it" }));
}

beforeEach(() => {
  push.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("BriefComposer", () => {
  it("starts a session from the brief and opens its page", async () => {
    const calls = stubCreated();
    render(<BriefComposer />);

    typeBrief("Diwali push for Snacks in North, budget 2 lakh");
    planIt();

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
    const button = screen.getByRole("button", { name: "Plan it" });

    expect(button).toBeDisabled();
    typeBrief("   ");
    expect(button).toBeDisabled();
    typeBrief("Diwali push");
    expect(button).toBeEnabled();
    expect(screen.getByText("11 / 2000")).toBeInTheDocument();
  });

  it("shows why the session could not start and stays on the page", async () => {
    stubCreateSession(() =>
      Response.json({ detail: "API unreachable" }, { status: 502 }),
    );
    render(<BriefComposer />);

    typeBrief("Diwali push");
    planIt();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't start planning: HTTP 502",
    );
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Plan it" })).toBeEnabled();
  });
});

describe("example briefs", () => {
  it("offers the four recorded examples", () => {
    render(<BriefComposer />);
    const examples = screen.getByRole("list", { name: "Try an example" });

    expect(within(examples).getAllByRole("listitem")).toHaveLength(4);
    for (const example of EXAMPLE_BRIEFS) {
      expect(
        within(examples).getByRole("heading", { name: example.title }),
      ).toBeInTheDocument();
    }
    expect(
      within(examples).getByText(/Budget cut to ₹6 lakh/),
    ).toBeInTheDocument();
  });

  it("fills the brief with the example and clears the constraints, without planning", () => {
    const calls = stubCreated();
    render(<BriefComposer />);
    type("Marketing budget (₹ lakh)", "3");
    fireEvent.click(screen.getByRole("checkbox", { name: "South" }));

    const demo = EXAMPLE_BRIEFS[0];
    fireEvent.click(
      screen.getByRole("button", { name: `Try it ${demo.title}` }),
    );

    expect(briefBox()).toHaveValue(demo.brief);
    expect(
      screen.getByRole("textbox", { name: "Marketing budget (₹ lakh)" }),
    ).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: "South" })).not.toBeChecked();
    expect(calls).toEqual([]);
    expect(push).not.toHaveBeenCalled();
  });

  it("sends an example exactly as recorded", async () => {
    const calls = stubCreated();
    render(<BriefComposer />);
    const example = EXAMPLE_BRIEFS[1];

    fireEvent.click(
      screen.getByRole("button", { name: `Try it ${example.title}` }),
    );
    planIt();

    await vi.waitFor(() => expect(push).toHaveBeenCalled());
    expect(calls[0].body).toEqual({ brief: example.brief });
  });
});

describe("constraint form", () => {
  it("submits the constraints with the brief as sentences the agent reads", async () => {
    const calls = stubCreated();
    render(<BriefComposer />);

    typeBrief("Plan a festive push.");
    type("Marketing budget (₹ lakh)", "4.5");
    type("Minimum margin (%)", "20");
    fireEvent.click(screen.getByRole("checkbox", { name: "West" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "North" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Dairy" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Promo window" }), {
      target: { value: "Christmas" },
    });
    type("Product to clear", "1kg paneer");
    type("Sell-through (%)", "50");

    const sent =
      "Plan a festive push.\n\nConstraints: Marketing budget ₹4.5 lakh. " +
      "Keep margin above 20%. Regions: North and West. Categories: Dairy. " +
      "Run it for Christmas. Clear at least 50% of 1kg paneer stock.";
    expect(screen.getByLabelText("PromoPilot will read")).toHaveTextContent(
      "Constraints: Marketing budget ₹4.5 lakh.",
    );
    expect(screen.getByText(`${sent.length} / 2000`)).toBeInTheDocument();

    planIt();

    await vi.waitFor(() =>
      expect(push).toHaveBeenCalledWith(`/sessions/${SESSION_ID}`),
    );
    expect(calls).toEqual([{ url: "/api/sessions", body: { brief: sent } }]);
  });

  it("shows what is wrong and does not plan until it is fixed", async () => {
    const calls = stubCreated();
    render(<BriefComposer />);

    typeBrief("Plan a festive push.");
    type("Marketing budget (₹ lakh)", "0");
    type("Sell-through (%)", "60");
    planIt();

    const budget = screen.getByRole("textbox", {
      name: "Marketing budget (₹ lakh)",
    });
    expect(budget).toHaveAttribute("aria-invalid", "true");
    expect(budget).toHaveAccessibleDescription("Enter a budget above ₹0.");
    expect(
      screen.getByRole("textbox", { name: "Product to clear" }),
    ).toHaveAccessibleDescription("Name the product to clear.");
    expect(calls).toEqual([]);

    type("Marketing budget (₹ lakh)", "2");
    expect(budget).not.toHaveAttribute("aria-invalid", "true");
    type("Product to clear", "400g namkeen");
    planIt();

    await vi.waitFor(() => expect(push).toHaveBeenCalled());
    expect(calls[0].body).toEqual({
      brief:
        "Plan a festive push.\n\nConstraints: Marketing budget ₹2 lakh. " +
        "Clear at least 60% of 400g namkeen stock.",
    });
  });

  it("will not send a brief longer than 2000 characters with its constraints", () => {
    render(<BriefComposer />);

    typeBrief("x".repeat(1990));
    expect(screen.getByRole("button", { name: "Plan it" })).toBeEnabled();
    type("Marketing budget (₹ lakh)", "2");

    expect(screen.getByRole("button", { name: "Plan it" })).toBeDisabled();
    expect(screen.getByText(/2030 \/ 2000/)).toBeInTheDocument();
  });

  it("says that only the example briefs replay exactly without a key", () => {
    render(<BriefComposer />);
    expect(
      screen.getByText(/only the example briefs replay exactly/),
    ).toBeInTheDocument();
  });
});
