# Demo video script (SPEC §18)

Target running time **3:30** (window 3:15–3:40). The submission form allows 2–4 minutes (SPEC §1.4), so **never cross 4:00**.

The video is made in three passes:

1. **Record the screen, no audio** (Part A). Four short clips, step by step, written for someone opening the app for the first time.
2. **Record the voice-over separately** (Part B). Part B holds only the words to say: 24 short paragraphs, one per screen, in plain English.
3. **Edit and merge** (Part C). Put the voice on the timeline first, then lay the clips on it with the editing map at the end of Part A: paragraph N of the voice goes with screen step N of the map. Cut the planning waits.

Everything on screen is a **recorded example brief** of the home page, played on `make demo` with no API key: the planner, optimiser and simulator run live, and only the LLM's answers are replayed from cassettes (ADR 0054, ADR 0073). Use only the clicks below; a brief or amendment that is not recorded shows "Not in the demo recordings".

Every eval number in the voice-over is on the Evals page and in `backend/evals/published/latest.md` (generated 2026-10-01, 33 scenarios, seed-42 world, `replay` provider): 33 scenarios, 12 of 13 targets met, plan quality 30 of 30, constraint satisfaction 30 of 30, median regret 12.3% against a target of ≤ 10% (said as a miss, not hidden). Consistency (5 of 5 in `consistency.md`, a live run) is **not** spoken: the Evals page shows it as "Not scored" under replay, and the voice must never contradict the screen; it stays in `nine-blocker.md` and the deck. The only other numbers are the Diwali brief's own (₹8 lakh, 18%, ₹6 lakh), read off the screen, and "a thousand times", which the Simulation card shows as 1000 runs.

UI labels below are the ones in `frontend/src` after #193 (warm theme) and #196 (the plan table fits its card at 1920×1080).

## Timeline at a glance

Times assume 130 words a minute with a short breath after each paragraph. The voice recording is the master: when it is slower or faster, the clips move with it (Part C, step 8).

| Target time | Section | Screen | Voice paragraphs | Words |
|---|---|---|---|---|
| 0:00–0:12 | Introduction | T1, A1 | 1 | 25 |
| 0:12–0:28 | Problem | A1, A2 | 2 | 33 |
| 0:28–2:20 | Live demo (the Diwali demo session) | A3–A21 | 3–16 | 227 |
| 2:20–2:48 | AI capabilities | A5, B3, C2, A8 | 17–20 | 57 |
| 2:48–3:05 | Key features recap + eval dashboard | quick cuts, D1 | 21–22 | 36 |
| 3:05–3:18 | Business impact | D2, D3 | 23 | 25 |
| 3:18–3:29 | Closing with the GitHub link | T2 | 24 | 23 |

Total: 426 words. At 130 words a minute that is 3:29 of voice; the closing card holds two more seconds, so the video ends at about 3:31. At 140 it is 3:15, at 120 it is 3:45 (then use the cuts in Part C, step 8).

## Part A: screen recording guide (Hinglish, pehli baar app chalane wale ke liye)

Is part mein video ke timestamps nahi hain, jaan-boojh kar: recording karte waqt sirf steps follow karo. Kaunsa step video mein kab aata hai aur kis voice paragraph ke saath, wo aakhri mein **A7 Editing map** table mein hai.

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

**"Ruko N s" ka matlab:** mouse hilaye bina N second hold. Har hold us screen ke voice paragraph se 2–3 s lamba rakha hai; editing mein extra kat jaata hai, kam pad jaaye to nahi badh sakta. Isliye **kam mat ruko, zyada ruk sakte ho.**

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

**A1 · Home page, top.** Kuch mat karo. **Ruko 15 s.**

**A2 · Thoda neeche scroll.** Mouse wheel 2–3 click neeche, jab tak **Brief** box poora dikhe (4 cards bhi dikhte rahen). Mouse **Diwali demo** card par le jaao. **Ruko 12 s.**

**A3 · "Try it" click.** **Diwali demo** card ke **Try it** button par click. *Dikhega:* Brief box mein lamba text bhar gaya: "Plan Diwali promotions for Snacks and Beverages across North and West. Budget ₹8 lakh. …". **Ruko 6 s.**

**A4 · "Plan it →" click.** Brief box ke neeche right wala orange button. *Dikhega:* naya page, heading **Planning session**; status card mein **Planning…**; left mein **Agent trace** bharne lagta hai.

**A5 · Wait.** Kuch mat chhuo, scroll mat karo, mouse mat hilao. 1–2 minute. *Dikhega:* Agent trace mein Context agent, phir Planner ke neeche `get_scope_data`, `get_inventory_status`, `generate_candidates`, `run_optimizer`, `get_competitor_gaps`, phir Critic, Explainer, Approval. Jab status card **Awaiting approval** ho jaaye aur uske neeche **Review plan revision 1** card aa jaaye, tab aage badho.

