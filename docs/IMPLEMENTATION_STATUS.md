# Implementation Status — RAG + SM-Review Flywheel

**This is the resume file.** Any agent or person picking this work up mid-stream reads this first,
then `docs/RAG_Flywheel_Engineering_Handoff.md` for the spec of whichever milestone is next.

**Branch:** `soeren` · **Plan:** `docs/RAG_Flywheel_Engineering_Handoff.md` (Revision 2)
**Last updated:** 2026-07-24 — initial state, no milestone started

## Protocol (follow this exactly)

1. Before starting work: read this file, find the first task not `[x]`, confirm nothing above it is
   still open.
2. When you start a task, change `[ ]` to `[~]` and add your date.
3. When you finish, change to `[x]` and **fill the Evidence column with a real file path, test name,
   or command output** — not a description. An unproven `[x]` is the failure mode this project has
   already caught twice (`docs/DataIngestion_CriticalReview.md` findings 1–2).
4. If you stop mid-task, leave it `[~]` and write what remains in Notes. Commit before stopping.
5. If you hit a blocker or a decision only the team can make, mark `[!]`, describe it in Notes, add
   it to `OPEN_POINTS.md`, and move to the next unblocked task rather than guessing.
6. Update the "Last updated" line and commit this file with every session's work.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done + evidence · `[!]` blocked · `[-]` descoped

---

## M0 — Manual baseline measurement (team task, not coding)

