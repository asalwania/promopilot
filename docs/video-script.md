# Demo video script (SPEC §18, 3:30–4:00)

Target running time **3:50**. The submission form takes 2–4 minutes and an mp4 under 50 MB (SPEC §1.4, §19), so do not run past 4:00. Narration is written at about 140 words a minute; the word counts below are budgets, not limits.

Everything on screen is one of the **recorded example briefs** of the home page, played on `make demo` with no API key: the planner, optimiser and simulator run live, and only the LLM's answers are replayed from cassettes (ADR 0054, ADR 0073). Anyone can reproduce every take. Do not type a brief of your own: it is not in the recordings and the demo says so.

The `/evals` numbers are from `backend/evals/published/latest.md` (generated 2026-09-30, 33 scenarios, seed-42 world). Say them as written; do not round a miss into a pass.

## Timing at a glance

| Time | Part | On screen | Words |
|---|---|---|---|
| 0:00–0:15 | Introduction | Title card, then the home page | ~35 |
| 0:15–0:40 | Problem overview | Home page, the brief | ~58 |
| 0:40–2:40 | Live product demonstration | The Diwali demo session, start to approval | ~270 |
| 2:40–3:05 | AI capabilities | Trace timeline, clarify example, grounding | ~58 |
| 3:05–3:25 | Key features | Nine-feature recap, then `/evals` | ~46 |
| 3:25–3:45 | Business impact | `/evals` numbers | ~46 |
| 3:45–4:00 | Closing summary | Title card with the GitHub link | ~35 |

Aim to end the closing at about 3:50 and let the last second of the card hold.

## Script

### 0:00–0:15 Introduction

**Screen:** title card (the home page, `01-home-example-briefs`), then a slow push-in on the brief box.

> Hi, I'm <!-- OWNER: your name -->, and this is PromoPilot, our entry for Problem 3, the autonomous promotion planner. We are claiming F3 by D2: all nine features, with reliability we measure rather than assert.

### 0:15–0:40 Problem overview

**Screen:** home page; the four example briefs; hover on the Diwali demo card.

> A promotions manager plans in spreadsheets, on gut feel and last year's calendar. Every choice pulls on the others: a discount cannibalises a sister product, drains stock, invites a competitor's reply and eats the budget. PromoPilot takes a plain-English brief and returns a plan a manager can approve, with the reasoning, the risk and the audit trail attached.

### 0:40–2:40 Live product demonstration (2:00)

Name each feature as it appears. Use the **Diwali demo** card. Work through it in this order; the sub-times are a guide.

**0:40–0:55 Brief.** Click "Try it" on **Diwali demo**; the brief fills in. Click **Plan it**.

> Here is the brief: eight lakh rupees, Snacks and Beverages in North and West, margin above 18 percent, clear sixty percent of the namkeen overstock, target families.

**0:55–1:10 Live trace (SF-01).** The session page opens; the trace timeline streams: Context agent, then Planner with its tool calls. Speed the waiting up in the edit (see "How to record").

> On the left, the agent trace streams live. The Context agent reads the brief. The Planner chooses its own tools: inventory, competitor prices, the demand model, relations, the optimiser, the simulator. Every call is logged.

**1:10–1:25 Assumptions (AG-01).** When the plan is up, scroll to the **Assumptions** panel.

> Everything the agent read or assumed is listed with its source and a confidence score. If a critical field were missing, it would ask rather than guess.

**1:25–1:50 Region plans (F-07, F-01, F-03, F-06).** Region tabs: North, then West, then **Compare regions**. Open **Details** on one line (uplift by segment). Scroll to the constraint checklist and the **Not selected** list.

> The plan is per region, line by line: mechanism, discount depth, duration, target segment, uplift, the P10 to P90 profit range and the stock-out risk. Regions sit side by side, and the same product can get a different offer in each. The checklist shows budget, margin, stock and clearance, passing or failing. And the Not selected list says why each rejected option lost.

**1:50–2:05 Cannibalisation, halo, competitor (F-04, F-05, F-08).** Open the callouts on a line (if a line shows them), then the **Competitor** panel.

> Promoting one product reduces its sister product's units by this much, and lifts its complement by that much; the plan profit is net of both. When a competitor undercuts a key value item, the planner says how it responded, and why.

**2:05–2:15 Mechanism (F-02).** Click **Compare mechanisms** on a line; show the drawer; close it.

> For each line, the simulator compares percent off, buy-one-get-one, bundle and fixed price, and the chosen one is marked.

**2:15–2:25 Simulation (F-09).** The **band chart**; "Show values"; optionally the 50 percent competitor-reaction stress test.

> Before launch, a thousand seeded Monte Carlo runs give a P10 to P90 band for profit on every line, and we can stress-test a competitor matching our discount.

**2:25–2:40 Amend and approve (AG-05, SF-04).** Type `Budget cut to ₹6 lakh` into the amend box, **Amend and re-plan**; show the diff (in the recording the plan already fits ₹6 lakh, so the diff says no plan line changed; that is the honest answer, say so). Type `Drop West`, **Amend and re-plan**; show the diff. Click **Approve**, **Confirm approval**; show the audit trail.

> Now the budget is cut to six lakh. The agent re-plans and tells us nothing needs to change, and why: the plan already fits inside six lakh. Then we drop West, and revision three shows exactly which lines left. Nothing is final until a person approves it, and the audit trail records every decision.