**A6 · Assumptions.** Mouse wheel se neeche scroll karo. Pehle **Review plan revision 1**, phir **LLM usage**, phir **Assumptions** card aayega. Scroll aise rok do ki **Assumptions** heading screen ke upar ke hisse mein ho. *Dikhega:* "1 needs a look", table, sabse neeche **Target segment** row par laal-sa **Flagged** badge. **Ruko 12 s.**

**A7 · Plan revision 1.** Aur neeche scroll: **Plan revision 1** card. Tabs **North (11) · West (11) · Compare regions** aur neeche table. Tabs screen ke upar rakho, table poori dikhe (right end mein **› Details** aur **⚖ Mechanisms**). **Ruko 10 s.**

**A8 · Hover (tooltip).** Pehli row (SKU0002) mein **Uplift** column ka number (+265.2%) hai. Us par mouse le jaao aur **hilao mat**. 1–2 s baad chhota tooltip aata hai: "Source: …". **Ruko 8 s** (tooltip ke saath). Phir mouse table se bahar le jaao.

**A9 · Tabs.** **West (11)** tab click → **ruko 4 s**. **Compare regions** click (table "Regions side by side") → **ruko 5 s**. Wapas **North (11)** click.

**A10 · Details.** Teesri row **SKU0017** dhundo: uske **Notes** mein do badges hain, **Cannibalisation** aur **Halo**. Us row ke sabse right mein **› Details** par click. *Dikhega:* row ke neeche ek section khulta hai: left mein **Why this line** aur **Uplift by segment** table; right mein ek peela box **Cannibalisation** aur uske neeche hara box **Halo**. **Ruko 18 s.**

**A11 · Mechanisms.** Usi SKU0017 row mein, **› Details** ke right mein **⚖ Mechanisms** par click. *Dikhega:* right se ek panel khulta hai, heading **Mechanisms for SKU0017 in North**, ek table jisme ek row par **Chosen** badge. **Ruko 8 s.** Phir keyboard par **Esc** dabao: panel band.

**A12 · Constraint checklist.** Neeche scroll: **Constraint checklist** card ("Every constraint passes", 5 rows **Budget · Minimum margin · Stock · Clearance · Policy**, sab **Pass**). **Ruko 7 s.**

**A13 · Not selected.** Thoda aur neeche: **Not selected** card. **Ruko 6 s.**

**A14 · Competitor prices.** Aur neeche: **Competitor prices** card: table (kuch rows par laal **Undercut** badge) aur uske neeche **Planner's response** bullets. Table aur bullets dono dikhen. **Ruko 7 s.**

**A15 · Simulation.** Aur neeche: **Simulation** card: 8 chhote tiles (Gross profit, Units, …) aur neeche chart **Simulated gross profit by plan line**. Tiles aur chart dono dikhen. **Ruko 9 s.** Isme kuch click mat karo (**Re-simulate** mat dabao).

**A16 · Amend 1.** Ab upar wapas jaao (keyboard **Home** key, ya wheel upar) jab tak **Review plan revision 1** card dikhe (status card ke theek neeche). Usme **Amend the brief** box par click karo aur type karo, bilkul yeh: `Budget cut to ₹6 lakh`. Phir **Amend and re-plan** click. *Dikhega:* status **Planning…**; Review card gayab; left trace mein "Approval · attempt 2", "Context agent · attempt 2", "Planner · attempt 2" aate hain. **Wait 1–2 min, kuch mat chhuo**, jab tak **Review plan revision 2** card aa jaaye.

**A17 · Revision 2 ka diff.** Neeche scroll **Plan revision 2** card tak. Card ke upar hi ek box hai **What changed from plan revision 1**: "After your amendment “Budget cut to ₹6 lakh”", "Marketing budget: ₹8 lakh → ₹6 lakh", chhoti Before/After table, aur line **No plan line changed.** Ye box poora dikhe. **Ruko 7 s.**

**A18 · Amend 2.** Upar wapas **Review plan revision 2** card. **Amend the brief** box mein type: `Drop West`. **Amend and re-plan** click. **Wait 1–2 min**, jab tak **Review plan revision 3** aa jaaye.

**A19 · Revision 3 ka diff.** Neeche scroll **Plan revision 3** card tak. Box **What changed from plan revision 2**: "Regions: North, West → North", table **Removed (11)**. Tabs ab sirf **North (11) · Compare regions**. **Ruko 7 s.**

**A20 · Approve.** Upar wapas **Review plan revision 3** card. **Approve plan revision 3** click. *Dikhega:* text "Approving makes plan revision 3 final…" aur naya button **Confirm approval**. **Ruko 2 s.** **Confirm approval** click. *Dikhega:* status card **Approved** aur **Final** badge; left trace ka badge bhi **Final**.

