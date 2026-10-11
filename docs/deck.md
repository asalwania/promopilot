---
marp: true
theme: promopilot
size: 16:9
paginate: true
footer: "PromoPilot · ET AI Hackathon 2026, Agentic Edition · claiming F3 × D2 · github.com/asalwania/promopilot"
---

<!--
PITCH DECK: 12 slides, SPEC §17. The submission form takes a PDF of at most 50 MB (SPEC §1.4, §19).
This file is the deck; `make deck` builds the PDF.

HOW TO BUILD THE PDF
1. Get the screenshots. Either
   a. download the `deck-screenshots` artifact from the latest green run of the CI `demo` job
      (GitHub, Actions, the run, Artifacts) and unzip it into `frontend/screenshots/`, or
   b. run it yourself: `make demo`, then `make screenshots` (Git Bash on Windows). Both give
      the same 1920x1080 PNGs, named as docs/deck/crops.py refers to them.
2. `make deck` (Git Bash on Windows). It cuts the slide crops with docs/deck/crops.py, then exports:
     npx -y @marp-team/marp-cli@latest docs/deck.md --pdf --html --allow-local-files --no-stdin \
         --theme-set docs/deck/theme.css -o PromoPilot-deck.pdf
   Needs Node 24 (for npx) and a local Chrome or Edge. The theme loads Geist and Source Serif 4
   from Google Fonts, so build online; offline it falls back to Segoe UI and Georgia.
3. Fill every OWNER marker (the video link on slides 1, 8 and 12). Markers are HTML comments next
   to the text they replace. Before you upload,
   grep -nE "OWN[E]R:|LA[T]E:" docs/deck.md   must print nothing.
4. Check: 12 pages, under 50 MB, every number matches `backend/evals/published/latest.md` and
   `docs/nine-blocker.md`.

NUMBERS. Every figure below is from `backend/evals/published/latest.md`: generated
2026-10-01T17:07:27Z, provider `replay` (it replays the recorded live LLM answers), seed-42 world,
33 scenarios x 1 run. Two exceptions: session time (see slide 10), and Consistency, which a
single run cannot measure: it is from `backend/evals/published/consistency.md`, the live
`make eval RUNS=5` run (provider `openai`, generated 2026-10-01T18:03:12Z, 5 scenarios x 5 runs).
The per-feature demo figures on slide 7 and the session figures on slide 8 are read off the
recorded demo sessions (the screenshots). The business-impact sums on slide 10 are the Ours and
Rule-based columns of latest.md's Plan quality table (30 rows).
CLAIM RULE (ADR 0089, docs/adr/0089-nine-blocker-claim-and-evidence-rules.md): D2 holds when most
of the 13 targeted metrics pass and constraint satisfaction, clarification, infeasibility handling
and grounding each pass or miss only narrowly with a stated cause. Every miss is listed.
-->

<!-- ============================ SLIDE 1 · Title and team ============================ -->
<!-- _class: dark -->
<!-- _paginate: false -->
<!-- _footer: "" -->

<div class="cols" style="grid-template-columns: 1.08fr 0.92fr; align-items: center; height: 100%;">
<div>
<div class="eyebrow">ET AI Hackathon · Agentic Edition · Retail – Autonomous Promotion Planner (Problem 3)</div>
<h1 style="font-size: 66px; margin: 0 0 12px; line-height: 1.05;">PromoPilot</h1>
<p class="lede" style="font-size: 21px; margin-bottom: 18px;">From a plain-English brief to an approved promotion plan.<br><b style="color: #faf9f5;">Agents decide, tools compute, humans approve.</b></p>
<p style="margin-bottom: 20px;"><span class="pill clay">Claiming F3 × D2</span>&nbsp; <span class="pill neutral">9 of 9 features</span>&nbsp; <span class="pill neutral">12 of 13 reliability targets</span>&nbsp; <span class="pill neutral">Runs with no API key</span></p>
<p style="font-size: 15px; color: #cfc9bb; margin-bottom: 18px;"><b style="color: #faf9f5;">Team ajjugotit</b> · Ajay Kumar (solo) · October 2026</p>
<div style="display: flex; align-items: center; gap: 14px;">
<img src="deck/qr-github.png" width="86" style="border-radius: 8px;">
<div style="font-size: 13.5px; color: #cfc9bb; line-height: 1.6;">
<code>github.com/asalwania/promopilot</code><br>
Demo video: link coming soon <!-- OWNER: replace "link coming soon" with the YouTube unlisted link --><br>
Run it: <code>make demo</code> · Docker only, no API key
</div>
</div>
</div>
<div><img class="shot" src="../frontend/screenshots/deck/home-hero.png" style="width: 100%;"></div>
</div>

