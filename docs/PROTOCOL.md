# PROTOCOL — pre-registration

**Locked 2026-08-05**, as of the commit that adds this file to version control (`git log
-- docs/PROTOCOL.md` for the exact SHA). This document exists so that the falsification
criterion, the metric set, and the analysis plan cannot drift toward whatever produces a
favourable result once real runs start — per `evaluation_study_design.md` §6: "not a
formality — it is what stops metric selection drifting toward whatever produced a good
result." **This file must not be edited after Phase 3 (the first scored run) begins.** A
deviation discovered later is recorded as a deviation in the thesis chapter, not folded
back into this document.

Full rationale for every decision below lives in `docs/evaluation_study_design.md` and
`docs/corpus_integration_plan.md`; this file restates only what is locked, not why.

## 1. The claim under test, and what would falsify it

Research question: does Agentic AI improve coordination and steering across PMI
activities. This corpus speaks to H2 (reporting) directly, H3 (risk management) and H5
(people alignment) partly, and cannot speak to H1 (project setup) or H4 (synergy
realisation) at all.

**Falsification, stated before any run:** if the agent produces a report that reads well,
contains no detectable fabrication, and yet **fails to escalate C5 or C6** (the two
designed conflicts with no resolvable correct value — a stale risk severity and a
reassigned-but-unamended action owner), the central claim fails. Those two are precisely
the coordination gaps the thesis argues Agentic AI closes; silently resolving either one
launders a coordination failure into an apparently authoritative figure.

## 2. Design

- **Design A (primary) — ablation.** Three conditions, same corpus, one dimension varied:
  - **Z — deterministic baseline.** Extractors + consistency engine + template renderer,
    no LLM (`LLM_PROVIDER=none`, already supported and free/reproducible).
  - **Y — LLM without the consistency layer.** Conflict detection and escalation
    disabled. **Not yet wired** — see §5, infrastructure status.
  - **X — full agent.** Extractors + consistency engine + escalation (409 gate) + LLM
    narrative. This is what `scripts/eval/run_corpus.py` drives today.
- **Design B (secondary) — model swap.** X held constant, provider varied
  (Anthropic/OpenAI, exact model IDs pinned, never "latest"). Report, do not build the
  thesis on it.
- **Do not cross both factors** unless n permits (3 conditions x 2 corpora x 5 repeats =
  30 runs is the ceiling already agreed).

## 3. Unit of analysis and repeats

- Unit of analysis: one run (one corpus condition, one agent configuration, one repeat).
- Unit of observation for detection metrics: one finding. n = 6 (clean) or 16
  (with_errors — 6 designed conflicts + 10 injected errors, not 10; see
  `ground_truth.json`).
- **≥ 5 repeats per cell, even at temperature 0.** A single run is the most common
  methodological failure in this literature. Report mean, SD, min, max — never a single
  number.
- This is a **feasibility and characterisation study**, not a powered comparison. No
  significance claims on small differences; effect sizes and bootstrap confidence
  intervals only.

## 4. Metrics locked in advance

**Primary (gates — pass/fail per run, never averaged):**

| # | Metric | Target |
|---|---|---|
| P1 | Critical-conflict escalation | 100% |
| P2 | Stale-register flagging (C5, C6) | 100% |
| P3 | Fabrication rate | 0 (adjudicated, not raw) |
| P4 | Silent-loss rate | 0 |
| P5 | Unreadable-file honesty (E-01) | pass/fail |

**Secondary (capability):** S1 extraction recall (>=90% tabular), S2 conflict detection
recall (>=90%), S3 conflict precision (>=95%, with `unplanted_true_positive` adjudicated
separately, not scored as a false positive), S4 resolution correctness (report, no
target), S5 output validity (100%, every artefact re-opens in its own library), S6
confidence calibration (report).

**Tertiary (summarisation arm, transcript -> minutes):** T1 decision recall, T2 action
recall + owner accuracy, T3 decision precision (the dangerous direction — decisions
asserted that were not taken), T4 faithfulness (human-rated).

**Cost/effort:** wall-clock, tokens, cost per run, human resolution time — required for
the H2 "reduced manual effort" claim, or that claim is dropped.

Full operational definitions: `evaluation_study_design.md` §4. This scorer implements
them (`scripts/eval/score.py`); it does not redefine them.

## 5. Infrastructure status at lock time

Built and passing:
- Corpus frozen as `data/corpus/dellemc_vcio/v1.0/` (`clean/`, `with_errors/`,
  `MANIFEST.sha256`, integrity-checked by `tests/test_corpus_dellemc.py -m corpus`, all 7
  keyless checks passing).
- `ground_truth.json` / `error_key.json` exported from `generators/case.py` /
  `error_key.py` (never hand-retyped), traced against the `g2_*.py` renderers file by
  file.
