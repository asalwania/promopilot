# When the LLM is down, the Context agent reads the brief by strict rules into low-confidence assumptions, and asks about anything the rules cannot read

E8 (#124) closes the last SF-03 gap. After #47 only the Planner degraded: an LLM failure at the Context node still failed the session (ADR 0046 D14, ADR 0049 D8). Now, when reading the brief raises `LLMError` after its retries and fallback provider, a cassette miss included, the Context agent reads the brief with `BriefResolver` (ADR 0032) and strict rules instead. Every value it reads is a low-confidence assumption, and whatever it cannot read goes to Clarify (ADR 0048). So planning runs end to end with no LLM.

SPEC, #10 and #124 leave open:

- when the fallback triggers;
- how brief phrases are found without the LLM lifting them;
- the rupee and percent rules;
- how the promo window is found without the LLM's week pick;
- the confidence values and routing;
- how the fallback is shown;
- clarify answers and amendments with the LLM down;
- "all regions" and "pan-India" (the #46 follow-up).

We chose these with the owner (D1–D11 on #124; every recommended option).

## When

- **D1. Any `LLMError` from the Context read, `CassetteMissError` included, and only in the graph's Context node.**
  - `read_context(..., fallback=True)` catches it, logs `context_fallback` with the reason, and returns the rules' reading. The reading says why in `ContextReading.degraded`: `DegradedReason.llm_unavailable` or `cassette_missing`, reused from ADR 0049.
  - Only the graph passes `fallback=True`. `read_planning_request`, which `make record-cassettes` and the committed-cassette test use, stays strict, so a miss still fails them loudly.
  - Other errors, such as `BriefError` or a bug, still fail the session (ADR 0046 D14).
  - We rejected skipping cassette misses, which leaves the replayed demo and e2e failing at Context. We also rejected falling back on any error, which hides bugs.
- **D2. Every Context run tries the LLM first.** Each clarify round and each amendment asks the LLM again, and falls back only if that run fails. The Planner, Critic and Explainer degrade on their own, as before. We rejected a sticky per-session fallback: it is faster during an outage but never recovers.

## Reading

The rules build the same `BriefReading` the LLM would lift. `interpret` then resolves and checks it exactly as it checks the LLM's (ADR 0048), so the request, assumptions and questions follow one set of rules. The code is `promopilot.agents.fallback.read_by_rules`.

- **D3. Phrases are exact mentions.**
  - `BriefResolver.mentions(text)` returns the regions, categories, product names (category, subcategory, brand, pack size) and holidays the text names.
  - A term counts only when all of its words appear in the text, in order and adjacent, filler words included.
  - The mentioned words are then resolved by the existing methods, so an exact reading still scores 1.0.
  - Fuzzy matching is used only on a clarify answer, where the answer is itself the phrase.
  - We rejected fuzzy scanning at the 0.6 similarity floor: ordinary words hit ("best" and West score 0.75, "month" and North 0.6). We rejected resolving whole sentences: the mean-over-words score falls below 0.7, so everything would be asked.
- **D4. Rupees and percentages come from `guardrails.read_stated_numbers`.** Turning "₹2 lakh" into 200000 is arithmetic, which `promopilot.agents` may not do (ADR 0049 D10), so the parser lives in guardrails.
  - **Money** needs ₹, Rs or INR, or a lakh, lac, crore or cr word ("₹8 lakh", "2 lakh", "Rs 5,00,000"). The shorthands k, L and Cr count only straight after a rupee sign ("₹90k", "₹2L"), so "2L cola" and "90k units" are never money.
  - A **percentage** is written with %, "percent" or "per cent", and is read as a fraction.
  - Numbers inside words ("400g", "SKU0002", "W108") are never read. A bare number is read only in an answer, in the unit the question asked for.
  - **Placing numbers.** The text is cut into sentences, then clauses (at commas, semicolons, dashes, "and", "with", …).
    - An amount in a clause about the budget ("budget", "spend", "marketing") is a budget candidate.
    - Otherwise, an amount written against exactly one region ("₹90k for North", "North at ₹90k") is that region's cap. Only linking words may stand between the two.
    - Any other amount is a loose candidate.
    - The budget is the one budget candidate, or else the one loose one. Two or more are asked about, with the amounts as suggestions.
    - A percentage belongs to the nearest cue in its clause, before it first: margin → minimum margin; clear, sell-through or overstock → clearance; competitor, KVI or tolerance → KVI tolerance. A percentage with no cue is not read.
  - **Other fields**, from keyword rules (D11):
    - SKU ids named in the text ("SKU0002");
    - the SKU cap ("at most 2 SKUs per category");
    - the objective ("maximise revenue", "boost volume"), flagged as before;
    - a segment ("Target families"), flagged as before.
  - **Clearance.** A sentence with a clearance cue gets one clearance ask per clearance percentage, or one with no figure, which is then asked. Its SKUs are the product names the sentence mentions, or else the previous sentence's. Its money and percentages are blanked first, so "₹2L" is no 2L pack. With no product names, the sentence itself is the phrase, which the resolver cannot match, so it is asked with the overstocked SKUs as suggestions (ADR 0048 D8).
  - We rejected also reading a bare "90k", "2L" or "2 lakh" with no rupee sign as money ("2L" is a pack size). We rejected reading only the budget and leaving the brief's margin and targets at policy defaults: that silently drops the brief's constraints.
- **D5. The promo window.**
  - Week ids the text states ("weeks 54-55", "W108-W109") are checked against the week table as before: source brief.
  - Otherwise, the one holiday the text names gives the calendar's weeks for it (ADR 0032): source data. So the committed demo brief reads as weeks 108–109, as the LLM read it.
  - Several different holidays, dates or relative phrases ("next month") are asked, with the holidays ahead as suggestions.
  - We rejected holidays only, and mapping calendar dates, which adds date-format edge cases.

## Confidence and how it shows

- **D6. What the rules read from the text is at most 0.7 confident** (`FALLBACK_CONFIDENCE`). This covers every source-brief assumption and the promo window. What comes from data or company policy keeps its confidence (the as-of week, policy defaults, the overstocked SKUs, the undercut KVIs, the objective).
  - Routing is unchanged: a missing field, or one the resolver scores below 0.7, is asked.
  - So "low confidence" in #124 means low next to an LLM reading's 1.0, yet at the AG-02 threshold, never below it. A brief the rules read fully, such as the demo brief, still plans.
  - We rejected keeping the resolver's 1.0, which is not low-confidence as #124 asks. We rejected a fixed 0.5 that skips Clarify, which breaks AG-02. We rejected a fixed 0.5 that asks about everything, which stops the demo at Clarify.
- **D7. `Assumption.fallback` marks it; the source is unchanged.**
  - Every assumption of a fallback reading has `fallback: true`, and one read from the text notes "Read by rules: the language model was unavailable."
  - `PlanningState.context_degraded` keeps the reason.
  - The Context node emits `DecisionMade(decision="context_fallback")`, whose summary names the reason.
  - The OpenAPI contract and frontend types gain the field. Stored assumptions without it read as `false`, so there is no migration.
  - We rejected a new `AssumptionSource.fallback`: it conflicts with SPEC AG-01's three sources, loses the brief-vs-data distinction and breaks the E3 page's enum. We rejected marking the fallback only in notes, which gives "flagged" a second meaning.

## Answers and amendments

- **D8. Answers are read against their questions.**
  - An answer is read into its question's field: regions, categories, window and clearance SKUs through mentions or the resolver, and amounts and percentages through the D4 parser (a bare number counts). It overrides the brief.
  - An answer the rules cannot read is asked again, as low confidence, quoting the answer.
  - We rejected appending the answers to the brief, where an answered budget collides with the brief's amount forever. We rejected needing the LLM for answers, which leaves Clarify unfinishable during an outage.
- **D9. Amendments are read oldest first, after the answers.**
  - What an amendment states replaces the earlier value.
  - In a clause with "drop", "remove", "exclude" or "without", the regions and categories it names leave the scope. With "add", "include" or "also", they join it. Named with no such verb, they replace it.
  - An amendment the rules read nothing from becomes a question (`field` `amendment`, `id` `amendment.<n>`). Its answer is read in the amendment's place.
  - This lives only in the fallback. `read_context` already passes amendments, and #50 re-reads with the LLM as before.
  - We rejected leaving amendments out: the replayed demo's "budget cut to ₹6 lakh" and "drop West" would fail until their cassettes are recorded. We rejected plain last-wins with no verbs, where "drop West" would narrow the scope to West.
- **D10. "All regions" and "pan-India" name every region, on both paths.**
  - `BriefResolver.regions` reads these as every region at 1.0: "all/every/each (four) regions or zones", "pan-India", "all-India", "nationwide" and "across India".
  - `categories` does the same for "all/every categories" and "the entire/whole/full range".
  - They count only when the phrase names nothing else, so "all regions except West" is resolved as before.
  - This supersedes ADR 0048's consequence that such phrases are always asked. We rejected fixing it only in the fallback, which would make the two paths disagree.

## What changes elsewhere

- **SPEC AG-02**: "low confidence" for a fallback reading means at most 0.7, and routing to Clarify stays "below 0.7" (D6).
- **SPEC AG-01** keeps its three sources. The fallback is marked by `Assumption.fallback`, not by a source (D7).
- **ADR 0027 and ADR 0049 D9**, "a cassette miss must fail loudly" and "the Context agent's miss still fails the session": now true only for recording and the committed-cassette test (`read_planning_request`). In a session, a Context miss reads by rules (D1).
- **ADR 0046 D14 and ADR 0049 D8**: an `LLMError` at Context no longer fails the session. A session still fails on other errors. The API's "the language model failed" message stays for any LLM error that escapes.
- **ADR 0048 D11** rejected a deterministic parser for quoted amounts. **D5** re-reads the answers with the LLM. Both still hold for the LLM path; the fallback alone parses and reads answers by rules (D4, D8).
- **ADR 0048's consequence** that "pan-India" or "all regions" is always asked is superseded (D10).

## Consequences

- New public names:
  - guardrails: `read_stated_numbers`, `StatedNumber` and `StatedKind`;
  - agents: `read_by_rules`, `FALLBACK_CONFIDENCE`, `BriefResolver.mentions` with `Mentions`, `ContextReading.degraded` and `PlanningState.context_degraded`;
  - domain: `Assumption.fallback`.
- `read_context` gains `fallback`. `DegradedReason` now also says why the Context agent read by rules.
- There is no migration and no new setting. The prompts and cassettes are unchanged.
- In replay, a brief without a cassette now plans (or asks) instead of failing, with fallback assumptions and the Planner's `cassette_missing` degradation.
- The rules are strict by design. A misspelling, a region adjective ("Northern") or an unusual phrasing is asked, never guessed.
- Follow-ups:
  - E10 shows the fallback marker in the assumptions panel;
  - E9 can score the rules against the LLM's readings on the eval briefs.
