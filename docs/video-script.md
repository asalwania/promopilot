# Demo video script (SPEC §18)

Target running time **3:30** (window 3:15–3:40). The submission form allows 2–4 minutes (SPEC §1.4), so **never cross 4:00**.

The video is made in three passes:

1. **Record the screen, no audio** (Part A). Four short clips, step by step, written for someone opening the app for the first time.
2. **Record the voice-over separately** (Part B). Short English sentences at about 140 words a minute; every paragraph carries its video time and its word count.
3. **Edit and merge** (Part C). Put the voice on the timeline first, then lay the clips on it using the editing map at the end of Part A. Cut the planning waits.

Everything on screen is a **recorded example brief** of the home page, played on `make demo` with no API key: the planner, optimiser and simulator run live, and only the LLM's answers are replayed from cassettes (ADR 0054, ADR 0073). Use only the clicks below; a brief or amendment that is not recorded shows "Not in the demo recordings".

Every eval number in the voice-over is from `backend/evals/published/latest.md` (generated 2026-10-01, 33 scenarios, seed-42 world, `replay` provider) and `consistency.md` (live run, 5 scenarios × 5 runs). Say them as written; the regret miss is said, not hidden. The only other numbers are the Diwali brief's own (₹8 lakh, 18%, 60%, ₹6 lakh), read off the screen, and "a thousand runs", which the Simulation card shows.

UI labels below are the ones in `frontend/src` after #193 (warm theme) and #196 (the plan table fits its card at 1920×1080).

## Timeline at a glance

| Video time | Section | Screen | Voice | Words |
|---|---|---|---|---|
| 0:00–0:10 | Introduction | T1, A1 | V1 | 21 |
| 0:10–0:31 | Problem | A1, A2 | V2 | 46 |
| 0:31–2:27 | Live demo (the Diwali demo session) | A3–A21 | V3–V11 | 267 |
| 2:27–2:48 | AI capabilities | A5, B3, C2, A8 | V12 | 47 |
| 2:48–3:01 | Key features recap + eval dashboard | quick cuts, D1 | V13 | 27 |
| 3:01–3:21 | Business impact | D1–D3 | V14 | 47 |
| 3:21–3:34 | Closing with the GitHub link | T2 | V15 | 26 |

Total: 481 words, 3:26 of speech plus a one-second breath between sections; the closing card holds to 3:34.

## Part A: screen recording guide (Hinglish, pehli baar app chalane wale ke liye)

Is part mein video ke timestamps nahi hain, jaan-boojh kar: recording karte waqt sirf steps follow karo. Kaunsa step video mein kab aata hai, wo aakhri mein **Editing map** table mein hai.

### A0. Pehle app ka naksha samajh lo (2 minute)