Type the two amendments **exactly** as written: the recordings are keyed on their text.

### 2:40–3:05 AI capabilities

**Screen:** the **Quick Diwali push** example's trace timeline, scrolled to the Critic's `loop_back` (heavy cannibalisation, attempt 1 of 4) and the Planner's second attempt (the demo brief's own Critic passes first time, so use this one for self-correction); then the "No budget: the agent asks" example up to the clarification form (`02-clarification-form`); then a plan line's rationale.

> Four things make this agentic. Tool use: the Planner decides what to call, and every call is traced. Self-correction: the Critic checks every hard constraint and reviews risk, and sends specific feedback back to the Planner, up to three times. Clarification: with no budget in the brief, it stops and asks. And grounding: the language model never computes a number. Every number in an explanation is checked against tool output, and a failed check falls back to a template.

### 3:05–3:25 Key features

**Screen:** quick cuts of the nine screens in order (`05`, `07`, `08`, `11`, `09`, `06`, `12`, `13`), then `/evals`, then `/models`.

> That was all nine features: product selection, mechanism, discount strategy, cannibalisation, relationships, inventory, geography, competitors and simulation. Behind them are the supporting features: trace, one-click retrain, fallback and replay, and the approval gate. And reliability is not a claim: here is the eval dashboard.

### 3:25–3:45 Business impact

**Screen:** `/evals`: metric cards, then the scenario table.

> We scored 33 scenarios against a hidden ground truth. Thirty of thirty plans beat the rule-based baseline; every final plan passes every hard constraint. Elasticity recovery is eight percent error, against a target of twenty. And we show our misses: grounding is 97.4 percent against 98, and median regret is 12.3 percent against 10, caused by model error, which a learning loop on real data would address.

<!-- LATE: Grounding 97.4% moves when PR #187 (Explainer grounding fix) re-records the cassettes: re-read the grounding sentence against the new backend/evals/published/latest.md before recording. -->
<!-- LATE: Consistency is n/a until a `make eval RUNS=5` run; if it has run by recording time, add one clause with its number, or leave it out. Do not say it passed before it has. -->
<!-- LATE: the 30 of 30, 8 percent (8.1%) and 12.3 percent figures come from the current latest.md: re-check all of them if it is re-published. -->

### 3:45–4:00 Closing summary

**Screen:** title card with the GitHub link and, if you have it, the QR code.

> PromoPilot: brief in, approved plan out. Agents decide, tools compute, humans approve. Run it yourself on a fresh clone with one command, make demo, no API key. The code and the evidence are at github dot com slash asalwania slash promopilot.

## How to record

You record and edit the video yourself. This is a checklist for a take that matches the script and needs no API key.

**Before you record**

1. Install Docker Desktop and start it. On Windows, run `make` from **Git Bash** (the Makefile refuses PowerShell).
2. From the repo root, `make demo` (the first build takes several minutes). It ends with `LLM: replaying the recorded demo sessions (no API key)`. Leave `OPENAI_API_KEY` empty in `.env`.
3. Open http://localhost:3000. The page should show the **Demo mode** note. If your own `.env` holds a key, the stack goes live instead; use a clean clone or clear the key.
4. Use Chrome or Edge, window at **1920×1080** (or record that region), zoom 100%, bookmarks bar and extensions hidden, a clean profile or a private window. Light theme is the one the screenshots use.
5. Turn off notifications. Close anything that shows secrets.
6. **Rehearse one full take first.** A plan takes about a minute or two of real time (the optimiser and simulator run live); you need that time on the clock when rehearsing so you know where to cut.

**Recording**

- Record the screen in one pass per section (OBS or Windows Game Bar; 1080p, 30 fps). Record the **voice-over separately** afterwards, reading the script against the picture: it is much easier to hit the timings.
- Use **only** the home page's example cards, and type the two amendments exactly (`Budget cut to ₹6 lakh`, `Drop West`). A brief or amendment that is not recorded shows "Not in the demo recordings".
- For the clarification clip, pick "No budget: the agent asks", and stop at the form (or answer `₹2 lakh`, the recorded answer).
- Re-take freely: the sessions replay the same every time. If a take shows a fallback or an error, run `docker compose exec -T api python -m promopilot.cassettes --check`: it replays every recorded session and names the request that misses.
- Between takes you can leave the stack running; `make demo-reset` wipes it clean.

**Editing**

- Speed the planning waits up 8–16× (a "Planning…" status with the trace streaming), and cut straight to the finished plan.
- Keep the demonstration section at 2:00 and the whole video under **4:00**. Check against the table at the top.
- Zoom or highlight the part named in the narration (a tooltip with its source tool, a callout, the band).
- Export **mp4, H.264, 1080p, about 1.2 Mbps video and 128 kbps audio**: that is about 40 MB for 4 minutes, under the 50 MB limit (SPEC §19). If it is bigger, export 720p.
- Upload to YouTube as **unlisted**, check it plays in a private window, and paste the link into the deck (slides 1, 8, 12) and the README.

**Screenshots for the deck and for B-roll** come from the same stack: `make screenshots` writes 1920×1080 PNGs to `frontend/screenshots/`, and the CI `demo` job uploads them as the `deck-screenshots` artifact. `docs/deck.md` says how to build the PDF.
