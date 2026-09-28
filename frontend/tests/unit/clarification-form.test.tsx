import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  ClarificationForm,
  type SubmitAnswers,
} from "@/components/clarification-form";

import {
  awaitingClarificationSession,
  repeatedQuestionSession,
} from "./fixtures/sessions";

const BUDGET =
  "What marketing budget should the plan's promo cost stay within, in rupees?";
const CATEGORIES = 'Which product categories does "snak stuff" mean?';

function renderForm(
  onSubmit: SubmitAnswers = vi.fn(async () => ({ ok: true as const })),
  session = awaitingClarificationSession,
) {
  render(
    <ClarificationForm
      questions={session.questions}
      clarifications={session.clarifications}
      onSubmit={onSubmit}
    />,
  );
  return onSubmit;
}

function answer(question: string, text: string) {
  fireEvent.change(screen.getByRole("textbox", { name: question }), {
    target: { value: text },
  });
}

function submit() {
  fireEvent.click(
    screen.getByRole("button", { name: "Answer and resume planning" }),
  );
}

describe("ClarificationForm", () => {
  it("asks each open question as a labelled answer box with its reason", () => {
    renderForm();

    const form = screen.getByRole("form", { name: "Clarification questions" });
    expect(within(form).getAllByRole("textbox")).toHaveLength(2);
    expect(screen.getByRole("textbox", { name: BUDGET })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: CATEGORIES })).toHaveValue("");
    expect(form).toHaveTextContent("Missing");
    expect(form).toHaveTextContent("Low confidence");
  });

  it("fills an answer from a suggestion, which stays editable", () => {
    renderForm();

    const suggestions = screen.getByRole("group", {
      name: "Suggestions for Categories",
    });
    fireEvent.click(
      within(suggestions).getByRole("button", { name: "Snacks" }),
    );

    const box = screen.getByRole("textbox", { name: CATEGORIES });
    expect(box).toHaveValue("Snacks");
    answer(CATEGORIES, "Snacks and Beverages");
    expect(box).toHaveValue("Snacks and Beverages");
  });

  it("offers no suggestions for a question that has none", () => {
    renderForm();

    expect(
      screen.queryByRole("group", { name: "Suggestions for Marketing budget" }),
    ).not.toBeInTheDocument();
  });

  it("submits every answer by its question id", async () => {
    const onSubmit = renderForm();

    answer(BUDGET, "  ₹2 lakh ");
    answer(CATEGORIES, "Snacks");
    submit();

    await vi.waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        marketing_budget: "₹2 lakh",
        "scope.categories": "Snacks",
      }),
    );
  });

  it("asks for every answer before sending any", () => {
    const onSubmit = renderForm();

    answer(BUDGET, "   ");
    submit();

    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      screen.getByRole("textbox", { name: BUDGET }),
    ).toHaveAccessibleDescription("Answer this question.");
    expect(
      screen.getByRole("textbox", { name: CATEGORIES }),
    ).toHaveAccessibleDescription("Answer this question.");

    answer(BUDGET, "₹2 lakh");
    expect(
      screen.getByRole("textbox", { name: BUDGET }),
    ).not.toHaveAccessibleDescription("Answer this question.");
  });

  it("caps each answer at the API's 2000 characters", () => {
    renderForm();

    expect(screen.getByRole("textbox", { name: BUDGET })).toHaveAttribute(
      "maxLength",
      "2000",
    );
  });

  it("disables the button while the answers are sent", async () => {
    let settle: (value: { ok: true }) => void = () => {};
    renderForm(() => new Promise((resolve) => (settle = resolve)));

    answer(BUDGET, "₹2 lakh");
    answer(CATEGORIES, "Snacks");
    submit();

    const button = screen.getByRole("button", {
      name: "Answer and resume planning",
    });
    await vi.waitFor(() => expect(button).toBeDisabled());
    settle({ ok: true });
  });

  it("shows why the answers were not taken and keeps them for another try", async () => {
    const onSubmit = vi.fn(async () => ({
      ok: false as const,
      reason:
        "answer every open question by its id; unanswered: scope.categories",
    }));
    renderForm(onSubmit);

    answer(BUDGET, "₹2 lakh");
    answer(CATEGORIES, "Snacks");
    submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't send the answers: answer every open question by its id; unanswered: scope.categories",
    );
    expect(screen.getByRole("textbox", { name: BUDGET })).toHaveValue(
      "₹2 lakh",
    );
    expect(
      screen.getByRole("button", { name: "Answer and resume planning" }),
    ).toBeEnabled();
  });

  it("shows the earlier answer to a question asked again", () => {
    renderForm(undefined, repeatedQuestionSession);

    const box = screen.getByRole("textbox", {
      name: /What budget should the plan's promo cost stay within/,
    });
    expect(box).toHaveValue("");
    expect(box).toHaveAccessibleDescription("You answered: “2 laks”");
  });
});