---

<!-- ============================ SLIDE 2 · Problem statement ============================ -->

<div class="eyebrow">Problem statement · Problem 3</div>

# Promotion planning is a coupled decision, still made in spreadsheets, on gut feel and last year's calendar

<div class="cols" style="grid-template-columns: repeat(3, 1fr); margin-bottom: 18px;">
<div class="card big"><h3>Inputs</h3><p>Inventory and days of cover · competitor prices · holidays and seasonality · margins · customer segments</p></div>
<div class="card big"><h3>Decisions</h3><p>Which products · which mechanism · how deep a discount · for how long · in which regions · for whom</p></div>
<div class="card big"><h3>Constraints</h3><p>Minimum margin · marketing budget · clearance targets · stock on hand · company policy caps</p></div>
</div>

<div class="card accent" style="margin-bottom: 20px; padding: 16px 18px;"><h3 style="font-size: 17px;">The hard part: every choice moves the others</h3><p style="font-size: 15px;">A discount on one SKU pulls sales from its substitutes, lifts its complements, drains stock, invites a competitor reply and eats budget. No spreadsheet holds all of that at once, so most promotion calendars repeat last year's.</p></div>

<div class="eyebrow muted">What the organisers asked for: an agentic planner that</div>
<p><span class="pill clay">Extracts or infers its inputs</span>&nbsp; <span class="pill clay">Decides the key dimensions</span>&nbsp; <span class="pill clay">Adjusts as requirements change</span>&nbsp; <span class="pill clay">Satisfies the parent company's constraints</span></p>

---

<!-- ============================ SLIDE 3 · Proposed solution ============================ -->

<div class="eyebrow">Proposed solution</div>

# Brief in, approved plan out

<div class="cols" style="grid-template-columns: 1.3fr 0.7fr; align-items: start;">
<div>
<div class="quote">"Plan Diwali promotions for Snacks and Beverages across North and West. Budget ₹8 lakh. Keep margin above 18%. We are overstocked on 400g namkeen packs — clear at least 60% of that stock. Target families."</div>
<ol class="steps">
<li><b>Understand.</b> The Context agent turns the brief into a request, lists every assumption with its source and confidence, and asks only when a critical field is missing.</li>
<li><b>Plan.</b> The Planner agent chooses its tools: scope data, inventory, competitor gaps, demand model, relations, mechanisms, optimiser, simulator.</li>
<li><b>Check.</b> The Critic runs deterministic constraint checks and a risk review, and sends findings back to the Planner (at most 3 loops).</li>
<li><b>Explain.</b> Every line gets a rationale, and every number in it is verified against tool output.</li>
<li><b>Decide.</b> A human approves or rejects. Amendments re-plan with a diff. Approved plans keep a full audit trail.</li>
</ol>
<p class="tagline">Agents decide, tools compute, humans approve.</p>
</div>
<div>
<img class="shot" src="../frontend/screenshots/deck/trace-clean.png" style="height: 500px; width: auto; margin: 0 auto;">
<div class="cap" style="text-align: center;">The live agent trace from the recorded Diwali demo: each LLM call with its tokens and cost, each tool call with its result.</div>
</div>
</div>

---

<!-- ============================ SLIDE 4 · Agentic capability ============================ -->

<div class="eyebrow">Agentic and autonomous capability · evaluation criterion 5</div>

# It reasons, plans, uses tools, recovers from errors, and knows when to ask