**A21 · Audit trail.** Page ke bilkul neeche scroll (keyboard **End**): **Audit trail** card, 3 lines (Amended plan revision 1 "Budget cut to ₹6 lakh" · Amended plan revision 2 "Drop West" · Approved plan revision 3). **Ruko 6 s.** **Win + Alt + R** (recording stop).

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

**D2 · Plan quality.** Dheere scroll neeche **PLAN QUALITY** section tak: **Plan quality (beats the rule-based baseline) 100% Pass**, **Regret (median, against the best plan) 12.3% Fail**, **Consistency n/a Not scored**. **Ruko 8 s.**

**D3 · Chart aur table.** Aur neeche **Regret distribution** chart (bars, ek line Median 12.3%, dotted Target ≤ 10%). **Ruko 4 s.** Aur neeche **Scenarios** table. **Ruko 4 s.** **Win + Alt + R** (stop).

### A6. Title cards (record nahi karne; editor mein text slide banao)

**T1 · Intro card (0:00–0:05):** "PromoPilot · Autonomous Promotion Planner · [your name] · ET AI Hackathon, Problem 3 · F3 × D2".

**T2 · Closing card (3:18–3:31):** "github.com/asalwania/promopilot · make demo · no API key". Agar QR code hai to saath mein. Voice khatam hone ke baad 2 s hold.

### A7. Editing map (voice paragraph N = screen step; ek paragraph, ek screen)

Timeline par pehle voice daalo. Phir har paragraph jahan shuru hota hai, wahan uska clip rakho. Target time 130 words/minute par hai; asli time voice se lo.

| Voice para | Target time | Screen (step) | Note |
|---|---|---|---|
| 1 | 0:00–0:12 | T1 (0:00–0:05), phir A1 | |
| 2 | 0:12–0:28 | A1 → A2 | |
| 3 | 0:28–0:39 | A3, A4 | |
| 4 | 0:39–0:49 | A5 | wait ko 8–16× fast karo, ~10 s banao |
| 5 | 0:49–0:57 | A6 | |
| 6 | 0:57–1:05 | A7 | A8 (tooltip) yahan se kaat lo; wo para 20 mein lagega |
| 7 | 1:05–1:12 | A9 | |
| 8 | 1:12–1:27 | A10 | |
| 9 | 1:27–1:33 | A11 | |
| 10 | 1:33–1:39 | A12 | |
| 11 | 1:39–1:43 | A13 | |
| 12 | 1:43–1:49 | A14 | |
| 13 | 1:49–1:57 | A15 | |
| 14 | 1:57–2:06 | A16 → A17 | typing dikhao, wait cut |
| 15 | 2:06–2:12 | A18 → A19 | wait cut |
| 16 | 2:12–2:20 | A20 → A21 | |
| 17 | 2:20–2:27 | A5 (trace close-up, dobara, normal speed) | |
| 18 | 2:27–2:34 | B3 | |
| 19 | 2:34–2:41 | C2 | |
| 20 | 2:41–2:48 | A8 (tooltip) | |
| 21 | 2:48–2:56 | quick cuts: A7, A10, A11, A12, A14, A15 (~1.3 s each) | time nahi hai to sirf A7 |
| 22 | 2:56–3:05 | D1 | |
| 23 | 3:05–3:18 | D2 → D3 | |
| 24 | 3:18–3:29 | T2 | voice ke baad 2 s hold |

## Part B: voice-over (sirf yeh bolna hai)

1. Hi, my name is ______. This is PromoPilot, our entry for Problem three. Give it a brief. It gives back a plan you can approve.

2. Today, promotions are planned in spreadsheets. One discount can take sales from a sister product, empty the stock, and break the budget. PromoPilot turns a short brief into a full plan, with reasons.

3. The brief: eight lakh rupees, Snacks and Beverages, North and West, margin above eighteen percent, clear the extra namkeen stock, target families. Plan it.

4. On the left, the agent trace runs live. The Context agent reads the brief. The Planner picks its own tools.

5. Every assumption is listed, with its source and confidence. One field is flagged for a human.

6. The plan, line by line: product, mechanism, discount, duration, target segment, uplift, profit range, and stock-out risk.

7. North and West get their own lines. Compare regions shows them side by side.

8. Open a line: why it was chosen, and the uplift by segment. Yellow box, cannibalisation. This product takes sales from a sister product. Green box, halo. It lifts a related product.

9. Each line also compares the other mechanisms. The chosen one is marked.

10. Every constraint is checked: budget, margin, stock, clearance, policy. All pass.

11. Not selected lists the options left out, and why.

