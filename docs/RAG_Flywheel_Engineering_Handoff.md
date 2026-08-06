# RAG + SM-Review Flywheel — Engineering Handoff

Compiled 2026-07-24. **Revision 2 (2026-07-24, same day):** amended after an academic critical review
of the UC3 "Research area 2 Automated Reporting: Requirements & Potentials" slide. Four mandatory
corrections and one recommended action are integrated — see §0. Do not execute Revision 1's ordering.

Companion to `docs/TrainingData_Decision.md` §8 (the D3 research brief this plan implements),
`docs/DataIngestion_CriticalReview.md`, `docs/TrainingData_UseCase_Fit_Analysis.md`, and
`OPEN_POINTS.md` #7/#10/#14/#15/#16. Written for a coding agent to execute against, in the same
demand/acceptance-criteria style as `TrainingData_UseCase_Fit_Analysis.md` §7.3.

**Read this first if you're the coding agent:** every file, endpoint, and model name below is taken
from the repo as inspected, not assumed — this project has twice caught documentation describing
infrastructure that didn't actually exist (`DataIngestion_CriticalReview.md` findings 1–2). Before
marking any milestone done, point to the actual file/test that proves it. Live progress is tracked
in `docs/IMPLEMENTATION_STATUS.md` — read it before starting and update it as you go.

## 0. Scope statement and validity boundaries (read before anything else)

These are not caveats to bury; they are the claims this work may and may not make. An examiner will
check the write-up against them.

**0.1 — H2 is only half addressed, and this is stated, not hidden.** H2 reads: Agentic AI "reduces
manual effort in PMI reporting by automatically **collecting** status information **and generating**
management reports." This implementation addresses the *generation* half (and the extraction that
feeds it). It does **not** implement automated status collection from workstream leads via form,
Jira, or transcript — which the UC3 slide ranks as the single highest-demand addition
("closes the collection gap upstream of reporting, named highest-value across three interviews").
The system presupposes a human has already gathered the week's files and uploads them. Any result
produced by this plan supports H2's generation half only, and every deliverable citing it must say
so. Closing the collection gap is out of scope for this build and remains an open research/scope
item.

**0.2 — Qualitative/sentiment insights are formally descoped.** The slide lists "Qualitative
Insights: enrich reports with previously missing sentiment and cultural signals" as a potential.
No corpus reviewed (`docs/TrainingData_UseCase_Fit_Analysis.md` §3) is fit for this, no
implementation exists, and no data plan is proposed. It is descoped in writing rather than left
dangling as an implied capability. Reopening it requires a dedicated `pmi-deep-research` pass.

**0.3 — Cross-source conflict detection is traceable, not scope creep.** It does not appear on the
UC3 slide, but derives from the functional spec (`2026_DPID_PreCourseMeeting.pdf` slides 5–7, steps
5–6) that `MASTER.md` implements. State this lineage when the feature is presented; do not let it
read as an unrequested addition.

**0.4 — Smart Prioritization and KPI Benchmarking are deterministic business logic.** Per
`docs/TrainingData_UseCase_Fit_Analysis.md` §5, overdue flagging, escalation, and KPI benchmarking
are rule-based, not learned skills, and need no training corpus. They still require test cases —
tracked under M1a, not skipped.

**0.5 — Anonymization procedure is mandatory for any real PMI material.** Interview evidence records
that German corporate clients frequently refuse recording/data sharing. Before any real PMI document
enters `data/gold_holdout/` (M1): replace client and company names with stable pseudonyms
(`CLIENT_A`, `TARGET_B`), shift all dates by a single fixed random offset per case (preserving
intervals), replace person names with role labels (`WS_LEAD_1`), and round or scale absolute
financial figures while preserving ratios. Record the procedure — not the mapping — in
`data/gold_holdout/README.md`. The pseudonym mapping must never be committed.

## 1. Status quo (verified against the repo, not the docs describing it)

- **Agent:** FastAPI + LangGraph, 7-step workflow (`app/agent/graph.py`), deterministic-first
  extraction (`app/extractors/*.py`), LLM only classifies the request and words the summary
  (`app/agent/llm.py` — OpenAI GPT-5.5 if `OPENAI_API_KEY` set, else a deterministic mock).
  **No training loop exists anywhere in this codebase.**
- **Test data: N=1.** `scripts/make_sample_data.py` generates exactly one case (three files, one
  planted 82%-vs-75% conflict). This proves the pipeline *runs*; it cannot support any accuracy claim.
- **UI:** `static/index.html` — upload, request, audience/conflict selectors, results view. Conflicts
  are displayed but there is **no approve/edit/correction capture**.