<div class="cols" style="grid-template-columns: 1.3fr 0.7fr; align-items: start;">
<div class="cols" style="grid-template-columns: 1fr 1fr; gap: 14px;">
<div class="card"><h3>Chooses its own tools</h3><p>For each brief the Planner decides which deterministic tools to call and in what order: scope data, inventory status, candidate generation, competitor gaps, the CP-SAT optimiser, the simulator.</p></div>
<div class="card"><h3>Critic and Planner loop</h3><p>The Critic runs the hard-constraint checks and a risk review (heavy cannibalisation, over-concentration, clearance shortfall) and sends findings back. At most 3 loops; repeated findings go to approval as open issues instead of spinning.</p></div>
<div class="card"><h3>Recovers from errors</h3><p>An invalid tool call is corrected and retried. LLM calls retry with backoff, then fall over to the second provider. If the LLM is down, the optimiser still produces a plan.</p></div>
<div class="card"><h3>Asks only when it must</h3><p>A missing budget pauses the graph with one clarifying question. Everything else becomes an explicit assumption with its source and confidence, and nothing ships without a human approval.</p></div>
<div class="card soft" style="grid-column: 1 / -1;"><p><b>Appropriate autonomy.</b> When no plan can satisfy the brief, the agent declares it infeasible, names the binding constraints and proposes the smallest relaxation. It never approves its own plan.</p></div>
</div>
<div>
<img class="shot" src="../frontend/screenshots/deck/trace-loop.png" style="height: 500px; width: auto; margin: 0 auto;">
<div class="cap" style="text-align: center;">The Critic finds three heavy-cannibalisation lines and sends the plan back. The Planner's second attempt retries a rejected tool call, then passes.</div>
</div>
</div>

---

<!-- ============================ SLIDE 5 · Architecture ============================ -->

<div class="eyebrow">Architecture</div>

# One graph, four agents, six deterministic tools, one human gate

<div class="cols" style="grid-template-columns: 1.5fr 0.5fr; align-items: start;">
<div class="arch">
<div class="band plain">
<div class="node ghost">Brief + amendments</div><div class="arrow">→</div><div class="node">FastAPI</div><div class="arrow">→</div><div class="node">LangGraph orchestrator<small>pauses at Clarify and Approval</small></div><div class="arrow">→</div><div class="node ghost">Checkpointer<small>graph state in Postgres</small></div><div class="node ghost">Next.js UI<small>live SSE trace</small></div>
</div>
<div class="link">runs the graph ↓</div>
<div class="band agents"><div class="band-label">LLM agents decide</div>
<div class="node a">Context agent<small>request, assumptions, clarify</small></div><div class="arrow">→</div><div class="node a">Planner agent<small>choose tools, weigh trade-offs</small></div><div class="arrow">⇄<small>violations, ≤ 3 loops</small></div><div class="node a">Critic<small>constraint checks, risk review</small></div><div class="arrow">→</div><div class="node a">Explainer<small>grounded rationales</small></div><div class="arrow">→</div><div class="node h">Human approval<small>approve, reject, amend</small></div>
</div>
<div class="link">tool calls from the Planner ↓ &nbsp;·&nbsp; every number comes back from here ↑</div>
<div class="band tools"><div class="band-label">Deterministic tools compute</div>
<div class="node">Data access</div><div class="node">Demand model<small>LightGBM + elasticities</small></div><div class="node">Relations<small>substitutes, complements</small></div><div class="node">Mechanism comparator</div><div class="node">Optimiser<small>OR-Tools CP-SAT</small></div><div class="node">Simulator<small>Monte Carlo, 1,000 runs</small></div>
</div>
<div class="link">↓</div>
<div class="band plain">
<div class="node ghost">Postgres<small>synthetic world, sessions, checkpoints</small></div><div style="flex: 0 0 24px;"></div><div class="node eval">Eval harness + Oracle<small>scores every final plan</small></div><div class="arrow">⇢<small>reads</small></div><div class="node ghost">Hidden ground truth<small>only the harness may read it</small></div>
</div>
</div>
<div>
<div class="card accent" style="margin-bottom: 12px;"><h3>The LLM never computes a number</h3><p>Every figure in a plan or a rationale comes from a tested, deterministic tool. The Explainer's numbers are checked against tool output before they are shown.</p></div>
<div class="card" style="margin-bottom: 12px;"><h3>Pauses, resumes, remembers</h3><p>The graph interrupts at Clarify and Approval, and its state is checkpointed, so a session survives a restart and an amendment re-plans from where it stopped.</p></div>
<div class="card" style="margin-bottom: 12px;"><h3>Measured, not asserted</h3><p>An oracle that knows the true demand function scores every final plan against a hidden ground truth that only the eval harness may read.</p></div>
<p class="foot">Process flow, agent graph and tool contracts: <code>docs/architecture.md</code>. Its module diagram is tested against the real imports.</p>
</div>
</div>