- Harness (`scripts/eval/run_corpus.py`) and scorer (`scripts/eval/score.py`) written,
  **and Phase 3 (Z-only, keyless) has now actually been run** against both `clean/` and
  `with_errors/` (`scripts/eval/runs/clean_Z_1_4dccacb2/`,
  `scripts/eval/runs/with_errors_Z_1_40f42e80/`). One real bug found and fixed in the
  scorer itself in the process: an empty-string substring check made every conflict read
  as falsely "detected" via `validation_issues` file-overlap — see the scorer's own
  history for the fix. Corrected result: **0 of 6 planted conflicts detected** under Z on
  the real corpus (`conflicts_pre_resolution` returns an empty list both runs); 9 of 10
  injected errors show a candidate match via `validation_issues`, unconfirmed pending
  adjudication (Phase 5) since file-overlap alone is a weak signal in a busy corpus (spot-
  checked one — E-09 — and the "match" was an unrelated warning, not the specific error).

**Known gaps, not silently dropped:**
- **The 0/6 conflict-detection result has a diagnosed, structural cause, not a bug in
  the harness.** Investigated in depth (see `known_limitations.md`, "Conflict detection
  limits"): C1 fails because a stated aggregate (a one-pager's "66% complete" tile) is
  never compared against the tracker's own correctly-computed roll-up (59%) — they land in
  different, uncompared entity-type collections. C6 fails because an explicit "the signed
  minutes were never corrected" statement lives in free text disconnected from the
  structured `owner` field conflict resolution actually evaluates. Both are real gaps in
  cross-entity-type matching and free-text-to-structured-conflict linkage — genuine,
  multi-file extraction/matching work, not something a single-session patch can respons
  fix without either overfitting to this corpus's exact wording or risking regressions in
  a shared, actively-developed codebase. **This means a paid X run today would very likely
  reproduce the same 0/6 result on these two conflicts specifically**, since extraction and
  matching are identical between X and Z — only narrative generation differs. C2, C3, C4,
  C5 were not individually root-caused to the same depth; C5 additionally cannot be
  evaluated at all without a working vision-capable API key (see below).
- Condition **Y** (LLM without the consistency layer) has no toggle in the app yet — a
  code change, not a config flag. Design A cannot run in full until it exists.
- **`.env` still holds the placeholder `ANTHROPIC_API_KEY=sk-ant-...`, not a real key** —
  confirmed via a live 401 from Anthropic during testing. No paid (X-condition) run is
  possible until a real key is added.
- Per-entity `stated_in` provenance (needed for S1) is exported only for the 16 findings,
  not the full entity set — see `ground_truth.json`'s own `known_gaps`.
- The API does not yet surface temperature, seed, token counts, or per-call cost;
  `run.json` records these as `null` with a note rather than inventing them. A cost/token
  logging pass is needed before Design A's cost-claim (§4, "Cost and effort") can be
  scored quantitatively.
- **Run traceability vs. blinding.** `corpus_integration_plan.md` originally called for a
  run ID surfaced in the UI so a rated report could be traced back to its run. On review,
  this conflicts with §7's blinding requirement (reports must be stripped of anything
  identifying condition X/Y/Z before a rater sees them) — stamping a run ID into the
  visible artefact would leak exactly what blinding is meant to hide. Resolution: no UI
  change. `scripts/eval/run_corpus.py` already writes one `run.json` per run and saves
  its artefacts under `scripts/eval/runs/<run_id>/`, so traceability exists on the
  researcher's side; the blinded rating packet (Phase 6) will carry a **separate,
  researcher-only lookup table** (anonymous rater-facing label -> `run_id`), prepared
  when that packet is built, never a visible stamp.

## 6. Analysis plan, fixed in advance

- Descriptive first: per cell, mean/SD/min/max over repeats; every raw observation in an
  appendix (n is small enough the reader should see all of it).
- Paired comparisons (X, Y, Z see identical inputs): McNemar's test for binary
  detection outcomes across two conditions; Friedman then Wilcoxon signed-rank with Holm
  correction for continuous scores across three conditions.
- Effect sizes with bootstrap confidence intervals, not p-values alone.
- Gate metrics (P1-P5) reported as counts of runs that passed — **never averaged**.
- Deviations from this plan, if any become necessary, are reported as deviations in the
  thesis chapter, not silently absorbed.

## 7. Execution sequence from here

| Phase | Work | Gate to proceed |
|---|---|---|
| 0 | Corpus + ground truth + manifest (done, this lock) | — |
| 1 | This file, committed | must precede any scored run |
| 2 | Harness + scorer (done, unexecuted) | — |
| 3 | **Z only** — keyless, free, fully deterministic | debugs the harness at zero cost |
| 4 | X (and Y once wired), 5 repeats x 2 corpora | primary result |
| 5 | Adjudication (fabrication, unplanted positives) | two people, disagreements recorded |
| 6 | Blinded human rating (>=3 raters, recruitment starts alongside the next UAT round) | anchored against the human-authored ground-truth minutes |
| 7 | Analysis + limitation register | thesis chapter |

Phases 3 onward are explicitly **not** part of this work session — this protocol exists
so that when they happen, the bar was set before anyone saw a result.
