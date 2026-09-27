# The Context agent's LLM only lifts the brief's phrases and stated numbers; deterministic code resolves them into assumptions with a confidence, or into clarification questions answered in free text

E8 (#46) turns the E3 Context agent into SPEC's AG-01 and AG-02. It reads the brief into a planning request plus assumptions, each with a source (brief, data or default) and a confidence. When a critical field is missing or read below 0.7, the graph pauses at a Clarify interrupt, and `POST /api/sessions/{id}/clarify` resumes it.

SPEC, #10 and #46 leave several things open:

- where confidence comes from;
- how the promo window is read;
- which fields get an assumption, and the assumption's shape and storage;
- the question format and the `/clarify` body;
- how many rounds of questions there may be;
- how clamping relates to the optimiser's policy findings (ADR 0040);
- how clearance targets are read;
- what "data tools fill gaps" means;
- revenue, volume and segment asks;
- cassettes.

We chose these with the owner (D1–D14 on #46; every recommended option).

## Reading the brief

- **D1. The LLM lifts phrases, and `BriefResolver` scores them.**
  - The LLM's `BriefReading` gains the brief's own words for its regions (`regions_phrase`), categories (`categories_phrase`) and holiday (`holiday`), and for each clearance's SKUs.
  - The resolver from #83 (ADR 0032) turns each phrase into a value. Its match score is the assumption's confidence.
  - A phrase is asked about when nothing matches, when the best reading scores below 0.7, or when a runner-up is within 0.1.
  - With no phrase, the LLM's own values are resolved by name instead (they score 1.0). So a reading built by hand, as older tests build it, still works.
  - This is what ADR 0032 planned. It is deterministic and reproducible.
  - We rejected LLM-reported confidence, which is uncalibrated, varies between runs and leaves #83 unused. We also rejected taking the lower of the LLM's confidence and the score: two sources to explain, and a bigger schema.
- **D2. The promo window.**
  - When the brief says when, the LLM still picks weeks from the week table (ADR 0020). These are checked against the table: source brief, confidence 1.
  - When the brief only names a holiday, the calendar's weeks for it are used (ADR 0032's "Diwali" rule): source data, confidence = the match score.
  - Neither, or only half a window, is asked, with the holidays ahead as suggestions. So is a window outside the table.
  - The committed demo brief ("the two weeks leading up to Diwali") therefore still reads as weeks 108–109.
  - We rejected always resolving from the holiday phrase: that phrase scores below 0.7 and would ask on the demo brief. We rejected LLM weeks only, which never fills the window from data (AG-01).
- **D11. Numbers stay as ADR 0020 has them.** The LLM extracts the rupees and fractions the brief states. Deterministic code checks their ranges and scope. Their source is the brief, at confidence 1. We rejected a deterministic parser for quoted amounts: more code and more edge cases for the same result.

## Assumptions

- **D3. Every planning-request field gets an assumption**, whether read from the brief, filled from data or left at a default:
  - scope regions, categories and SKU ids;
  - the promo window;
  - the marketing budget and minimum margin;
  - the clearance targets and regional budget caps;
  - the KVI tolerance and the promoted-SKU cap;
  - the as-of week.

  So do facts the plan relies on:
  - the objective;
  - a segment ask;
  - the overstocked SKUs and undercut KVIs in scope.

  Unstated optional fields show company policy's value (source default). CONTEXT.md's **Assumption** is reworded from "inferred rather than read from the brief" to "as the agent read or inferred it". AG-01 and #46 give it source `brief` too. We rejected listing only inferred fields, which hides values read from the brief from correction.
- **D4. Shape and storage.**
  - `Assumption` is a domain type in `promopilot.domain`, with these fields:
    - `field`;
    - `value`, as display text;
    - `source`;
    - `confidence`, from 0 to 1;
    - `flagged`;
    - `note`.
  - The typed value stays in `PlanningRequest`.
  - Assumptions are in the graph's state and in `planning_sessions.assumptions` (JSONB, migration 0012). They hold the latest reading, which #50's re-read replaces.
  - `SessionResponse` gains `assumptions`.
  - We rejected typed JSON values, which grow the schema and the zod types for an editor E10 does not need. We rejected storing assumptions on each plan revision: a clarification pause has no revision yet.
- **D7. A brief that would loosen policy keeps ADR 0040's mechanism.**
  - The request keeps the brief's value.
  - The Context agent runs `guardrails.plan_limits(request, policy)` on the request it read. Each `PolicyFinding` becomes that field's assumption, flagged. Its value is the one applied ("15.0% (company policy; the brief asked for 5.0%)"), and its note is the finding's message.
  - The optimiser applies the same limits and still stores the findings on the revision. There is one source of truth, and the relaxation is unchanged.
  - #46's "clamped" is therefore what `plan_limits` applies, not a rewrite of the request. We rejected clamping inside the request, which loses the brief's value and empties the revision's findings (it would amend ADR 0040). We also rejected clamping in both places.
- **D9. Data fills two lists.**
  - The overstocked SKUs in scope (`pooled_stock` at the as-of week) and the undercut KVIs in scope (`competitor_gaps`) become source-data assumptions.
  - They add no target: only SKUs the brief names get one (ADR 0014).
  - They are computed with the deterministic functions directly, not through the tool registry. The planner keeps its own tools (#47).
  - We rejected calling them through `Tool.run` so the trace (ADR 0047) would show them as tool calls; that would couple this ticket to the planner's tool registry (ADR 0049). We also rejected leaving them to the planner, which leaves SPEC §9.6's gap-filling unmet.
- **D10. What the planner does not offer.**
  - The objective is always listed: incremental gross profit, source default.
  - It is flagged when the LLM's `objective_asked` is revenue or volume (ADR 0005).
  - A `segment_phrase` ("Target families") becomes a flagged assumption that segments are chosen per plan line by profit.
  - We rejected ignoring segment asks, and a new `target_segments` request field, which is new optimiser behaviour.

## Clarification

- **D5. Questions and answers.**
  - A `ClarificationQuestion` has:
    - an `id`, the field, or `clearance_targets.<n>` for the n-th clearance;
    - the `field`;
    - the `question`;
    - a `reason` (`missing`, `low_confidence` or `ambiguous`);
    - `suggestions`, the resolver's readings or the data's options, best first.
  - The body is `{"answers": {question_id: text}}`.
    - Every open question is answered, and nothing else. Each answer is 1–2000 characters and not blank.
    - Unknown fields, a missing or unknown id, and an empty or oversized answer are `422`.
  - The answers are kept as `Clarification`s (question and answer). They are in the graph's state and in `planning_sessions.clarifications`.
  - The Context node reads the brief again with the answers and any amendments, which prepares #50. They go as quoted JSON after the brief. That is one more LLM call per round.
  - A brief with no answers or amendments is sent exactly as before, so only the prompt and schema changed its hash.
  - We rejected typed answers per field, which need a form per field and no LLM. We rejected one free-text `{text}`, which loses which answer goes with which question.
- **D6. Rounds and the API.**
  - Rounds are not capped. Each asks only what is still open, and the manager drives every round.
  - `POST /clarify` returns `202`. The session is back in `planning` with its answers kept, and the graph resumes from its checkpoint in the background, because planning follows.
  - Responses: `409` unless the session is `awaiting_clarification` (a second answer to the same questions included), `404` for an unknown session, `503` without checkpoints.
  - The session moves to `awaiting_clarification` only after the graph returns paused at Clarify, as ADR 0046 D5 does for approval. `SessionStore.answer_clarifications` moves it back with a conditional `UPDATE … WHERE status = 'awaiting_clarification'`, so two answers cannot both resume one interrupt. The same per-session lock covers answers and decisions.
  - A session awaiting clarification survives an API restart. Only `planning` sessions fail at startup (ADR 0046 D15).
  - We rejected a cap of 3 rounds, which fails a session a manager is still answering. We rejected a synchronous `/clarify`, which blocks for as long as planning takes.
- **The graph.**
  - Context → Clarify when the reading has questions; otherwise Context → Planner.
  - Clarify → Context, as SPEC §9.6 draws it. So #46's "the answer resumes to Planner" is the route clarify → context → planner.
  - Clarify does nothing before its interrupt, since LangGraph re-runs an interrupted node from its start.
  - `resume_with_answers` answers it.
  - Both nodes are traced like every other (ADR 0047). The `clarification` trace event (`ClarificationAsked`, the questions' text) is emitted by the Context node when it has questions, not by Clarify before its interrupt: Clarify re-runs from its start when it is resumed, so emitting there would repeat the event.
  - `GraphSnapshot.awaits_clarification` joins `awaits_decision`.
  - The checkpoint allowlist gains the Clarify interrupt's types.
- **D8. Clearance targets.**
  - For each clearance the brief asks for, the LLM lifts the SKUs' words and a sell-through (null when the brief gives none). `resolver.products(phrase, categories=scope)` finds the SKUs, and each gets the figure as its target.
  - A missing figure is asked ("What sell-through should subcategory Paneer reach…"). This is ADR 0040's "asks for one"; it never defaults (ADR 0014).
  - So is a phrase that matches nothing in scope, or matches ambiguously, such as "clear our overstock". The overstocked SKUs in scope are suggested.
  - A named SKU that is not overstocked in any scope region is flagged, and its target kept.
  - We rejected a default figure, which ADR 0014 rules out, and assuming the best reading of an ambiguous phrase without asking.
- **D14. The E3 session page lists the open questions** as text, each with its suggestions. Answering them, and the assumptions panel, are E10's.

## What changes elsewhere

- **ADR 0020's "a missing critical field fails the session" is replaced by Clarify**, as that ADR foresaw. `read_planning_request`, used by `make record-cassettes` and the committed-cassette test, still raises `BriefError` naming what is missing when a brief would need a question. Every brief in `briefs.json` must therefore read without one.
- **ADR 0040 is kept.** The request keeps the brief's values. Its "asks for one or records an assumption" for a clearance with no figure is settled as asking. The four fields ADR 0040 left to #46 are now read from the brief:
  - clearance targets;
  - regional budget caps;
  - the KVI tolerance;
  - the promoted-SKU cap.
- **Cassette (D12).** The prompt (context v2) and `BriefReading` changed, so the committed cassette's request hash changed. The cassette `9c322147…json` was **migrated by hand, not recorded**:
  - Its request was rebuilt by the real code path over the seed-42 world, through `record_cassettes` with a scripted provider, so its hash is exact.
  - Its response keeps the recorded answer (Snacks and Beverages, North and West, weeks 108–109, ₹200,000).
  - The new fields hold only the brief's own words ("North and West", "Snacks and Beverages", "Diwali") or null.
  - It must be re-recorded with a live key (`make data`, `make train`, then `make record-cassettes`, which also records the planner agent's turns since ADR 0049) with the owner's OK. The SPEC §3.2 demo brief joins `briefs.json` at that recording, not before, since a response for a brief never recorded would be invented.
  - We rejected leaving the stale cassette, which turns CI red until recording. We also rejected skipping the committed-cassette test.
- **D13. A relaxation as an amendment the manager can accept** (ADR 0044's follow-up) belongs to #50. #50 adds amending and re-planning, and can apply `optimizer.relaxed_request`. We rejected a suggested amendment text on the revision now (the revision read model is #49's too), and a `POST /accept-relaxation` that duplicates #50's re-planning.

## Consequences

- Migration 0012 adds nullable `assumptions`, `questions` and `clarifications` JSONB columns to `planning_sessions`. Sessions from before #46 read as empty.
- New public names:
  - domain: `Assumption`, `AssumptionSource`, `ClarificationQuestion`, `QuestionReason` and `Clarification`;
  - agents: `read_context`, `ContextReading`, `ClearanceAsk`, `RegionalCap`, `ClarificationRequest`, `ClarificationAnswer` and `resume_with_answers`;
  - `SessionRecorder.save_assumptions`.
- `BriefData` also reads stores, inventory and the latest competitor prices.
- `BriefReading`'s JSON Schema marks every field required and shows no defaults, as structured outputs need. Fields added here keep a Python default of None, so hand-built readings need not name them.
- A phrase the resolver cannot match is always asked, even one meaning "every region" ("pan-India", "all regions"). Teaching the resolver those phrases is a follow-up.
- There is no new configuration.
- Follow-ups:
  - re-record the cassette with a live key, and add the SPEC §3.2 brief;
  - #50 amends and accepts relaxations;
  - E10 adds the clarification form and the assumptions panel.