---

<!-- ============================ SLIDE 6 · AI models and technologies ============================ -->

<div class="eyebrow">AI models and technologies</div>

# LLM agents for judgement; statistical models and a solver for every number

| Layer | What we use | What it does |
|---|---|---|
| LLM agents | OpenAI (primary) or Anthropic via `LLM_PROVIDER`, the other as fallback; **`gpt-4.1-mini` recorded the demo sessions**; LangGraph | Understand the brief, choose tools, weigh trade-offs, explain |
| Demand | LightGBM baseline forecast + hierarchical log-log promo response (own-price elasticity per SKU × segment, mechanism effects, competitor sensitivity), with standard errors | Predict units with uncertainty |
| Relations | Cross-price regression with Benjamini–Hochberg control (substitutes); basket lift (complements) | Cannibalisation and halo |
| Optimiser | OR-Tools CP-SAT | At most one promo option per SKU and region under budget, margin, stock and clearance |
| Simulator | Seeded Monte Carlo, 1,000 runs, numpy | P10 / P50 / P90 for every line and the whole plan |
| Platform | FastAPI, Postgres, Next.js, TypeScript strict, Docker, GitHub Actions | One-command demo, SSE trace, typed API |

<div class="cols" style="grid-template-columns: 1fr 1fr; margin-top: 18px;">
<div class="card accent"><h3>Replay mode: the demo needs no API key</h3><p>A <code>ReplayProvider</code> plays back the recorded LLM calls, so <code>make demo</code> runs on a fresh clone with only Docker. The optimiser and the simulator still run live; only the LLM answers are recorded.</p></div>
<div class="card accent"><h3>Seeds everywhere</h3><p>Data generation, training, simulation and evals all take an explicit seed, and structured LLM steps run at temperature 0. The same brief gives the same plan.</p></div>
</div>

---

<!-- ============================ SLIDE 7 · Feature coverage ============================ -->

<div class="eyebrow">Feature coverage · all nine, each with a demo moment and an eval metric</div>

# Nine features, nine places you can see them working

<div class="feat">
<div class="card"><div class="id">F-01</div><h3>Select products</h3><p>Plan table plus a "Not selected" list with the reason each option lost.</p><div class="demo">22 lines across North and West; SKU0033 left out as a strong substitute of SKU0035, which the plan promotes.</div></div>
<div class="card"><div class="id">F-02</div><h3>Mechanism</h3><p>% off, fixed price, BOGO and bundle compared per SKU and region.</p><div class="demo">SKU0002 North: 25% off (value ₹13,648) beats fixed price 10% (₹13,350) and BOGO 50% (₹1,370).</div></div>
<div class="card"><div class="id">F-03</div><h3>Discount and strategy</h3><p>Depth, duration and target segment per line; uplift by segment.</p><div class="demo">SKU0002 uplift: +324.6% value seekers, +274.5% families, +177.2% premium.</div></div>
<div class="card"><div class="id">F-04</div><h3>Cannibalisation</h3><p>"Promoting A reduces B's units by N%" callouts; the Critic blocks heavy cases.</p><div class="demo">Promoting SKU0002 cuts SKU0004 units by 11%. In another brief the Critic sent three lines over the 50% limit back.</div></div>
<div class="card"><div class="id">F-05</div><h3>Relationships</h3><p>Substitutes from cross-price regression, complements from basket lift; halo noted per line.</p><div class="demo">Halo flagged on SKU0017, SKU0029 and SKU0040 in North; substitutes kept apart by policy.</div></div>
<div class="card"><div class="id">F-06</div><h3>Inventory</h3><p>Stock-out risk per line; clearance targets checked against stock.</p><div class="demo">Stock-out risk 0.6% in North; 60% sell-through met on SKU0002 and SKU0006.</div></div>
<div class="card"><div class="id">F-07</div><h3>Geography</h3><p>Region tabs and a side-by-side comparison of the same SKU.</p><div class="demo">SKU0002: 25% off in North, fixed price 10% in West; 11 lines in each region.</div></div>
<div class="card"><div class="id">F-08</div><h3>Competitor</h3><p>KVI price gaps and the planner's stated response.</p><div class="demo">Three North KVIs undercut by 12.9% to 13.9%; the plan matches on one and says why not the others.</div></div>
<div class="card"><div class="id">F-09</div><h3>Simulation</h3><p>P10 to P90 band per line and plan; competitor-reaction stress test.</p><div class="demo">Gross profit ₹4.44 lakh (P10 ₹4.26, P90 ₹4.62); ₹4.34 lakh if the competitor matches half the lines.</div></div>
</div>

