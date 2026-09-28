// One-click trials on the home page (ADR 0058). Each brief is, word for word, a session
// script in backend/cassettes/sessions.json, so it replays with no API key (ADR 0054).
// tests/unit/example-briefs.test.ts fails if a brief drifts from its recording.
export type ExampleBrief = {
  /** The recorded session's name in backend/cassettes/sessions.json. */
  session: string;
  title: string;
  description: string;
  brief: string;
  /** What to try on the session page, in the words the recording used. */
  tryNext?: string;
};

export const EXAMPLE_BRIEFS: readonly ExampleBrief[] = [
  {
    session: "demo",
    title: "Diwali demo",
    description:
      "₹8 lakh across North and West, a margin floor, a clearance target and a target segment.",
    brief:
      "Plan Diwali promotions for Snacks and Beverages across North and West. Budget ₹8 lakh. Keep margin above 18%. We are overstocked on 400g namkeen packs — clear at least 60% of that stock. Target families.",
    tryNext: "Then amend with “Budget cut to ₹6 lakh” and “Drop West”.",
  },
  {
    session: "e2e",
    title: "Quick Diwali push",
    description: "Two weeks before Diwali in North and West, on ₹2 lakh.",
    brief:
      "Plan a Diwali promotion for Snacks and Beverages in North and West. Run it for the two weeks leading up to Diwali, with a marketing budget of ₹2 lakh.",
  },
  {
    session: "clarify",
    title: "Vague brief: the agent asks",
    description:
      "No budget is given, so the agent asks for one before planning.",
    brief:
      "Plan a Diwali promotion for Snacks and Beverages in North and West. Run it for the two weeks leading up to Diwali.",
    tryNext: "Answer “₹2 lakh” when it asks for the budget.",
  },
  {
    session: "regional",
    title: "Christmas, every region",
    description:
      "₹5 lakh with a cap on South, KVIs kept near competitor prices, young urban shoppers.",
    brief:
      "Plan a Christmas promotion for Snacks and Beverages across all regions. Marketing budget ₹5 lakh, with no more than ₹1 lakh in South. Stay within 3% of competitor prices on KVIs. Target young urban shoppers.",
  },
];