12. Competitor prices: where a rival is cheaper, and how the planner responds.

13. The simulation runs the plan a thousand times. Every line gets a profit range before launch.

14. Now cut the budget to six lakh. The agent plans again: no line changed, the plan already fits.

15. Then drop West. Revision three shows exactly which lines were removed.

16. Nothing is final until a person approves it. Confirm, and the audit trail records every step.

17. Four things make this an agent. One, tool use: the Planner decides what to call.

18. Two, self-correction: the Critic finds heavy cannibalisation and sends the plan back. Attempt two passes.

19. Three, clarification: no budget in the brief, so the agent stops and asks.

20. Four, grounding: the language model never computes a number. Every number shows its source.

21. All nine features: product selection, mechanism, discount strategy, cannibalisation, product relationships, inventory, geography, competitor awareness, and simulation.

22. Reliability is measured, not claimed. Thirty-three test scenarios, with answers the agent never sees. Twelve of thirteen targets met.

23. Every plan passes every constraint. Thirty of thirty beat the baseline. One honest miss: median regret is twelve point three percent. The target is ten.

24. PromoPilot: agents decide, tools compute, humans approve. One command runs it: make demo, no API key. The code is on GitHub. Thank you.

## Part C: start to finish (simple steps)

1. **Stack chalu karo** (Part A, A1 steps 1–6): Docker Desktop → Git Bash → `cd ~/Documents/PromoPilot` → `.env` mein key commented → `make demo` → Chrome incognito → http://localhost:3000 → **Demo mode** badge.
2. **Screen aur recorder set karo** (A1 steps 7–10): maximize, zoom 100%, notifications off, Game Bar mic off, ₹ ka tareeka.
3. **Rehearse** (A1 step 11): Clip A bina record kiye ek baar.
4. **Record Clip A** (A2): home se approval tak, ek take, bina audio. Waits poore record karo.
5. **Record Clip B** (A3): Quick Diwali push, Critic loop.
6. **Record Clip C** (A4): No budget form.
7. **Record Clip D** (A5): Evals page.
8. **Voice record karo** (Part B):
   - Part B ke 24 paragraphs, 1 se 24, isi order mein. Sirf wahi shabd; paragraph ke number mat bolo. Para 1 mein blank par apna naam.
   - Har paragraph ke baad **ek chhoti saans** (aadha second chup). Isi se editing mein cut point milte hain.
   - Dheere aur saaf bolo; tez bolne ki zaroorat nahi. Galti ho to wahi paragraph dobara bolo, baad mein kaat lenge.
   - Mushkil words: cannibalisation = *ka-ni-ba-lai-ZAY-shun*; mechanism = *MEK-a-ni-zum*; constraint = *kun-STRAYNT*; clearance = *KLEER-ens*; scenarios = *si-NAA-ri-oze*; regret = *ri-GRET*; baseline = *BAYS-line*.
   - Pehle ek baar timer ke saath practice karo. Voice **3:30 se kam** ho to best.
   - **Voice 3:40 se lambi ho** to is order mein hatao, aur kuch nahi badalta: (a) para 11 poora (A13 skip), (b) para 5 ki doosri line "One field is flagged for a human.", (c) para 22 ki pehli line "Reliability is measured, not claimed.", (d) para 9 poora (A11 skip; Mechanisms column phir bhi para 6 ki table mein hai aur para 21 mein naam hai). Charon milke ~15 s.
   - **Voice 3:05 se chhoti ho** to koi dikkat nahi: editing mein para 4 (A5) aur para 8 (A10) ke clips 2–3 s lambe rakho, title cards 1 s zyada.
9. **Edit** (A7 editing map): timeline par pehle voice; phir har paragraph ke shuru par uska clip; T1 aur T2 text slides; planning waits cut ya 8–16× fast.
10. **Check:** total 3:15–3:40; 4:00 cross na ho; 9 features screen par (A7, A10, A11, A12, A14, A15, yaani para 6–13) aur para 21 mein naam; voice kabhi screen se ulta na bole.
11. **Export:** mp4, H.264, 1080p, 30 fps, video ~1.2 Mbps + audio 128 kbps: 3.5 min ≈ 35 MB (limit 50 MB, SPEC §19). Bada ho to 720p.
12. **Upload:** YouTube unlisted → private window mein play check → link README ke LATE marker aur deck slides 1, 8, 12 mein → `make deck` → mp4 form mein upload.
13. **Baad mein:** `make demo-down` (stack band, data rehta hai).

Screenshots for the deck and for B-roll come from the same stack: `make screenshots` writes 1920×1080 PNGs to `frontend/screenshots/`, and the CI `demo` job uploads them as the `deck-screenshots` artifact. `docs/deck.md` says how to build the PDF.