<p class="foot" style="margin-top: 12px;"><b>Supporting features:</b> trace timeline (observability) · retrain from the Models page (trainability) · retries and provider fallback (fault tolerance) · approval gate (human oversight) · grounded rationales (explainability).</p>

---

<!-- ============================ SLIDE 8 · Product demo ============================ -->

<div class="eyebrow">Product demo · the recorded Diwali brief, end to end, on <code>make demo</code> with no API key</div>

# Seven steps, three revisions, one approved plan

<div class="cols" style="grid-template-columns: 0.8fr 1.2fr; align-items: start;">
<div>
<ol class="steps" style="font-size: 14px;">
<li><b>Pick the brief</b> on the home page.</li>
<li><b>Watch the trace</b>: Context agent, then the Planner's tool calls, the Critic, the Explainer.</li>
<li><b>Review the assumptions</b>, each with its source and confidence; one is flagged for a look.</li>
<li><b>Read the plan per region</b>: 11 lines in North, 11 in West, with mechanism, depth and segment per SKU.</li>
<li><b>Amend</b> "Budget cut to ₹6 lakh": revision 2 with a diff. No line changed; the plan already sat inside the new budget.</li>
<li><b>Amend</b> "Drop West": revision 3. Eleven West lines removed, objective ₹59,584 to ₹30,092.</li>
<li><b>Approve</b>: the final plan with its audit trail. The whole session took 27 LLM calls and ₹9.82.</li>
</ol>
<p class="foot" style="margin-top: 12px;">Video (3:30–4:00): link coming soon <!-- OWNER: replace "link coming soon" with the YouTube unlisted link --><br>Run it yourself: <code>make demo</code>, then open <code>http://localhost:3000</code></p>
</div>
<div>
<img class="shot" src="../frontend/screenshots/deck/assumptions-inferred.png" style="width: 100%; margin-bottom: 10px;">
<img class="shot" src="../frontend/screenshots/deck/diff-budget.png" style="width: 100%; margin-bottom: 10px;">
<img class="shot" src="../frontend/screenshots/deck/audit-trail.png" style="width: 100%;">
</div>
</div>

---

<!-- ============================ SLIDE 9 · Nine-blocker claim and reliability ============================ -->

<div class="eyebrow">Nine-blocker claim and reliability evidence</div>

# We claim F3 × D2, and we measured it against hidden truth

<div class="cols" style="grid-template-columns: 0.64fr 1.36fr; align-items: start; gap: 20px;">
<div>
<div class="card" style="margin-bottom: 10px;"><h3><span class="pill clay">F3</span>&nbsp; All 9 features, plus 5 supporting ones</h3><p>F3 needs 7; two are a buffer. Each feature has code, tests, a demo moment and an eval metric (<code>docs/nine-blocker.md</code>).</p></div>
<div class="card" style="margin-bottom: 10px;"><h3><span class="pill clay">D2</span>&nbsp; Structured tables plus a free-text brief, with reliability measured</h3><p>33 scenarios in 9 groups on a seed-42 synthetic world. An oracle that knows the true demand function scores every final plan; only the eval harness may read that ground truth.</p></div>
<div class="card soft" style="margin-bottom: 10px;"><h3>Not D3</h3><p>Multimodal input (flyers, PDFs, images) is out of scope today and on the roadmap.</p></div>
<div class="card soft"><h3>Why D2 stands (ADR 0089)</h3><p>D2 is kept when most targets pass and the four critical ones (constraint satisfaction, clarification, infeasibility handling, grounding) pass. All four pass outright, and 12 of 13 targets pass. The one miss, regret, is reported with its cause. Had the targets mostly failed, we would have claimed D1.</p></div>
</div>
<div class="tight">