**Home page** (http://localhost:3000), upar se neeche:

1. Sabse upar nav bar: **PromoPilot** logo, phir links **Home · Models · Data · Evals**.
2. Bada heading **PromoPilot**, uske neeche ek chhota badge **Demo mode** aur text "replaying recorded sessions, no API key". Ye badge zaroor dikhna chahiye.
3. **Try an example**: 4 cards, 2×2 mein. Har card ke right-top mein **Try it** button. Card ke naam: **Diwali demo**, **Quick Diwali push**, **No budget: the agent asks**, **Christmas, every region**.
4. Cards ke neeche **Brief** box (bada khali text area) aur uske neeche right mein orange **Plan it →** button.
5. Page ke right side mein **Constraints (optional)** panel. Isko kabhi chhuna nahi hai.

**Session page** (Plan it dabane ke baad khulta hai):

- Upar heading **Planning session**, right mein **New brief** button (isse home par wapas jaate hain).
- **Left column:** ek card **Agent trace**. Ye apne aap bharta hai: Context agent → Planner (uske neeche tool calls) → Critic → Explainer → Approval. Is card ke andar alag se scroll hota hai (mouse card ke upar rakh ke wheel).
- **Right column**, upar se neeche, isi order mein (scroll karte jaao, isi kram mein milenge):
  1. **Status card**: "Planning…" (ghoomta icon) → baad mein "Awaiting approval" → aakhri mein "Approved" + **Final** badge. Neeche brief ka text.
  2. **Review plan revision N** card: buttons **Approve plan revision N** / **Reject plan revision N**, aur neeche **Amend the brief** text box + **Amend and re-plan** button. (Ye card tabhi dikhta hai jab plan ready ho.)
  3. **LLM usage** card.
  4. **Assumptions** card (table: Field / Value / Source / Confidence).
  5. **Plan revision N** card: tabs **North (11) · West (11) · Compare regions**, phir plan table.
  6. **Constraint checklist** card.
  7. **Not selected** card.
  8. **Competitor prices** card.
  9. **Simulation** card.
  10. **Audit trail** card (sabse neeche).

**Plan table** (Plan revision card ke andar): har row ek product (SKU0002, SKU0006, …). Row ke **sabse right** mein do chhote buttons: **› Details** aur **⚖ Mechanisms**. Uske just left mein **Notes** column, jisme badges hote hain: **Cannibalisation**, **Halo**, **Undercut**. 1920×1080 par poori table dikhti hai; agar right wale buttons cut dikhen to window poori 1920 wide nahi hai.

**Wait ka matlab:** jab status card mein "Planning…" ghoom raha ho, agent kaam kar raha hai. 1–2 minute lagte hain. Us dauraan **kuch mat chhuo, scroll mat karo**. Recording chalne do; ye wait editing mein cut hoga.

**"Ruko N s" ka matlab:** mouse hilaye bina N second hold. Editing mein isi hold se timing banegi.

**Agar galti ho jaaye:** recording stop karo, **New brief** dabao, aur wo clip shuru se dobara record karo. Sessions har baar bilkul same replay hote hain, kitni bhi baar.

### A1. Setup (ek baar, recording se pehle)

1. **Docker Desktop** kholo. Neeche-left whale icon steady (green) hone tak ruko.
2. **Git Bash** kholo (PowerShell nahi), repo folder mein jaao: `cd ~/Documents/PromoPilot`.
3. `.env` file mein `OPENAI_API_KEY` wali line khali ya `#` se commented honi chahiye (abhi hai). Agar key hai, line ke aage `#` laga do.
4. Chalao: `make demo`. 2–5 minute. Aakhri lines mein yeh dikhna chahiye: `LLM: replaying the recorded demo sessions (no API key)` aur `PromoPilot is ready: http://localhost:3000`.
5. **Chrome** kholo → **Ctrl + Shift + N** (incognito window; isme bookmarks aur extensions nahi dikhte). Address bar mein http://localhost:3000.
6. Home page par **Demo mode** badge check karo. Agar **Live LLM** dikhe: ruk jao, step 3 dobara, `make demo` dobara.
7. Window **maximize** karo (screen 1920×1080 par). Zoom 100% rakho: **Ctrl + 0**.
8. Windows notifications band: **Win + A** → Do not disturb on.
9. Recording tool set karo, mic **off**:
   - Sabse simple: **Xbox Game Bar**. **Win + G** → Settings (gear) → Capturing → "Record audio" off. Band karo. Ab **Win + Alt + R** se recording start/stop hoti hai (Chrome window active honi chahiye). Files `Videos\Captures` mein jaati hain.
   - Ya OBS: Display capture, 1920×1080, 30 fps, audio sources mute.
10. `₹` type karne ke liye: **Win + .** (period) → upar **Symbols** tab → currency → ₹. Ya is file se `Budget cut to ₹6 lakh` copy kar lo. Text **bilkul same** hona chahiye, warna recording match nahi karegi.
11. **Ek baar bina record kiye Clip A poora chalao** (A2–A21). Isse pata chal jaayega ki har cheez kahan hai. Phir **New brief** dabao aur asli recording shuru karo.

### A2. Clip A: Diwali demo, home se approval tak (ek continuous recording, ~7 minute real time)

Shuru: home page, page ka sabse upar, mouse kone mein. **Win + Alt + R** (recording start).

**A1 · Home page, top.** Kuch mat karo. **Ruko 12 s.**

**A2 · Thoda neeche scroll.** Mouse wheel 2–3 click neeche, jab tak **Brief** box poora dikhe (4 cards bhi dikhte rahen). Mouse **Diwali demo** card par le jaao. **Ruko 6 s.**

**A3 · "Try it" click.** **Diwali demo** card ke **Try it** button par click. *Dikhega:* Brief box mein lamba text bhar gaya: "Plan Diwali promotions for Snacks and Beverages across North and West. Budget ₹8 lakh. …". **Ruko 4 s.**

**A4 · "Plan it →" click.** Brief box ke neeche right wala orange button. *Dikhega:* naya page, heading **Planning session**; status card mein **Planning…**; left mein **Agent trace** bharne lagta hai.

**A5 · Wait.** Kuch mat chhuo, scroll mat karo, mouse mat hilao. 1–2 minute. *Dikhega:* Agent trace mein Context agent, phir Planner ke neeche `get_scope_data`, `get_inventory_status`, `generate_candidates`, `run_optimizer`, `get_competitor_gaps`, phir Critic, Explainer, Approval. Jab status card **Awaiting approval** ho jaaye aur uske neeche **Review plan revision 1** card aa jaaye, tab aage badho.

**A6 · Assumptions.** Mouse wheel se neeche scroll karo. Pehle **Review plan revision 1**, phir **LLM usage**, phir **Assumptions** card aayega. Scroll aise rok do ki **Assumptions** heading screen ke upar ke hisse mein ho. *Dikhega:* "1 needs a look", table, sabse neeche **Target segment** row par laal-sa **Flagged** badge. **Ruko 9 s.**

**A7 · Plan revision 1.** Aur neeche scroll: **Plan revision 1** card. Tabs **North (11) · West (11) · Compare regions** aur neeche table. Tabs screen ke upar rakho, table poori dikhe (right end mein **› Details** aur **⚖ Mechanisms**). **Ruko 6 s.**

**A8 · Hover (tooltip).** Pehli row (SKU0002) mein **Uplift** column ka number (+265.2%) hai. Us par mouse le jaao aur **hilao mat**. 1–2 s baad chhota tooltip aata hai: "Source: …". **Ruko 3 s** (tooltip ke saath).

**A9 · Tabs.** **West (11)** tab click → **ruko 3 s**. **Compare regions** click (table "Regions side by side") → **ruko 4 s**. Wapas **North (11)** click.

**A10 · Details.** Teesri row **SKU0017** dhundo: uske **Notes** mein do badges hain, **Cannibalisation** aur **Halo**. Us row ke sabse right mein **› Details** par click. *Dikhega:* row ke neeche ek section khulta hai: left mein **Why this line** aur **Uplift by segment** table; right mein ek peela box **Cannibalisation** aur uske neeche hara box **Halo**. **Ruko 15 s.**

**A11 · Mechanisms.** Usi SKU0017 row mein, **› Details** ke right mein **⚖ Mechanisms** par click. *Dikhega:* right se ek panel khulta hai, heading **Mechanisms for SKU0017 in North**, ek table jisme ek row par **Chosen** badge. **Ruko 7 s.** Phir keyboard par **Esc** dabao: panel band.

**A12 · Constraint checklist.** Neeche scroll: **Constraint checklist** card ("Every constraint passes", 5 rows sab **Pass**). **Ruko 5 s.**

**A13 · Not selected.** Thoda aur neeche: **Not selected** card. **Ruko 4 s.**

**A14 · Competitor prices.** Aur neeche: **Competitor prices** card: table (kuch rows par laal **Undercut** badge) aur uske neeche **Planner's response** bullets. Table aur bullets dono dikhen. **Ruko 6 s.**

**A15 · Simulation.** Aur neeche: **Simulation** card: 8 chhote tiles (Gross profit, Units, …) aur neeche chart **Simulated gross profit by plan line**. Tiles aur chart dono dikhen. **Ruko 6 s.** Isme kuch click mat karo (**Re-simulate** mat dabao).

**A16 · Amend 1.** Ab upar wapas jaao (keyboard **Home** key, ya wheel upar) jab tak **Review plan revision 1** card dikhe (status card ke theek neeche). Usme **Amend the brief** box par click karo aur type karo, bilkul yeh: `Budget cut to ₹6 lakh`. Phir **Amend and re-plan** click. *Dikhega:* status **Planning…**; Review card gayab; left trace mein "Approval · attempt 2", "Context agent · attempt 2", "Planner · attempt 2" aate hain. **Wait 1–2 min, kuch mat chhuo**, jab tak **Review plan revision 2** card aa jaaye.

**A17 · Revision 2 ka diff.** Neeche scroll **Plan revision 2** card tak. Card ke upar hi ek box hai **What changed from plan revision 1**: "After your amendment “Budget cut to ₹6 lakh”", "Marketing budget: ₹8 lakh → ₹6 lakh", chhoti Before/After table, aur line **No plan line changed.** Ye box poora dikhe. **Ruko 6 s.**

**A18 · Amend 2.** Upar wapas **Review plan revision 2** card. **Amend the brief** box mein type: `Drop West`. **Amend and re-plan** click. **Wait 1–2 min**, jab tak **Review plan revision 3** aa jaaye.

**A19 · Revision 3 ka diff.** Neeche scroll **Plan revision 3** card tak. Box **What changed from plan revision 2**: "Regions: North, West → North", table **Removed (11)**. Tabs ab sirf **North (11) · Compare regions**. **Ruko 6 s.**

**A20 · Approve.** Upar wapas **Review plan revision 3** card. **Approve plan revision 3** click. *Dikhega:* text "Approving makes plan revision 3 final…" aur naya button **Confirm approval**. **Ruko 2 s.** **Confirm approval** click. *Dikhega:* status card **Approved** aur **Final** badge; left trace ka badge bhi **Final**.

**A21 · Audit trail.** Page ke bilkul neeche scroll (keyboard **End**): **Audit trail** card, 3 lines (Amended plan revision 1 "Budget cut to ₹6 lakh" · Amended plan revision 2 "Drop West" · Approved plan revision 3). **Ruko 5 s.** **Win + Alt + R** (recording stop).

### A3. Clip B: Quick Diwali push, sirf Critic ka loop (~3 minute real time)

Ye isliye alag hai kyunki Diwali demo mein Critic pehli baar hi pass ho jaata hai; self-correction is session mein dikhti hai.

**B1 · Home par jaao.** Upar right **New brief** click (ya nav mein **Home**). Home page top. **Win + Alt + R** (recording start).

**B2 · Plan.** **Quick Diwali push** card ke **Try it** click → brief bhar jaata hai → **Plan it →** click. **Wait 1–2 min** jab tak status **Awaiting approval**.

**B3 · Trace mein Critic dikhao.** Mouse ko left **Agent trace** card ke upar rakho aur wheel se card ke andar scroll karo. Dhundo: **Critic** heading, uske neeche teen warning lines **risk_review HEAVY_CANNIBALISATION** (har ek ke neeche 2–3 line text), phir **loop_back** ("The Critic sends attempt 1 of 4 back to the planner with 3 findings to address."), uske neeche **Planner · attempt 2**, aur phir **Critic · attempt 2** ke neeche **plan_valid**. Scroll aise rakho ki **loop_back** card ke beech mein ho. **Ruko 10 s.** **Win + Alt + R** (stop).

### A4. Clip C: No budget, the agent asks (~1 minute real time)

**C1 · Home → plan.** **New brief** → home. **Win + Alt + R** (start). **No budget: the agent asks** card ke **Try it** → **Plan it →**.

**C2 · Clarification form.** Kuch seconds mein status card **Awaiting clarification**, aur uske neeche card **The agent needs your answers**: sawaal "What marketing budget should the plan's promo cost stay within, in rupees?", right mein **Missing** badge, khali box, aur button **Answer and resume planning**. Left trace mein "Context agent → Asked for clarification" aur "Clarify · Paused". **Ruko 8 s.** Kuch type mat karo, answer mat do. **Win + Alt + R** (stop).

### A5. Clip D: Evals page (~1 minute real time)

**D1 · Evals, top.** Nav mein **Evals** click. **Win + Alt + R** (start). Page ka top: heading **Evals**, line "Generated 1 Oct 2026 … provider replay · seed-42 world · 33 scenarios × 1 run", phir **12 of 13 targets met**, phir cards (CONSTRAINTS, AGENT BEHAVIOUR). **Ruko 12 s.**

**D2 · Plan quality.** Dheere scroll neeche **PLAN QUALITY** section tak: **Plan quality (beats the rule-based baseline) 100% Pass**, **Regret (median, against the best plan) 12.3% Fail**, **Consistency n/a Not scored**. **Ruko 7 s.**

**D3 · Chart aur table.** Aur neeche **Regret distribution** chart (bars, ek line Median 12.3%, dotted Target ≤ 10%). **Ruko 3 s.** Aur neeche **Scenarios** table. **Ruko 3 s.** **Win + Alt + R** (stop).

### A6. Title cards (record nahi karne; editor mein text slide banao)

**T1 · Intro card (0:00–0:05):** "PromoPilot · Autonomous Promotion Planner · [your name] · ET AI Hackathon, Problem 3".

**T2 · Closing card (3:21–3:34):** "github.com/asalwania/promopilot · make demo · no API key". Agar QR code hai to saath mein. Voice khatam hone ke baad 2 s hold.

### A7. Editing map (kaunsa step video mein kab, kis voice para ke saath)

| Video time | Screen (step) | Voice para | Note |
|---|---|---|---|
| 0:00–0:05 | T1 | V1 | |
| 0:05–0:10 | A1 | V1 | |
| 0:10–0:31 | A1 → A2 | V2 | |
| 0:31–0:42 | A3, A4 | V3 | |
| 0:42–0:53 | A5 | V4 | wait ko 8–16× fast karo, 11 s banao |
| 0:53–1:03 | A6 | V5 | |
| 1:03–1:19 | A7, A9 | V6 | |
| 1:19–1:37 | A10 | V7 | |
| 1:37–1:45 | A11 | V8 | |
| 1:45–1:54 | A12, A13 | V9 | |
| 1:54–2:06 | A14, A15 | V10 | |
| 2:06–2:27 | A16 → A21 | V11 | dono waits cut |
| 2:27–2:31 | A5 (trace close-up, dobara) | V12 "Tool use" | |
| 2:31–2:38 | B3 | V12 "Self-correction" | |
| 2:38–2:43 | C2 | V12 "Clarification" | |
| 2:43–2:48 | A8 (tooltip) | V12 "Grounding" | |
| 2:48–2:56 | quick cuts: A7, A10, A11, A12, A14, A15 (~1.3 s each) | V13 | time nahi hai to sirf A7 |
| 2:56–3:01 | D1 | V13 "Here is the eval dashboard" | |
| 3:01–3:08 | D1 | V14 | |
| 3:08–3:21 | D2, D3 | V14 | |
| 3:21–3:34 | T2 | V15 | 2 s hold at the end |

## Part B: voice-over (English)

Read at a steady pace, about 140 words a minute. Pause one second where a new section starts. Each paragraph: video time · screen · word count.

### V1 · Introduction · 0:00–0:10 · T1, A1 · 21 words

> Hi, I'm [your name]. This is PromoPilot, our entry for Problem 3: the autonomous promotion planner. Brief in, approved plan out.

### V2 · Problem · 0:10–0:31 · A1, A2 · 46 words

> A promotions manager plans in spreadsheets, on gut feel. Every choice pulls on the others: a discount can eat into a sister product, drain stock, and blow the budget. PromoPilot reads a plain-English brief and returns a plan a manager can approve, with the reasoning attached.

### Live demo · 0:31–2:27 · A3–A21 · 267 words

**V3 · 0:31–0:42 · A3, A4 · 26 words**

> The brief: eight lakh rupees, Snacks and Beverages, North and West, margin above eighteen percent, clear sixty percent of the namkeen overstock, target families. Plan it.

**V4 · 0:42–0:53 · A5 · 26 words**

> On the left, the agent trace streams live. The Context agent reads the brief. The Planner picks its own tools: inventory, candidates, the optimiser, competitor gaps.

**V5 · 0:53–1:03 · A6 · 22 words**

> Everything the agent read or assumed is listed with its source and confidence. One field is flagged for a human to check.

**V6 · 1:03–1:19 · A7, A9 · 39 words**

> The plan is per region, line by line: which products, the mechanism, discount depth, duration, target segment, uplift, a profit range and the stock-out risk. North and West get their own lines. Compare regions puts them side by side.

**V7 · 1:19–1:37 · A10 · 40 words**

> Open a line: why it was chosen, and the uplift by segment. On the right, cannibalisation: this product pulls units from its sister product, and profit is net of that. Below it, the halo: a lift on a related product.

**V8 · 1:37–1:45 · A11 · 19 words**

> Each line's mechanisms are compared: percent off, fixed price, buy one get one, bundle. The chosen one is marked.

**V9 · 1:45–1:54 · A12, A13 · 21 words**

> Every hard constraint is checked: budget, margin, stock, clearance, policy. All pass. And Not selected says why each rejected option lost.

**V10 · 1:54–2:06 · A14, A15 · 29 words**

> Competitor prices: the key items where a rival undercuts us, and the planner's response. Then the simulation: a thousand runs give a profit range for every line before launch.

**V11 · 2:06–2:27 · A16–A21 · 45 words**

> Now cut the budget to six lakh. The agent re-plans and reports no line changed: the plan already fits. Then, drop West. Revision three shows exactly which lines left. Nothing is final until a person approves it. Confirm, and the audit trail records every decision.

### V12 · AI capabilities · 2:27–2:48 · A5, B3, C2, A8 · 47 words

> Four things make this agentic. Tool use: the Planner decides what to call. Self-correction: here the Critic finds heavy cannibalisation and sends the plan back; attempt two passes. Clarification: with no budget in the brief, it stops and asks. Grounding: the language model never computes a number.

Screen order: "Tool use" on the trace from A5 (2:27–2:31); "Self-correction" on B3 (2:31–2:38); "Clarification" on C2 (2:38–2:43); "Grounding" on the tooltip from A8 (2:43–2:48).

### V13 · Key features · 2:48–3:01 · quick cuts, D1 · 27 words

> All nine features: product selection, mechanism, discount strategy, cannibalisation, product relationships, inventory, geography, competitor awareness and simulation. Reliability is not a claim. Here is the eval dashboard.

Cut to the Evals page (D1) on "Here is the eval dashboard".

### V14 · Business impact · 3:01–3:21 · D1–D3 · 47 words

> Thirty-three scenarios against a hidden ground truth. Thirty of thirty plans beat the rule-based baseline. Every plan passes every hard constraint. In five live repeat runs, each scenario picked the same products every time. One honest miss: median regret is 12.3 percent against a target of 10.

<!-- Sources: 33 scenarios, plan quality 100% (30 of 30), constraint satisfaction 100% (30 of 30) and regret 12.3% vs ≤ 10% (fail) are from latest.md (2026-10-01T17:07:27Z); "five live repeat runs … same products every time" is consistency 100% (5 of 5), 5 runs each, from consistency.md (2026-10-01T18:03:12Z). -->

### V15 · Closing · 3:21–3:34 · T2 · 26 words

> PromoPilot: agents decide, tools compute, humans approve. One command runs it: make demo, no API key. Code and evidence: github dot com slash asalwania slash promopilot.

### If the voice runs long

Check the voice track before editing. If it is over 3:30, drop these in order, and nothing else changes:

1. V5: "One field is flagged for a human to check." (9 words, about 4 s)
2. V14: "In five live repeat runs, each scenario picked the same products every time." (13 words, about 6 s)
3. V2: "on gut feel" and "with the reasoning attached" (7 words, about 3 s)

## Part C: start to finish (simple steps)

1. **Stack chalu karo** (Part A, A1 steps 1–6): Docker Desktop → Git Bash → `cd ~/Documents/PromoPilot` → `.env` mein key commented → `make demo` → Chrome incognito → http://localhost:3000 → **Demo mode** badge.
2. **Screen aur recorder set karo** (A1 steps 7–10): maximize, zoom 100%, notifications off, Game Bar mic off, ₹ ka tareeka.
3. **Rehearse** (A1 step 11): Clip A bina record kiye ek baar.
4. **Record Clip A** (A2): home se approval tak, ek take, bina audio. Waits poore record karo.
5. **Record Clip B** (A3): Quick Diwali push, Critic loop.
6. **Record Clip C** (A4): No budget form.
7. **Record Clip D** (A5): Evals page.
8. **Voice record karo** (Part B): V1 se V15, section ke beech 1 s pause. Galti ho to wahi para dobara. Length check: 3:30 se zyada ho to "If the voice runs long" ke cuts.
9. **Edit** (A7 editing map): timeline par pehle voice, phir clips map ke time par; T1 aur T2 text slides; planning waits cut ya 8–16× fast.
10. **Check:** total 3:15–3:40; 4:00 cross na ho; 9 features screen par (A7, A10, A11, A12, A14, A15) aur V13 mein naam.
11. **Export:** mp4, H.264, 1080p, 30 fps, video ~1.2 Mbps + audio 128 kbps: 3.5 min ≈ 35 MB (limit 50 MB, SPEC §19). Bada ho to 720p.
12. **Upload:** YouTube unlisted → private window mein play check → link README ke LATE marker aur deck slides 1, 8, 12 mein → `make deck` → mp4 form mein upload.
13. **Baad mein:** `make demo-down` (stack band, data rehta hai).

Screenshots for the deck and for B-roll come from the same stack: `make screenshots` writes 1920×1080 PNGs to `frontend/screenshots/`, and the CI `demo` job uploads them as the `deck-screenshots` artifact. `docs/deck.md` says how to build the PDF.
