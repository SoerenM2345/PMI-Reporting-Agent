# Runbook — running the full test suite and the evaluation study

Everything needed to go from a clean checkout to a scored result. Ordered so each step's
output feeds the next. See `docs/PROTOCOL.md` for what each phase is *for* and
`docs/known_limitations.md` for what currently doesn't work and why.

## 0. Prerequisites

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # then paste a real ANTHROPIC_API_KEY — see step 4, this is currently a placeholder
```

Confirm which key is actually active before relying on it:
```bash
grep ANTHROPIC_API_KEY .env   # must NOT read "sk-ant-..." literally — that's the placeholder
```

## 1. Application test suite (product code, not the eval study)

```bash
.venv/bin/pytest -q -m "not corpus"          # the app's own ~839 tests, no API key needed
.venv/bin/pytest -q -m "not corpus" --cov=app
```
One pre-existing, unrelated collection error: `tests/test_report_formats.py` needs the
`fpdf` package, missing from this `.venv` (`pip install fpdf2` fixes it — not something
introduced by the evaluation work).

## 2. Corpus integrity (keyless, seconds, run this before trusting anything downstream)

```bash
.venv/bin/pytest -q -m corpus                                  # 7 tests via pytest
.venv/bin/python data/corpus/dellemc_vcio/v1.0/generators/corpus_integrity.py  # same checks, standalone
```
Confirms: every manifested file still hashes to what `MANIFEST.sha256` recorded, `clean/`
and `with_errors/` differ in exactly the 6 files they should, and all 21 documents parse
with the app's own extractors.

**If you ever deliberately edit the corpus** (new version, e.g. v1.1): re-run
`generators/build_manifest.py`, and if `case.py`/`error_key.py` changed, re-run
`generators/export_ground_truth.py` too — nothing else updates the manifest or ground
truth for you.

## 3. Free, keyless evaluation run (Z condition — the deterministic baseline)

Start a server explicitly configured `LLM_PROVIDER=none` (don't reuse a dev server that
merely has an invalid key — that's a different, uncontrolled condition):
```bash
LLM_PROVIDER=none .venv/bin/uvicorn app.main:app --port 8001 &
```
Run the harness against it, both corpus conditions:
```bash
.venv/bin/python scripts/eval/run_corpus.py --base http://127.0.0.1:8001 --condition clean --agent-config Z --repeat-index 1
.venv/bin/python scripts/eval/run_corpus.py --base http://127.0.0.1:8001 --condition with_errors --agent-config Z --repeat-index 1
```
Score it:
```bash
.venv/bin/python scripts/eval/score.py scripts/eval/runs/*/run.json --out scripts/eval/runs/results.csv
```

**What to expect right now, and why it's not a bug:** 0 of 6 planted conflicts detected.
Root-caused, not hand-waved — see `docs/known_limitations.md` "Conflict detection limits"
(the two paragraphs on the stated-vs-computed aggregate gap, and the free-text-vs-
structured-conflict gap). 9 of 10 injected errors show a *candidate* match via
`validation_issues`; treat every one as unconfirmed until adjudicated (Phase 5) — the
matching heuristic is file-overlap only and produces false positives in a busy corpus
(confirmed by spot-check).

## 4. Paid evaluation run (X condition — full agent) — **blocked right now**

`.env`'s `ANTHROPIC_API_KEY` is still the literal placeholder `sk-ant-...`. Confirmed via
a live 401 from Anthropic during this session's testing. **Paste a real key before this
step will do anything except fail.**

Once a real key is in `.env`, restart a normal server (this one *should* use your real
`.env`, unlike step 3's forced-`none` instance):
```bash
.venv/bin/uvicorn app.main:app --reload   # port 8000
```
Run 5 repeats per corpus condition (PROTOCOL.md §3's minimum — never report a single run):
```bash
for i in 1 2 3 4 5; do
  .venv/bin/python scripts/eval/run_corpus.py --base http://127.0.0.1:8000 --condition clean       --agent-config X --repeat-index $i
  .venv/bin/python scripts/eval/run_corpus.py --base http://127.0.0.1:8000 --condition with_errors --agent-config X --repeat-index $i
done
.venv/bin/python scripts/eval/score.py scripts/eval/runs/*/run.json --out scripts/eval/runs/results_full.csv
```
**Expect C1 and C6 to still fail** for the structural reasons in step 3 — extraction and
matching are identical between X and Z, only narrative generation differs. This is a
known, documented limitation of the *system*, not of this run. C2, C3, C4 were not
individually root-caused; C5 additionally needs a working vision-capable key regardless
(its evidence is an image).

**Condition Y** (LLM without the consistency layer) has no toggle in the app — it cannot
be run without a code change first (`docs/PROTOCOL.md` §5).

## 5. Adjudication (Phase 5 — human, not automatable)

Every scorer row with `needs_adjudication=true` (which is most of them — see `score.py`'s
own docstring on why) needs a person to look at the actual conflict/issue payload in the
corresponding `run.json` against `ground_truth.json`/`error_key.json` and decide: real
detection, false positive, or an `unplanted_true_positive` (a genuine finding the corpus
didn't plant — counts separately, not as a false positive). Not scripted; there is
nothing here to automate without reintroducing the exact judgment problem adjudication
exists to solve.

## 6. Blinded human rating (Phase 6)

Needs reports generated from a completed X run (step 4) and your ≥3 recruited raters
(recruitment starts alongside the next UAT round, per your plan). Instrument:
`docs/uat_questionnaire.md`, extended per `evaluation_study_design.md` §7 (5-point Likert
on faithfulness/completeness/actionability/trust, condition-blind, randomised order,
anchored against the human-authored ground-truth minutes). Traceability from a blinded
report back to its run is via `scripts/eval/runs/<run_id>/` — never a visible stamp on
the artefact itself, since that would break blinding (see `docs/PROTOCOL.md` §5).

## 7. Optional: poke around in the actual app (not part of scoring)

```bash
.venv/bin/uvicorn app.main:app --reload &          # terminal 1
npm --prefix frontend run dev &                     # terminal 2
.venv/bin/python scripts/load_synthetic_corpus.py   # loads both corpora as chat projects
```
Open the frontend, find "PMI Case (Demo) - Clean" / "- With Errors" in the sidebar, chat
with them. Ground truth is never uploaded, so this is a fair (if informal) look at the
agent's behaviour — just not a scored one.

## Quick reference — what's already been run this session

| Artefact | Status |
|---|---|
| `pytest -q -m "not corpus"` | 839 passed, 3 skipped |
| `pytest -q -m corpus` | 7 passed |
| Z-condition, `clean` | `scripts/eval/runs/clean_Z_1_4dccacb2/run.json` |
| Z-condition, `with_errors` | `scripts/eval/runs/with_errors_Z_1_40f42e80/run.json` |
| X-condition (any) | **not run — no valid API key** |
| Demo loader | Verified working against a live server (21/21 files each corpus) |