| Metric | Result | Target | |
|---|---|---|---|
| Constraint satisfaction | 100.0% (30 of 30) | ≥ 100% | <span class="pill pass">pass</span> |
| Oracle breach rate | 13.3% (4 of 30) | ≤ 15% | <span class="pill pass">pass</span> |
| Extraction accuracy | 100.0% (152 of 152) | ≥ 95% | <span class="pill pass">pass</span> |
| Clarification behaviour | 100.0% (3 of 3) | 100% | <span class="pill pass">pass</span> |
| Infeasibility handling | 100.0% (2 of 2) | 100% | <span class="pill pass">pass</span> |
| Grounding | 100.0% (39 of 39) | ≥ 98% | <span class="pill pass">pass</span> |
| Elasticity recovery (median abs error) | 8.1% | ≤ 20% | <span class="pill pass">pass</span> |
| Substitute precision / recall | 86.7% / 100% | ≥ 80% / ≥ 70% | <span class="pill pass">pass</span> |
| Complement precision / recall | 100% / 97.5% | ≥ 80% / ≥ 70% | <span class="pill pass">pass</span> |
| Plan quality (beats rule-based baseline) | 100.0% (30 of 30) | ≥ 90% | <span class="pill pass">pass</span> |
| **Regret (median vs best plan)** | **12.3% (12 of 29 within 10%)** | ≤ 10% | <span class="pill miss">miss</span> |
| Consistency (Jaccard over 5 runs) | 100.0% (5 of 5)* | ≥ 90% | <span class="pill pass">pass</span> |

<p class="foot" style="margin-top: 8px;">Report <code>20261001T170727Z</code>: provider <code>replay</code> (the recorded live LLM answers), 1 run each. *Consistency needs repeated runs, so it is a separate live <code>make eval RUNS=5</code> with OpenAI: 5 scenarios × 5 runs, the same SKUs selected every time. <b>The regret miss, with its cause:</b> of the 17 runs above 10%, 16 are demand-model error (the model over-values the options the optimiser picks), 1 is the planner's choice, 0 are timeouts; one more run is uncounted because its best plan was infeasible. Baseline forecast WAPE (reported, aim ≤ 25%): 13.5% at region × SKU, 25.1% at store × SKU, 43.5% at store × SKU × segment.</p>

</div>
</div>

---

<!-- ============================ SLIDE 10 · Business impact ============================ -->

<div class="eyebrow">Business impact · 30 scored plans against the rule-based baseline ("20% off the top 10 sellers")</div>

# Every plan beat the baseline, and the baseline lost money in 22 of 30 scenarios

<div class="cols" style="grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px;">
<div class="card kpi"><div class="l top">Plans that beat the baseline</div><div class="n">30 of 30</div><div class="l">Target ≥ 90%. The baseline loses money in 22 of 30 scenarios; ours in 1.</div></div>
<div class="card kpi"><div class="l top">Oracle objective, 30 plans</div><div class="n">₹28.2 lakh</div><div class="l">Incremental profit plus clearance value, against −₹11.1 lakh for the baseline. Median per scenario ₹66,540 against −₹33,885.</div></div>
<div class="card kpi"><div class="l top">Hard-constraint breaks at plan time</div><div class="n">0 of 30</div><div class="l">Under realised demand 4 of 30 breach a limit (13.3%, target ≤ 15%); plans keep a safety margin by design.</div></div>
<div class="card kpi"><div class="l top">Per plan, with a live LLM</div><div class="n">68 s · ₹3.52</div><div class="l">P50 session time and LLM cost (target ₹20). The 60 s time target is missed narrowly: close, and over.</div></div>
</div>

<div class="cols" style="grid-template-columns: 1fr 1fr; align-items: start;">
<div>
<div class="card accent" style="margin-bottom: 10px;"><h3>Clearance without breaking margin</h3><p>Clearance scenarios plan to their stock target. Where a target cannot be met (1 of 4), the plan declares it infeasible and proposes the smallest relaxation instead of shipping a broken plan.</p></div>
<div class="card"><h3>What we do not claim</h3><p>Planner time saved is not measured against spreadsheet planning. We claim the 68 seconds per plan and the measured plan quality above, nothing more.</p></div>
<p class="foot" style="margin-top: 10px;">Session time is from the live recording run of 2026-09-30; the published replay report excludes LLM time. Cost is token-based, so it holds under replay.</p>
</div>
<div><img class="shot" src="../frontend/screenshots/deck/evals-plan-quality.png" style="width: 100%;"><div class="cap">The Evals page, from the published report: plan quality, regret and consistency, with the reasons behind each count.</div></div>
</div>

