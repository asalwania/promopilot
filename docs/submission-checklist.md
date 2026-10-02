# Submission checklist

SPEC §19's final checklist, with the Unstop form fields of SPEC §1.3–§1.4, tracked for #81. A ticked item links its evidence. An unticked item names its owner and the one step left.

Checked on 2026-10-02 against `main` at `403a416`.

## SPEC §19

- [x] **Repo public; opens in a private window; no secrets in history.**
  - `gh repo view asalwania/promopilot` reports `PUBLIC`, and an anonymous request to <https://github.com/asalwania/promopilot> returns HTTP 200.
  - All 107 commits on every branch were scanned for OpenAI, Anthropic, AWS, GitHub and Slack key shapes and for private-key blocks. The only hits are two fake test keys, `sk-test-do-not-leak-…` and `sk-ant-test-do-not-leak`, which the redaction tests use to prove a key never reaches a log.
  - No `.env` file was ever committed. The `detect private key` pre-commit hook runs on every commit.
- [x] **`make demo` works on a fresh clone with no API key.** CI's `make demo from a clean checkout (no key, Playwright)` job does exactly this on every PR and on `main`: it starts from a clean checkout with no key, runs `make demo`, and drives the app with Playwright. It last passed on `main` in [this run](https://github.com/asalwania/promopilot/actions/runs/36955103252/job/110676234651). See also [ADR 0073](adr/0073-make-demo-from-a-fresh-clone.md).
- [x] **README complete per §1.4.** The [README](../README.md) has:
  - complete source: the whole repo, laid out under "Repository layout";
  - installation steps: "Try it: `make demo`" and "Develop";
  - dependencies: Docker, uv, Node 24 with pnpm 11, and GNU make, listed under "Develop", with the open-source credits under "Credits";
  - an architecture overview: "Architecture", which links [docs/architecture.md](architecture.md);
  - API documentation: "API", which links the generated [docs/api.md](api.md) and [docs/tools.md](tools.md);
  - environment setup: `.env.example` and [docs/guide/running.md](guide/running.md).

  The README also covers the claim, results, known gaps and licence ([LICENSE](../LICENSE)).
- [x] **`docs/architecture.md` and `docs/nine-blocker.md` final, numbers match the eval report.**
  - [architecture.md](architecture.md): its module diagram is checked against the real imports by `backend/tests/architecture/test_architecture_doc.py` ([ADR 0092](adr/0092-module-dependency-diagram-is-tested-against-imports.md)).
  - [nine-blocker.md](nine-blocker.md): its numbers come from [published/latest.md](../backend/evals/published/latest.md) (report `20261001T170727Z`) and [published/consistency.md](../backend/evals/published/consistency.md) (report `20261001T180312Z`). Every cited file, symbol and pytest id is resolved by `backend/tests/tools/test_nine_blocker_matrix.py` ([ADR 0091](adr/0091-the-matrix-cites-files-and-symbols-and-a-test-resolves-them.md)).
  - Neither document has a `LATE:` marker left.
- [ ] **All 9 features visible in the video.** Owner: **the user** (#80). [video-script.md](video-script.md) shows all nine (F-01 to F-09) between 0:40 and 3:25, using only recorded briefs, so it plays with no key.
- [ ] **Video 2–4 min, mp4 under 50 MB, YouTube unlisted link works.** Owner: **the user** (#80). The script runs about 3:50. After uploading, check the link in a private window, then put it in the README's "Demo video" section (replacing its `LATE:` marker) and in the deck's three `OWNER:` video markers.
- [ ] **Deck PDF under 50 MB, 12 slides.** Owner: **the user** (#79). [deck.md](deck.md) has the 12 slides of SPEC §17, with the published numbers. Its header comment gives the three steps: get the screenshots (the `deck-screenshots` CI artifact, or `make screenshots`), fill the `OWNER:` markers, and export with Marp.
- [ ] **Problem statement dropdown set to "Retail – Autonomous Promotion Planner".** Owner: **the user**, on the Unstop form.
- [ ] **Confirmation screenshot saved.** Owner: **the user**, after submitting.

## Unstop form fields (SPEC §1.4)

| Field | Requirement | Status |
|---|---|---|
| Pitch deck | PDF, ≤ 50 MB, 8–12 slides covering team, problem, solution, architecture, AI models, demo, impact, scalability, roadmap | Content ready in [deck.md](deck.md), and its 12 slides cover every required topic. **User**: build the PDF (#79). |
| Demo video | 2–4 min mp4 plus an unlisted YouTube or Drive link; intro, problem, live demo, AI capabilities, key features, impact, close | Script ready in [video-script.md](video-script.md), with its sections in the required order. **User**: record, edit and upload it (#80). |
| GitHub repo | Public; source, README, installation, dependencies, architecture, API docs, environment setup | Done; see the §19 items above. |
| Problem statement | "Retail – Autonomous Promotion Planner" | **User**: select it on the form. |

## SPEC §1.3 expectations

- **A working demo in every area we claim.** The [nine-blocker matrix](nine-blocker.md) gives a demo moment for each claimed feature, and the video script follows those moments.
- **A detailed structural architecture.** [architecture.md](architecture.md) covers the process flow, the agent graph, the decisions, model use and how each feature is built.

## Known gaps, stated honestly

- **Regret misses its target:** 12.3% median against ≤ 10%. The largest cause is model error, in 16 of 29 plans. This is stated in the README, the nine-blocker document and the deck.
- These follow-up issues are left open on purpose and listed in the README: #166, #168, #170, #171, #174, #181.
