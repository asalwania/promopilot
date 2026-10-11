# Demo video script (SPEC §18)

Target running time **3:30** (window 3:15–3:40). The submission form allows 2–4 minutes (SPEC §1.4), so **never cross 4:00**.

How this script is used (three passes):

1. **Record the screen, no audio** (Part A). Four short clips, in Hinglish, step by step.
2. **Record the voice-over separately** (Part B). Short English sentences at about 140 words a minute; every paragraph carries its video time, its screen step and its word count.
3. **Edit and merge.** Put the voice on the timeline first, then lay the clips on it by the timestamps. Cut the planning waits.

Everything on screen is a **recorded example brief** of the home page, played on `make demo` with no API key: the planner, optimiser and simulator run live, and only the LLM's answers are replayed from cassettes (ADR 0054, ADR 0073). Use only the clicks below; a brief or amendment that is not recorded shows "Not in the demo recordings".

Every eval number in the voice-over is from `backend/evals/published/latest.md` (generated 2026-10-01, 33 scenarios, seed-42 world, `replay` provider) and `consistency.md` (live run, 5 scenarios × 5 runs). Say them as written; the regret miss is said, not hidden. The only other numbers are the Diwali brief's own (₹8 lakh, 18%, 60%, ₹6 lakh), read off the screen, and "a thousand runs", which the Simulation card shows.

UI labels below are the ones in `frontend/src` after #193 (warm theme). The `make screenshots` files (`frontend/screenshots/NN-*.png`) show what each step should look like; their numbers are given in brackets.

## Timeline at a glance

| Video time | Section | Screen steps | Words |
|---|---|---|---|
| 0:00–0:10 | Introduction | 1, 2 | 21 |
| 0:10–0:31 | Problem | 2, 3 | 46 |
| 0:31–2:27 | Live demo (the Diwali demo session) | 4–18 | 267 |
| 2:27–2:48 | AI capabilities | 19, 20, 21, 7 | 47 |
| 2:48–3:01 | Key features recap + eval dashboard | 22, 23 | 27 |
| 3:01–3:21 | Business impact | 23, 24 | 47 |
| 3:21–3:34 | Closing with the GitHub link | 25 | 26 |

Total: 481 words, 3:26 of speech plus a one-second breath between sections; the closing card holds to 3:34.

## Part A: screen recording guide (Hinglish)

**Setup (recording se pehle)**