---

<!-- ============================ SLIDE 11 · Scalability and responsible AI ============================ -->

<div class="eyebrow">Scalability, responsible AI and robustness · evaluation criterion 8</div>

# Human oversight by design, numbers that are checked, failures that degrade gracefully

<div class="cols" style="grid-template-columns: 1.15fr 0.85fr; align-items: start;">
<div class="cols" style="grid-template-columns: 1fr 1fr; gap: 12px;">
<div class="card"><h3>Human approval</h3><p>Nothing is final until a person approves. A rejection keeps its reason. An infeasible plan cannot be approved.</p></div>
<div class="card"><h3>Audit trail</h3><p>Every amendment, relaxation, approval and rejection is listed, oldest first, with the revision it produced.</p></div>
<div class="card"><h3>Grounding: 39 of 39</h3><p>Every number in an explanation is checked against tool output. A failed check regenerates once, then falls back to a template. Target 98%.</p></div>
<div class="card"><h3>Fault tolerance</h3><p>Retries with backoff, a fallback LLM provider, deterministic fallbacks (the optimiser runs if the LLM is down), replay mode, checkpointed state.</p></div>
<div class="card"><h3>Safe by design</h3><p>The brief is data, never instructions. Input limits, per-client rate limits, API keys redacted in logs, behavioural segments only, synthetic data with no PII.</p></div>
<div class="card"><h3>Scales per region</h3><p>One joint CP-SAT solve over region-level lines with pooled stock; candidate pruning and solver work limits keep it fast. Seeded and reproducible.</p></div>
</div>
<div>
<img class="shot" src="../frontend/screenshots/deck/infeasible.png" style="width: 100%;">
<div class="cap">When no plan can reach every clearance target, the agent says so, names the binding constraints and proposes the smallest relaxation. A person decides whether to accept it.</div>
</div>
</div>

---

<!-- ============================ SLIDE 12 · Future roadmap and links ============================ -->
<!-- _class: dark center -->

<div class="eyebrow">Future roadmap</div>

# What comes next

<div class="timeline" style="margin-bottom: 26px;">
<div class="card"><div class="eyebrow" style="margin-bottom: 6px;">Next</div><h3>Real POS data</h3><p>Swap the synthetic world for a retailer's sales, inventory and price feeds. The models, the optimiser and the eval harness are built to take them.</p></div>
<div class="card"><div class="eyebrow" style="margin-bottom: 6px;">Then</div><h3>Learning loop</h3><p>Feed realised promo results back into the elasticity and relation models: the direct answer to the regret miss, whose cause is model error in 16 of 17 runs.</p></div>
<div class="card"><div class="eyebrow" style="margin-bottom: 6px;">Then</div><h3>Consistency at scale</h3><p>Today 5 scenarios are repeated five times with a live LLM, 100% stable. Next, all 33, on every release.</p></div>
<div class="card"><div class="eyebrow" style="margin-bottom: 6px;">Later</div><h3>Multimodal inputs (D3)</h3><p>Read competitor flyers, PDFs and images into the same request. Out of scope today, which is why we claim D2.</p></div>
<div class="card"><div class="eyebrow" style="margin-bottom: 6px;">Later</div><h3>Hosted instance</h3><p>So a reviewer needs no Docker. Everything else already runs from one command.</p></div>
</div>

<div style="display: flex; align-items: center; gap: 20px; border-top: 1px solid #2f2d29; padding-top: 20px;">
<img src="deck/qr-github.png" width="104" style="border-radius: 8px;">
<div style="font-size: 15px; line-height: 1.7; color: #cfc9bb;">
<b style="color: #faf9f5;">GitHub</b> <code>github.com/asalwania/promopilot</code> · public, with README, architecture, API docs and the eval reports<br>
<b style="color: #faf9f5;">Demo video</b> link coming soon <!-- OWNER: replace "link coming soon" with the YouTube unlisted link --><br>
<b style="color: #faf9f5;">Run it</b> <code>make demo</code> (Docker only, no API key) · <b style="color: #faf9f5;">Claim and evidence</b> <code>docs/nine-blocker.md</code> · <b style="color: #faf9f5;">Architecture</b> <code>docs/architecture.md</code>
</div>
</div>