- **Storage:** `app/storage/json_store.py` — session-scoped only. No cross-session corpus exists.
- **SM review:** stated in the UI footer and `MASTER.md`'s guardrail section, **not an enforced
  workflow step** (`OPEN_POINTS.md` #7).
- **Data model:** `app/models/pmi.py`'s `SourceRef` carries `file_name`, `file_format`, `location`
  (sheet/slide/page) — provenance, **not a literal text excerpt** (`OPEN_POINTS.md` #16).
- **Manual baseline:** does not exist. Nothing measures the human effort this system claims to reduce.
- **Frozen gold set:** does not exist (`OPEN_POINTS.md` #15).

## 2. Goal

Replace "train on weak-fit proxy datasets" with two mechanisms needing no new training
infrastructure, reusing a compliance requirement the project already has:

1. **RAG at generation time** — retrieve similar past SM-approved reports as few-shot exemplars.
2. **The SM-review step as the corpus-growth mechanism** — every approved report becomes a real,
   gold, target-domain example as a byproduct of a step that must happen anyway.

Evaluated **prequentially** against the frozen gold set — not k-fold, not one pooled dataset
(`docs/TrainingData_Decision.md` §8).

## 3. Milestones

Ordering is load-bearing. **M0 and M1 must complete before M1a.** The reason is methodological, not
administrative: if the synthetic generator is built first, its variation space is defined by what we
already believe messy documents look like, and any gold set drawn afterward becomes correlated with
the generator by construction — making the later transfer-gap number meaningless.

### M0 — Manual baseline measurement *(new in rev. 2; not a coding task)*

**Correction 2 of the critical review.** "Reduces manual effort" is a comparative claim and is
unfalsifiable without a measured comparator. Before or alongside M1: have 2–3 team members each
produce a SteerCo-style report manually from one gold case's source files, recording wall-clock
time, and have their output checked for field-level errors against the same gold labels the agent
will be scored on. Record N, per-participant time, mean, and spread.

**Acceptance:** `data/gold_holdout/baseline_manual.md` exists with per-participant timings, the task
description given to participants, and an explicit statement of how few participants there were
(this is an indicative baseline, not a powered experiment — say so rather than implying otherwise).
**Owner:** Sören/team. **Blocks:** any claim of effort reduction; does not block M2–M5 engineering.

### M1 — Freeze the gold set *(blocking; not a coding task)*

15–30 real or anonymized PMI status-report cases (per §0.5), each with gold field-level labels,
written once and never touched by prompting, RAG indexing, or training.

**Correction 4 of the critical review — inter-rater reliability:** a second annotator independently
labels a subset (minimum 5 cases, ~20–30% of the set). Compute and report agreement — Cohen's κ for
categorical fields (status, severity, owner-present), exact-match rate plus mean absolute error for
numeric fields (progress %, budget). Disagreements are adjudicated and the adjudication rule is
recorded. A single-annotator gold set has no reliability estimate and will be challenged.

**Acceptance:** `data/gold_holdout/` contains the cases plus gold labels; `data/gold_holdout/README.md`
records the freeze date, the anonymization procedure (§0.5), annotator count, the reliability
coefficients, and the adjudication rule. **Owner:** Sören/team.

### M1a — Parameterized synthetic case generator *(coding; requires M1 frozen first)*

Extend `scripts/make_sample_data.py` from one hardcoded case into a generator producing N cases,
varying: owners, workstreams, dates, task/risk/budget counts, conflict type and magnitude, and
document noise (missing/renamed headers, merged cells, mixed date formats DE/EN, percentage as
`82%` vs `0.82` vs `82`, empty rows). Deterministic given a seed. Emits a manifest CSV mapping each
generated file to its ground-truth field values.

Also add test cases for the deterministic Smart Prioritization / KPI Benchmarking logic (§0.4):
overdue = `due_date < today AND status != done`; escalation at a configurable N-day threshold.

**Honest limitation, state it in the code docstring and any write-up:** this validates that the
code does what it was told to do; it does not establish real-world robustness. It is not a
substitute for M8.

**Acceptance:** `python scripts/make_sample_data.py --n 50 --seed 42` produces 50 reproducible
cases + manifest; a test asserts identical output for identical seeds; extraction runs across all
50 without unhandled exceptions; field-level precision/recall computed against the manifest.

### M2 — Cross-session corpus store

New `app/storage/corpus_store.py`, parallel to session-scoped `json_store.py`. Schema:
`{report_id, timestamp, audience, pmi_data_model (snapshot), summary_bullets, sm_status
(pending/approved/edited/rejected), correction_diff}`.
**Acceptance:** write-then-read round-trip test in `tests/test_pipeline.py`; persists across sessions.

### M3 — SM-review UI (makes `OPEN_POINTS.md` #7 real)

New `static/review.html` (design reference: `static/review_mockup.html` — static mockup, not wired)
plus two endpoints in `app/main.py`: `GET /api/review/{session_id}` (pending report + extracted data
+ conflicts) and `POST /api/review/{session_id}` (approve/edit/reject → writes to M2's store). Must
show per conflict: values by source with `SourceRef.location`, current auto-resolution, manual
override control.

**Scope decision required before building (`OPEN_POINTS.md` #16):** the mockup shows source
*location* (file/sheet/slide), not literal quoted text, because extractors don't retain raw
snippets. Either accept location-only, or add M3a (extend `app/extractors/*.py` to keep a short text
snippet per record). Decide explicitly; do not let it become another "described but not built" gap.

### M4 — Wire approval into corpus growth

On approval (edited or not), write the final `PMIDataModel` + report text to M2's store as
`sm_status=approved`. This is the actual flywheel step — skip it and M3 is a nicer UI with no
learning effect. **Acceptance:** an approved report is retrievable by M5.

### M5 — Embeddings index + retrieval integration

Small local vector index over M2's approved reports (reuse whichever provider `app/agent/llm.py`
switches on, or a local sentence-embedding model for zero API cost). In `generate_output`
(`app/agent/graph.py`), retrieve top-k similar approved reports (audience + workstream + similarity)
and inject as few-shot exemplars into the `app/agent/llm.py` prompt.
**Cold-start requirement:** with zero approved reports, fall back to today's zero-shot behavior —
must not hard-fail, consistent with the existing "LLM failures fall back to heuristics" principle.

### M6 — Prequential evaluation harness

A script (not a full online-learning system), run as new reports are approved: score each against
the M1 gold set using the metrics `docs/TrainingData_Decision.md` Stages 1–3 already define
(field-level P/R/F1, numeric accuracy, ROUGE/BERTScore), logged over time rather than computed once
via k-fold. **Pre-registered thresholds (decided before results are seen, do not adjust afterward):**
numeric accuracy ≥95%; transfer gap ≤10–15% relative (`TrainingData_Decision.md` §7 Stage 4).
**Acceptance:** a CSV/log showing metric trend as the corpus grows, plus a documented "corpus is
hurting, not helping" threshold. Report against the M0 baseline where an effort claim is made.

### M7 — Roadmap, not immediate: weak-supervision extraction model

If/when the team wants a smaller, cheaper trained extraction model instead of an indefinite LLM API
call, revisit candidate 3 from `TrainingData_Decision.md` §8 (Snorkel-style weak supervision, Ratner
et al. 2017), using `app/extractors/base.py` as labeling functions. Sequenced after M1–M6.

### M8 — Parallel track: Gap-1 real-document data

M0–M6 need zero external proxy corpora. But RAG only touches *generation*; extraction stays
deterministic and untouched, and per `DataIngestion_CriticalReview.md` it is both the bulk of the
codebase and the source of most defects. Run the SEC EDGAR Gap-1 acquisition
(`TrainingData_Decision.md` §5, `OPEN_POINTS.md` #10) **in parallel** with M1a–M6 — not blocking,
not indefinitely deferred. It validates the one part of the system RAG does not help with, and is
the only step that provides real-world formatting noise M1a cannot fake.

## 4. What this doesn't change

`TrainingData_UseCase_Fit_Analysis.md` §7.3's Demands 1–3 (QMSum download,
`render_generation_fixtures.py`, extraction-roundtrip test) still stand as extraction-layer test
fixtures. Their framing as a "generation fine-tuning/prompting corpus" (§7.1) is superseded by
M1a–M6. Demands 5–6 unaffected.

## 5. Reproducibility requirements (apply to every coding milestone)

Fixed seeds for anything random; datasets versioned and dated; `requirements.txt` pinned when new
deps are added; every acceptance claim backed by a runnable test, not a doc sentence.

## Sources

- `docs/TrainingData_Decision.md` §8 (this plan's direct source)
- `docs/DataIngestion_CriticalReview.md`, `docs/TrainingData_UseCase_Fit_Analysis.md`
- UC3 slide, "Research area 2 Automated Reporting: Requirements & Potentials" (TUM x Deloitte 2026, p.24)
- `OPEN_POINTS.md` #7, #10, #14, #15, #16
- Ratner et al. (2017), Snorkel, PVLDB 11(3); Lewis et al. (2020), RAG, NeurIPS; Settles (2009),
  Active Learning Literature Survey; Gama et al. (2014), ACM Computing Surveys 46(4) — full
  citations in `TrainingData_Decision.md` §8
