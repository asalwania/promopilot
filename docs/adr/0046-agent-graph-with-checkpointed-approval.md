# Planning sessions run a checkpointed agent graph that pauses at Approval, and every approval or rejection is kept as the session's audit trail

E8 (#44) replaces the fixed planning pipeline with the LangGraph agent graph of SPEC §9.6. The graph runs Context → Planner → Critic → Explainer → Approval (an interrupt) → Done. It is checkpointed in Postgres, so a session paused at Approval survives an API restart. A manager approves a specific plan revision, or rejects it with a reason. The ticket fixes the nodes of this first slice:

- the Planner runs the deterministic default sequence;
- the Critic runs `validate_plan`;
- the Explainer uses a template.

It does not fix:

- the checkpointer's driver and tables;
- how the graph runs from a request;
- how the thread relates to the session;
- the transitions and their 409s;
- the approval record;
- what reject does to the graph;
- how failures and restarts behave.

We chose these with the owner (D1–D17 on #44; every recommended option).

## The checkpointer

- **D1. LangGraph's own Postgres checkpointer, on psycopg 3.** The pins are:
  - `langgraph` ≥ 1.2.12;
  - `langgraph-checkpoint-postgres` ≥ 3.1.2;
  - `psycopg[binary]` ≥ 3.3.6;
  - `psycopg-pool` ≥ 3.3.3.

  `AsyncPostgresSaver` gets its own small psycopg pool (up to 4 connections) on the app database. Its URL is `DATABASE_URL` with the SQLAlchemy driver name dropped. So the app now has two drivers: asyncpg for SQLAlchemy (ADR 0001) and psycopg 3 for the checkpoints. This amends ADR 0001, which names asyncpg as the only driver.
  - psycopg's async mode cannot run on the Proactor event loop that Windows uses by default:
    - `make dev` is unaffected, because uvicorn's `--reload` runs a selector loop;
    - Docker runs Linux;
    - the integration tests pick a selector loop through pytest-asyncio's `pytest_asyncio_loop_factories` hook.
  - We rejected a hand-written checkpointer on asyncpg: it would reimplement LangGraph's checkpoint protocol and have to track it on every upgrade. We also rejected the sync `PostgresSaver` in threads, which is clumsy under an async graph.
- **D2. LangGraph owns its tables.** `AsyncPostgresSaver.setup()` creates and migrates them when the API starts, right after `migrate()`. Migration 0009 adds only our tables and columns. We rejected copying LangGraph's DDL into Alembic, which would drift on upgrades.
- **Checkpoints revive only our types.** By default LangGraph revives any type a checkpoint names and only warns about it. `checkpoint_serializer()` passes an explicit allowlist instead: every pydantic model and enum reachable from the graph's state and the Approval interrupt, collected from the type annotations.
- **Every step is checkpointed before the next runs** (durability `sync`).
- If the checkpointer cannot open at startup, the API still starts, since liveness comes first (ADR 0001). `POST /api/sessions`, `/approve` and `/reject` then answer `503`.

## Sessions and the graph

- **D3. The thread id is the session id.** `planning_sessions.thread_id` holds it as text. It is set when the session is created, and it is null for sessions planned before E8.
- **D4. Planning runs in the background, and decisions run in the request.**
  - `POST /api/sessions` still returns `202`. A background task runs the graph until it pauses or fails.
  - `POST /approve` and `POST /reject` resume the graph from its checkpoint within the request and return the updated `SessionResponse`. Approval → Done is deterministic and instant, so a decision and its 409 are immediate.
  - A per-session lock in the process means two requests never resume one interrupt together. The store's conditional update (below) is the guard across processes.
  - We rejected running decisions in the background, which makes the UI poll and makes 409s racy. We also rejected running the whole graph in `POST /api/sessions`, which would block it for up to a minute.
- **D5. The session row stays the read model.** Nodes write to it through a `SessionRecorder` (`SessionStore`):
  - the Planner saves the plan revision and the planning request;
  - the Critic saves its open issues on the revision;
  - Approval records each decision.

  The checkpoint is read only to resume. `GET /api/sessions/{id}` never touches LangGraph and still reads sessions from before E8.

  One refinement: the move to `awaiting_approval` happens after `start_planning` returns with the thread paused at Approval. The node itself does not make it. A decision is therefore only possible once its interrupt is checkpointed; a test that restarted the API right after the status changed caught the race. LangGraph re-runs an interrupted node from its start on resume, so the Approval node does nothing before its interrupt.
- **D12. The fixed pipeline goes, and its parts become nodes.**
  - `plan_session` and the old `SessionService(planner=...)` wiring are removed.
  - The Context node is `read_planning_request`, unchanged, so cassettes keep their hashes.
  - The Planner node is `OptimisingPlanner`. It generates options, optimises, attaches the relaxation when the request is infeasible (ADR 0044) and simulates, all as before. It now also returns the revision's `PlanFacts`, built by the new `optimizer.plan_facts` from the option table (ADR 0028's consequence). #47 puts the tool-calling agent in front of it and keeps it as the degraded path.
  - We rejected driving the sequence through the tool registry now, which would rebuild the revision from tool JSON.
- **State.** `PlanningState` holds the SPEC §9.6 fields that have values in this slice:
  - the session id, brief and amendments;
  - the planning request;
  - the plan revision and its plan facts;
  - the Critic's findings and the iteration;
  - the explanations and the latest decision.

  The simulation lives on the revision (ADR 0042). Assumptions and clarifications (#46), the trace (#45) and the diff from the previous revision (#50) join the state with the tickets that produce them.

## Transitions

- **D6. The session statuses and their transitions:**

  | From | Event | To |
  |---|---|---|
  | `planning` | graph paused at Approval | `awaiting_approval` |
  | `planning` | a node fails | `failed` |
  | `awaiting_approval` | approve | `approved` (final) |
  | `awaiting_approval` | reject | `rejected` (open for an amendment, #50) |

  `awaiting_clarification` arrives with #46. Approve and reject are allowed only from `awaiting_approval`. Everything else is `409`: approving or rejecting twice, deciding while planning, and approving or rejecting a rejected revision (it must be amended first). An unknown session is `404`. We rejected letting a rejected revision be approved later, which muddies the audit trail.
- **D7. Every decision names its revision.**
  - Approve takes `{revision_number}`.
  - Reject takes `{revision_number, reason}`, with a reason of 1–2000 characters that is not blank.
  - Unknown fields are `422`.
  - A revision that is not the session's latest is `409`, so nobody approves a revision they never saw, such as a stale tab after an amendment.

  This adds `revision_number` to SPEC §10's bodies. We rejected an empty approve body that means "the latest".
- **D10. An infeasible revision cannot be approved** (ADR 0044 left this to E8). Approving it is `409`, and the message says to amend the brief with its relaxation first. It can still be rejected. A revision with open Critic issues can be approved, as SPEC's "best feasible plan with open issues listed" implies.
- **D16. An approved plan is final.** `POST /api/plans/{id}/simulate` is `409` on an approved session, because its stored simulation is part of what was approved. This amends ADR 0043's "any session with a plan revision can be re-simulated".

## The approval record

- **D8. The audit trail.** Migration 0009 adds an `approvals` table with one row per decision:
  - `id`;
  - `session_id` and `revision_number`, a foreign key to the plan revision;
  - `decision`, `approved` or `rejected`;
  - `reason`, required exactly for a rejection;
  - `decided_at`, the server's `now()`.

  A partial unique index allows one approval per session. Rejections are all kept. There is no approver column, because SPEC has no authentication. `SessionStore.record_decision` moves the status and inserts the row in one transaction. Its `UPDATE … WHERE status = 'awaiting_approval' AND <latest revision> = n` raises `SessionConflictError` and changes nothing when it does not apply. The read model gains `decisions`, oldest first, as `PlanDecision` values. We rejected keeping only the last rejection reason on the session.
- **D9. Reject resumes the graph.**
  - The Approval node records the rejection, and its edge goes back to Approval, so the thread pauses at the interrupt again. #50's amendment resumes it from there into the Planner.
  - The rejection is in the graph's state (`approval`) for #45's trace.
  - Approve goes to Done, which ends the thread.

  This amends the SPEC §9.6 diagram, which had reject going to Done. The spec issue (#10) already keeps a rejected session open. We rejected a reject that only writes to the database.

## Critic, Explainer and failures

- **D11. No Critic loop yet.** `validate_plan` runs on the Planner's plan facts, and every violation becomes an **open issue**. Open issues are stored on the revision (`plan_revisions.open_issues`, JSONB, migration 0009) and shown in the read model. The plan still goes to the Explainer and Approval. #48 adds the loop back to the Planner and its cap. With a deterministic planner, looping would only produce the same plan again.
  - The Critic validates against the planning request the Context agent read. An optimised plan has no violations: a test on the small world checks that its plan facts pass `validate_plan`.
- **D13. A template Explainer.** Each plan line gets one sentence, and the revision gets a summary:
  - status, objective and binding constraints;
  - which constraints the relaxation changes, and whether policy binds;
  - the open issues' codes.

  It uses only the revision's own numbers. Money is in whole rupees and units are whole numbers, rounded to the nearest one, so every number passes numeric grounding (ADR 0028); a hypothesis property checks this. The explanations live in the graph's state only. Storing them and exposing them is #49, whose LLM Explainer keeps this template as its fallback.
- **D14. A node's error fails the session.** It propagates out of the graph. The session service marks the session `failed` with the same manager-readable messages as before: the brief could not be planned, planning is not possible yet, the language model failed, or it failed unexpectedly. The checkpoint is left as it is and never resumed. We rejected an error field and a Failed node, which add graph surface #45 can revisit.
- **D15. A restart still fails what was mid-planning.** At startup, sessions still `planning` are marked failed, as ADR 0020 decided. Only a thread paused at an interrupt resumes. We rejected resuming half-planned sessions at boot, which would redo LLM and solver work and risk running them twice. This settles ADR 0020's "E8's checkpointer can later resume them" for now.

## The session page

- **D17.** The E3 session page follows the regenerated types (`decisions`, `open_issues`). It shows the latest decision as a line of text: "Plan revision 1 was approved." or "Plan revision 1 was rejected: <reason>". Its status labels already covered every status, and it stops polling on any status but `planning`. The approve and reject buttons, the audit trail and the open issues are E10's.

## Consequences

- `build_graph(tools, llm, checkpointer)` is the agents module's entry point. SPEC §7.3 is updated to match.
- There are new public names:
  - agents: `GraphTools`, `SessionRecorder`, `PlanningState`, `ApprovalAnswer`, `PostgresCheckpoints` and `MemoryCheckpoints`, `start_planning`, `resume_with_decision` and `graph_state`;
  - domain: `PlanDecision` and `DecisionKind`;
  - `Violation` and `ViolationCode` move to `promopilot.domain`, which a revision's open issues need, and `promopilot.guardrails` still exports them;
  - `optimizer.plan_facts`.
- The domain may now import `datetime`, for `PlanDecision.decided_at`.
- There is no new configuration: the checkpointer uses `DATABASE_URL`.
- Follow-ups:
  - #45 emits trace events from these nodes;
  - #46 adds the Clarify interrupt and `awaiting_clarification`;
  - #47 and #48 put the LLM planner and the Critic loop on these edges;
  - #49 stores explanations;
  - #50 resumes a rejected or awaiting session into the Planner with an amendment;
  - E10 adds the buttons.