- Docker Desktop chalu karo. Git Bash kholo (Makefile PowerShell mein nahi chalta).
- Repo root mein `.env` ko rename karo (jaise `.env.live`), taaki koi API key na ho. Terminal mein bhi `OPENAI_API_KEY` set na ho. `.env` ke bina bhi `make demo` chalta hai: compose ke saare defaults hain.
- `make demo` chalao. Aakhri line yeh honi chahiye: `LLM: replaying the recorded demo sessions (no API key)`.
- Chrome mein http://localhost:3000 kholo. Home page par **Demo mode** badge dikhna chahiye ("replaying recorded sessions, no API key"). Agar **Live LLM** dikhe, to key abhi bhi kahin hai: rukko, pehle use hatao.
- Chrome: private window, 1920×1080, zoom 100%, bookmarks bar aur extensions hidden, notifications off. Light theme.
- 1920×1080 par plan table poori card mein fit hoti hai (#195 ke fix ke baad): har row ke end mein **› Details** aur **⚖ Mechanisms** dono buttons dikhne chahiye. Agar phir bhi cut dikhe, to window sach mein 1920 wide nahi hai; tab table ke andar Shift + mouse wheel se right scroll ho jaata hai.
- `₹` type karne ke liye: Win + . (period) → Symbols → ₹, ya is file se copy karo. Amendments **bilkul same text** mein honi chahiye, warna recording match nahi karegi.
- Ek baar bina record kiye poora Clip A rehearse karo. Teen planning waits (brief, budget cut, Drop West) real time mein 1–2 minute har ek lete hain; editing mein yeh cut honge.

Har step ka format: video time · kahan · kya karna hai · kitna rukna. "Ruko" ka matlab mouse hilaye bina hold karo; editor mein usi hold se timing set hogi.

### Clip A: Diwali demo, brief se approval tak (steps 2–18, ek continuous recording)

Recording start karo home page par. Beech mein kuch galat ho jaaye to **New brief** (top right) se dobara Diwali demo shuru karo; sessions har baar same replay hote hain.

2. **0:05–0:20 · Home page (01).** Page ka top dikhao: "PromoPilot", neeche **Demo mode** badge, **Try an example** ke 4 cards. Mouse mat hilao. Ruko 12 s.
3. **0:20–0:31 · Home page.** Dheere scroll karo taaki **Brief** box aur right side **Constraints (optional)** panel dikhe. Mouse **Diwali demo** card par le jaao, ruko 6 s.
4. **0:31–0:42 · Home page → session page.** **Diwali demo** card par **Try it** click karo. Brief box mein poora brief bhar jaata hai. Ruko 4 s. Phir **Plan it** click karo. Session page khulta hai: heading **Planning session**, status card **Planning…**.
5. **0:42–0:53 · Session page, Agent trace (04).** Kuch mat chhuo. Left side **Agent trace** card mein **Context agent** → **Planner** aata hai, Planner ke neeche tool calls stream hoti hain: `get_scope_data`, `get_inventory_status`, `generate_candidates`, `run_optimizer`, `get_competitor_gaps`, phir **Critic** → **Explainer** → **Approval · Paused**. Poora wait record karo (1–2 min real). Editing: is wait ko 8–16× fast karke 11 s banao, Planner ke tool calls dikhte hue.
6. **0:53–1:03 · Assumptions card (03).** Jab status **Awaiting approval** ho jaaye aur **Review plan revision 1** card dikhe, scroll karke **Assumptions** card ko top par lao. Subtitle "1 needs a look"; table mein Field / Value / Source / Confidence, aur sabse neeche **Target segment** row par **Flagged** badge. Ruko 9 s.
7. **1:03–1:19 · Plan revision 1 card (05, 06).** Scroll karke **Plan revision 1** card lao. Tabs: **North (11)** · **West (11)** · **Compare regions**. North table par ruko 6 s (columns: SKU, Mechanism, Depth, Start, Duration, Target segment, Uplift, Profit P10–P90, Stock-out risk, Promo cost, Expected incremental profit, Notes, Details). Kisi underlined number par (jaise pehli row ka Uplift **+265.2%**) mouse rakh ke 3 s ruko: tooltip "Source: …" dikhta hai (AI capabilities ke grounding wale hisse ke liye yahi shot reuse hoga). **West (11)** click karo, ruko 3 s. **Compare regions** click karo (table "Regions side by side"), ruko 4 s. Wapas **North (11)** click karo.
8. **1:19–1:37 · Plan line Details (08, 11).** North table mein teesri row **SKU0017** dhundo: uske Notes column mein **Cannibalisation** aur **Halo** dono badges hain. Row ke end mein **>** chevron (Details) click karo. Row ke neeche khulta hai: left mein **Why this line** aur **Uplift by segment** table (Segment / Units / Baseline / Uplift); right mein **Cannibalisation** box aur uske neeche **Halo** box. Ruko 15 s. (Pehli row SKU0002 mein Cannibalisation + **Undercut** hai; wo baad mein Competitor prices card mein dikhega.)
9. **1:37–1:45 · Mechanisms drawer (07).** Usi SKU0017 row mein, chevron ke paas **Mechanisms** button (scale icon) click karo. Right se drawer khulta hai: **Mechanisms for SKU0017 in North**, table Mechanism / Best option / Units / Margin / Promo cost / Incremental profit / Value, chosen mechanism par **Chosen** badge. Ruko 7 s. **Esc** dabao, drawer band.
10. **1:45–1:50 · Constraint checklist (09).** Scroll karke **Constraint checklist** card lao: "Every constraint passes", rows Budget / Minimum margin / Stock / Clearance / Policy, sab **Pass**. Ruko 5 s.
11. **1:50–1:54 · Not selected (10).** Thoda aur scroll: **Not selected** card ("The best options the optimiser left out, best first"), column **Why not selected**. Ruko 4 s.
12. **1:54–2:00 · Competitor prices (12).** Scroll: **Competitor prices** card. Table mein Flags column mein **Undercut** badges, Plan line column, aur neeche **Planner's response** bullets. Ruko 6 s.
13. **2:00–2:06 · Simulation (13).** Scroll: **Simulation** card. Header "No competitor reaction · 1000 runs, seed 0", summary tiles (Gross profit, Units, Revenue, Promo spend, Margin, Sell-through, Stock-out risk), aur **Simulated gross profit by plan line** chart (P10–P90 band + P50 line). Ruko 6 s. Re-simulate mat karo.
14. **2:06–2:10 · Amend 1.** Scroll upar **Review plan revision 1** card tak (status card ke theek neeche). **Amend the brief** box mein exactly yeh type karo: `Budget cut to ₹6 lakh`. **Amend and re-plan** click karo. Status **Planning…**; trace mein **Approval · attempt 2 → amended**, **Context agent · attempt 2**, **Planner · attempt 2** aate hain. Wait record karo (1–2 min real); editing mein cut.
15. **2:10–2:16 · Revision 2 diff (15).** Jab **Review plan revision 2** dikhe, scroll karke **Plan revision 2** card mein **What changed from plan revision 1** box lao: "After your amendment “Budget cut to ₹6 lakh”", "Marketing budget: ₹8 lakh → ₹6 lakh", Before/After table, aur **"No plan line changed."** Ruko 6 s.
16. **2:16–2:22 · Amend 2 + Revision 3 diff (16).** Upar **Review plan revision 2** mein **Amend the brief** box mein exactly: `Drop West`. **Amend and re-plan**. Wait (cut hoga). Jab **Review plan revision 3** dikhe, **What changed from plan revision 2** box lao: "Regions: North, West → North", **Removed (11)** table, "11 plan lines unchanged." Tabs ab **North (11)** · **Compare regions**. Ruko 6 s.
17. **2:22–2:25 · Approve (17).** Upar **Review plan revision 3** card: **Approve plan revision 3** click karo. Text aata hai "Approving makes plan revision 3 final…" aur **Confirm approval** button. Ruko 2 s, phir **Confirm approval** click karo.
18. **2:25–2:27 · Approved + Audit trail (18).** Status card **Approved** + **Final** badge; Agent trace ka badge **Final**. Page ke bilkul neeche scroll karo: **Audit trail** card, 3 entries (Amended plan revision 1 "Budget cut to ₹6 lakh" · Amended plan revision 2 "Drop West" · Approved plan revision 3). Ruko 5 s. Recording stop.

### Clip B: Quick Diwali push, sirf Critic ka loop (step 19)

19. **2:31–2:38 · Agent trace of the Quick Diwali push.** Home (nav mein **Home**) → **Quick Diwali push** card par **Try it** → **Plan it**. Status **Awaiting approval** hone tak wait karo (1–2 min). Ab left **Agent trace** card ke andar scroll karke yeh hissa dikhao: **Critic** ke neeche teen `risk_review` **HEAVY_CANNIBALISATION** findings, phir `loop_back` ("The Critic sends attempt 1 of 4 back to the planner with 3 findings to address."), uske neeche **Planner · attempt 2**, phir **Critic · attempt 2** ke neeche `plan_valid`. Ruko 10 s. Recording stop. (Diwali demo ka Critic pehli baar hi pass ho jaata hai, isliye self-correction yahan se dikhti hai.)

### Clip C: No budget, the agent asks (step 20)

20. **2:38–2:43 · Clarification form (02).** Home → **No budget: the agent asks** card par **Try it** → **Plan it**. Kuch seconds mein status **Awaiting clarification** aur card **The agent needs your answers** dikhta hai: sawaal "What marketing budget should the plan's promo cost stay within, in rupees?" ke saath **Missing** badge aur **Answer and resume planning** button. Left trace mein **Context agent → Asked for clarification**, **Clarify · Paused**. Ruko 8 s. Form par hi rukna; answer mat do. Recording stop.

### Clip D: Evals page (steps 23–24)

21. (Grounding shot: step 7 ka tooltip hover reuse hota hai, alag recording nahi.)
22. (Key features recap: Clip A ke 6 quick cuts, 1.5 s har ek: region tabs (step 7), Details callouts (8), Mechanisms drawer (9), Constraint checklist (10), Competitor prices (12), Simulation (13). Agar editing mein time nahi hai, sirf step 7 ka North table dheere scroll karo.)
23. **2:56–3:08 · Evals page, top (21).** Nav mein **Evals** click karo. Page: heading **Evals**, line "Generated 1 Oct 2026 … provider replay · seed-42 world · 33 scenarios × 1 run", phir **12 of 13 targets met**, aur cards: CONSTRAINTS (Constraint satisfaction 100% Pass …), AGENT BEHAVIOUR (Extraction accuracy, Clarification behaviour, Infeasibility handling, Grounding 100% Pass). Ruko 12 s.
24. **3:08–3:21 · Evals page, Plan quality + chart (22).** Dheere scroll karo PLAN QUALITY tak: **Plan quality (beats the rule-based baseline) 100% Pass**, **Regret (median, against the best plan) 12.3% Fail**, **Consistency n/a Not scored**. Ruko 7 s. Phir **Regret distribution** chart (median line 12.3%, target 10%) tak scroll, ruko 3 s, phir **Scenarios** table, ruko 3 s. Recording stop.

### Title cards (editor mein banao, record nahi karna)

1. **0:00–0:05 · Intro card.** Plain text: "PromoPilot · Autonomous Promotion Planner · [your name] · ET AI Hackathon, Problem 3". Phir step 2 (home page) par cut.
25. **3:21–3:34 · Closing card.** Plain text: "github.com/asalwania/promopilot · make demo · no API key". Agar QR code hai to saath mein. Voice khatam hone ke baad 2 s hold, phir end.

## Part B: voice-over (English)

Read at a steady pace, about 140 words a minute. Pause one second where a new section starts. Each paragraph: video time · screen steps · word count.

### Introduction · 0:00–0:10 · steps 1, 2 · 21 words

> Hi, I'm [your name]. This is PromoPilot, our entry for Problem 3: the autonomous promotion planner. Brief in, approved plan out.

### Problem · 0:10–0:31 · steps 2, 3 · 46 words

> A promotions manager plans in spreadsheets, on gut feel. Every choice pulls on the others: a discount can eat into a sister product, drain stock, and blow the budget. PromoPilot reads a plain-English brief and returns a plan a manager can approve, with the reasoning attached.

### Live demo · 0:31–2:27 · steps 4–18 · 267 words

**0:31–0:42 · step 4 · 26 words**

> The brief: eight lakh rupees, Snacks and Beverages, North and West, margin above eighteen percent, clear sixty percent of the namkeen overstock, target families. Plan it.

**0:42–0:53 · step 5 · 26 words**

> On the left, the agent trace streams live. The Context agent reads the brief. The Planner picks its own tools: inventory, candidates, the optimiser, competitor gaps.

**0:53–1:03 · step 6 · 22 words**

> Everything the agent read or assumed is listed with its source and confidence. One field is flagged for a human to check.

**1:03–1:19 · step 7 · 39 words**

> The plan is per region, line by line: which products, the mechanism, discount depth, duration, target segment, uplift, a profit range and the stock-out risk. North and West get their own lines. Compare regions puts them side by side.

**1:19–1:37 · step 8 · 40 words**

> Open a line: why it was chosen, and the uplift by segment. On the right, cannibalisation: this product pulls units from its sister product, and profit is net of that. Below it, the halo: a lift on a related product.

**1:37–1:45 · step 9 · 19 words**

> Each line's mechanisms are compared: percent off, fixed price, buy one get one, bundle. The chosen one is marked.

**1:45–1:54 · steps 10, 11 · 21 words**

> Every hard constraint is checked: budget, margin, stock, clearance, policy. All pass. And Not selected says why each rejected option lost.

**1:54–2:06 · steps 12, 13 · 29 words**

> Competitor prices: the key items where a rival undercuts us, and the planner's response. Then the simulation: a thousand runs give a profit range for every line before launch.

**2:06–2:27 · steps 14–18 · 45 words**

> Now cut the budget to six lakh. The agent re-plans and reports no line changed: the plan already fits. Then, drop West. Revision three shows exactly which lines left. Nothing is final until a person approves it. Confirm, and the audit trail records every decision.

### AI capabilities · 2:27–2:48 · steps 5 (reuse), 19, 20, 7 (tooltip reuse) · 47 words

> Four things make this agentic. Tool use: the Planner decides what to call. Self-correction: here the Critic finds heavy cannibalisation and sends the plan back; attempt two passes. Clarification: with no budget in the brief, it stops and asks. Grounding: the language model never computes a number.

Screen order for this paragraph: "Tool use" on the trace from step 5 (2:27–2:31); "Self-correction" on Clip B (2:31–2:38); "Clarification" on Clip C (2:38–2:43); "Grounding" on the tooltip hover from step 7 (2:43–2:48).

### Key features · 2:48–3:01 · steps 22, 23 · 27 words

> All nine features: product selection, mechanism, discount strategy, cannibalisation, product relationships, inventory, geography, competitor awareness and simulation. Reliability is not a claim. Here is the eval dashboard.

Cut to the Evals page (step 23) on "Here is the eval dashboard".

### Business impact · 3:01–3:21 · steps 23, 24 · 47 words

> Thirty-three scenarios against a hidden ground truth. Thirty of thirty plans beat the rule-based baseline. Every plan passes every hard constraint. In five live repeat runs, each scenario picked the same products every time. One honest miss: median regret is 12.3 percent against a target of 10.

<!-- Sources: 33 scenarios, plan quality 100% (30 of 30), constraint satisfaction 100% (30 of 30) and regret 12.3% vs ≤ 10% (fail) are from latest.md (2026-10-01T17:07:27Z); "five live repeat runs … same products every time" is consistency 100% (5 of 5), 5 runs each, from consistency.md (2026-10-01T18:03:12Z). -->

### Closing · 3:21–3:34 · step 25 · 26 words

> PromoPilot: agents decide, tools compute, humans approve. One command runs it: make demo, no API key. Code and evidence: github dot com slash asalwania slash promopilot.

### If the voice runs long

Check the voice track before editing. If it is over 3:30, drop these in order, and nothing else changes:

1. "One field is flagged for a human to check." (step 6, 9 words, about 4 s)
2. "In five live repeat runs, each scenario picked the same products every time." (step 24, 13 words, about 6 s)
3. "on gut feel" and "with the reasoning attached" (step 2, 7 words, about 3 s)

## Part C: start to finish (simple steps)

1. **Stack chalu karo.** Docker Desktop start → Git Bash → repo root → `git checkout main && git pull` (taaki #195 ka table fix image mein aaye) → `.env` rename (jaise `.env.live`) → `make demo` → wait for "LLM: replaying the recorded demo sessions (no API key)" → Chrome mein http://localhost:3000 → **Demo mode** badge confirm.
2. **Browser set karo.** Private window, 1920×1080, zoom 100%, bookmarks/extensions hidden, notifications off.
3. **Rehearse.** Clip A ek baar bina record kiye poora chalao (steps 2–18). Jahan ruk jaao, `make screenshots` ke PNG se match karo.
4. **Record Clip A** (steps 2–18): home page se approval tak, ek continuous take, bina audio. Planning waits poore record karo; baad mein cut honge.
5. **Record Clip B** (step 19): Quick Diwali push, sirf trace ka Critic loop.
6. **Record Clip C** (step 20): No budget, clarification form.
7. **Record Clip D** (steps 23–24): Evals page.
8. **Voice record karo.** Part B ko section by section padho, 140 words/min, har section ke beech 1 s ka pause. Galti ho to wahi section dobara. Phir voice track ki length check karo; 3:30 se zyada ho to "If the voice runs long" wale cuts lagao.
9. **Edit.** Timeline par pehle voice daalo. Phir Part A ke timestamps par clips rakho: title card (step 1) → Clip A → Clip B → Clip C → Clip A ke cuts (step 22) → Clip D → closing card (step 25). Planning waits ko cut karo ya 8–16× fast karo. Jahan voice kisi cheez ka naam le, waha zoom ya highlight optional hai.
10. **Check.** Total 3:15–3:40 ke beech ho; 4:00 cross na ho. Saare 9 feature moments screen par hain (steps 7, 8, 9, 10, 12, 13) aur voice mein naam aaya hai (Key features para).
11. **Export.** mp4, H.264, 1080p, 30 fps, video ~1.2 Mbps + audio 128 kbps: 3.5 min ≈ 35 MB, 50 MB limit ke andar (SPEC §19). Bada ho to 720p.
12. **Upload.** YouTube par unlisted → private window mein play check → link README ke LATE marker aur deck (slides 1, 8, 12) mein daalo → mp4 submission form mein upload.
13. **Wapas.** `make demo-down` (stack band, data rehta hai). `.env.live` ko wapas `.env` rename karo agar live key chahiye.

Screenshots for the deck and for B-roll come from the same stack: `make screenshots` writes 1920×1080 PNGs to `frontend/screenshots/`, and the CI `demo` job uploads them as the `deck-screenshots` artifact. `docs/deck.md` says how to build the PDF.