| # | Task | Status | Evidence |
|---|---|---|---|
| 0.1 | Define the manual task given to participants (produce SteerCo report from one gold case's raw files) | `[ ]` | |
| 0.2 | Run with 2–3 team members, record wall-clock time each | `[ ]` | |
| 0.3 | Score their output against the same gold labels the agent will be scored on | `[ ]` | |
| 0.4 | Write `data/gold_holdout/baseline_manual.md` incl. explicit small-N caveat | `[ ]` | |

**Notes:** Blocks any "reduces manual effort" claim. Does NOT block M2–M5 engineering.

## M1 — Freeze the gold set (team task, not coding) — BLOCKING for M1a

| # | Task | Status | Evidence |
|---|---|---|---|
| 1.1 | Collect 15–30 real PMI status-report cases | `[ ]` | |
| 1.2 | Apply anonymization procedure per handoff §0.5 (pseudonyms, date offset, role labels, scaled figures) | `[ ]` | |
| 1.3 | Annotator 1 writes gold field-level labels for all cases | `[ ]` | |
| 1.4 | Annotator 2 independently labels a ≥5-case subset | `[ ]` | |
| 1.5 | Compute Cohen's κ (categorical) + exact-match/MAE (numeric); record adjudication rule | `[ ]` | |
| 1.6 | Write `data/gold_holdout/README.md`: freeze date, anonymization procedure, annotator count, κ, adjudication rule | `[ ]` | |
| 1.7 | Confirm mapping file is gitignored and never committed | `[ ]` | |

**Notes:** Must be frozen before M1a is designed — see handoff §3 ordering rationale.

## M1a — Parameterized synthetic case generator (coding)

| # | Task | Status | Evidence |
|---|---|---|---|
| 1a.1 | Refactor `scripts/make_sample_data.py` to accept `--n` and `--seed` | `[ ]` | |
| 1a.2 | Parameterize owners / workstreams / dates / item counts | `[ ]` | |
| 1a.3 | Parameterize conflict type + magnitude (not just the fixed 82/75) | `[ ]` | |
| 1a.4 | Add document-noise variants: renamed/missing headers, merged cells, DE/EN date formats, `82%` vs `0.82` vs `82`, empty rows | `[ ]` | |
| 1a.5 | Emit manifest CSV: generated file → ground-truth field values | `[ ]` | |
| 1a.6 | Determinism test: same seed → identical output | `[ ]` | |
| 1a.7 | Run extraction across all N cases, no unhandled exceptions | `[ ]` | |
| 1a.8 | Compute field-level P/R/F1 vs. manifest; record the numbers | `[ ]` | |
| 1a.9 | Add deterministic overdue/escalation/KPI-benchmark test cases (handoff §0.4) | `[ ]` | |
| 1a.10 | Docstring states the circularity limitation explicitly | `[ ]` | |

## M2 — Cross-session corpus store (coding)

| # | Task | Status | Evidence |
|---|---|---|---|
| 2.1 | Create `app/storage/corpus_store.py` with the handoff §3 schema | `[ ]` | |
| 2.2 | Write/read round-trip test in `tests/test_pipeline.py` | `[ ]` | |
| 2.3 | Verify persistence across separate process runs | `[ ]` | |

## M3 — SM-review UI (coding)

| # | Task | Status | Evidence |
|---|---|---|---|
| 3.0 | **Decision first:** location-only provenance, or add M3a snippet extraction? (`OPEN_POINTS.md` #16) | `[!]` | Awaiting team decision |
| 3.1 | `GET /api/review/{session_id}` in `app/main.py` | `[ ]` | |
| 3.2 | `POST /api/review/{session_id}` (approve/edit/reject) | `[ ]` | |
| 3.3 | `static/review.html` from `static/review_mockup.html` design | `[ ]` | |
| 3.4 | Per-conflict: source values + `SourceRef.location` + override control | `[ ]` | |
| 3.5 | API round-trip test | `[ ]` | |

## M3a — Raw-snippet extraction *(only if 3.0 decides "add")*

| # | Task | Status | Evidence |
|---|---|---|---|
| 3a.1 | Add optional `snippet` field to `SourceRef` in `app/models/pmi.py` | `[ ]` | |
| 3a.2 | Populate it in each `app/extractors/*.py` | `[ ]` | |
| 3a.3 | Surface in review UI | `[ ]` | |

## M4 — Wire approval into corpus growth (coding)

| # | Task | Status | Evidence |
|---|---|---|---|
| 4.1 | On approve, write `PMIDataModel` + report text to corpus store as `sm_status=approved` | `[ ]` | |
| 4.2 | Capture `correction_diff` when the reviewer edited before approving | `[ ]` | |
| 4.3 | Test: approved report is retrievable | `[ ]` | |

## M5 — Embeddings index + retrieval (coding)

| # | Task | Status | Evidence |
|---|---|---|---|
| 5.1 | Choose embedding source (reuse `app/agent/llm.py` provider vs. local model) — record the choice | `[ ]` | |
| 5.2 | Build index over approved reports | `[ ]` | |
| 5.3 | Retrieve top-k by audience + workstream + similarity | `[ ]` | |
| 5.4 | Inject as few-shot exemplars into the generation prompt | `[ ]` | |
| 5.5 | **Cold-start test:** zero approved reports → falls back to zero-shot, does not hard-fail | `[ ]` | |

## M6 — Prequential evaluation harness (coding)

| # | Task | Status | Evidence |
|---|---|---|---|
| 6.1 | Scoring script: field-level P/R/F1, numeric accuracy, ROUGE/BERTScore vs. M1 gold set | `[ ]` | |
| 6.2 | Prequential loop: score before folding each new approved case in | `[ ]` | |
| 6.3 | Metric-trend log (CSV) over corpus growth | `[ ]` | |
| 6.4 | Encode pre-registered thresholds: numeric ≥95%, transfer gap ≤10–15% — do not adjust after seeing results | `[ ]` | |
| 6.5 | Report against M0 baseline wherever an effort-reduction claim is made | `[ ]` | |

## M7 — Weak-supervision extraction model — ROADMAP, not now

| # | Task | Status | Evidence |
|---|---|---|---|
| 7.1 | Revisit only after M0–M6 run and cost/accuracy is measured (`OPEN_POINTS.md` #14) | `[ ]` | |

## M8 — Gap-1 real-document data (parallel track, can run anytime)

| # | Task | Status | Evidence |
|---|---|---|---|
| 8.1 | SEC EDGAR acquisition per `TrainingData_Decision.md` §5 | `[ ]` | |
| 8.2 | XBRL tags → ground-truth labels for HTML/PDF extraction | `[ ]` | |
| 8.3 | Field-level extraction scoring on real documents | `[ ]` | |

## Descoped (do not implement without reopening the decision)

| Item | Status | Reason |
|---|---|---|
| Qualitative / sentiment / cultural signals | `[-]` | Handoff §0.2 — no fit-for-purpose corpus, no implementation, formally descoped |
| Automated status collection from workstream leads (form/Jira/transcript) | `[-]` | Handoff §0.1 — out of scope for this build; H2's collection half is not addressed. **Must be stated in every deliverable citing these results.** |
