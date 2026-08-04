# MASTER — What This Codebase Does and How It Is Built

Orientation for a developer. The functional spec is `agent.md`; this file says how the
code realises it. To *use* the app, see [README.md](README.md). For the design reasoning,
see [docs/architecture.md](docs/architecture.md).

## What this is

An agent that turns a week of fragmented PMI files into an audience-specific report.

Its defining behaviour is not what it produces but what it **refuses** to produce. The
files disagree with each other, and a tool that silently picks one number launders a
disagreement into a fact — which then goes to a board. So:

- Conflicts that change the management message are put to a human. `POST /api/generate`
  returns **409** until they are answered.
- A field no source stated is `None`, rendered "Not Reported". Never a guess, never a zero.
- Anything read from an image is capped below full confidence and flagged for review.
- With no vision model, an unreadable screenshot is *reported as unreadable* — not
  silently dropped.

## Layout

```
app/
├── config.py             every model ID, threshold and policy knob (§21.10, test-enforced)
├── main.py               FastAPI: project → upload → analyze → resolve → generate → download
│
├── llm/                  provider abstraction; the LLM never does arithmetic (§11)
│   ├── base.py           LLMClient Protocol: one method, structured() -> validated Pydantic
│   ├── anthropic_client.py   default; vision-capable (this is what §5.6 needs)
│   ├── openai_client.py      kept working; LLM_PROVIDER=openai
│   ├── null_client.py        no key -> raises -> tasks.py falls back deterministically
│   ├── tasks.py          the semantic tasks; records a warning on every fallback
│   ├── fallbacks.py      keyword matching + template prose. Honest but dumb.
│   ├── schemas.py        Pydantic contracts for every LLM output
│   └── prompts/          *.md, loaded at runtime
│
├── extractors/           one module per format: suffixes, format, extract(path) -> [dict]
│   ├── base.py           header aliases (EN+DE), the Extractor protocol, parsers
│   ├── excel.py csv.py powerpoint.py word.py pdf.py html.py
│   └── image.py          §5.6 — the biggest subsystem. Confidence computed in Python.
│
├── models/               the 14 spec entities (§6)
│   ├── enums.py          taxonomies + alias maps (§7)
│   ├── source.py         SourceReference: file/sheet/cell/slide/page/region + confidence
│   ├── entities.py       the 13 entities
│   ├── quality.py        Conflict, ValidationIssue, DataQualityReport
│   └── pmi.py            PMIDataModel + the import surface
│
├── agent/
│   ├── graph.py          three compiled LangGraph graphs over shared nodes
│   ├── state.py          AgentState
│   ├── standardize.py    raw records -> entities. Bad rows are REPORTED, not swallowed.
│   ├── calculations.py   risk scores, variances, overdue. Deterministic (§11).
│   ├── matching.py       "ERP go-live" == "ERP Go Live". Without this, no conflict exists.
│   ├── consistency/      32 registered checks + severity + §9 Mode A/B/C resolution
│   └── data_quality.py   the score, and the honest account of what the run could not do
│
├── generators/
│   ├── pptx_report.py    4 audience decks (§12), management-message titles (§12.5)
│   ├── xlsx_dashboard.py the 10 sheets of §13
│   ├── charts.py         10 chart types (§14), incl. the risk heatmap
│   └── quality_report.py the conflict + data-quality reports — on EVERY run
│
├── storage/json_store.py sessions + the persisted analysis
└── utils/images.py       §5.6 steps 1-4: orient, resize, contrast, measure quality

frontend/                 React + JavaScript + Tailwind (Vite)
scripts/                  sample data (11 files), vision-fixture recorder, §20 demo
tests/                    136 tests, all green with no API key
docs/                     architecture · data model · reporting logic · user guide ·
                          evaluation plan · known limitations · UAT questionnaire
```

## The design decisions that matter

### Three graphs, not one

Generation must never re-run extraction. The original single graph re-ran from the top on
every human-in-the-loop round trip — which, once image extraction landed, meant paying
for a vision call every time the user resolved a conflict, and re-rolling the dice on
what the model saw. Analysis is run once and persisted to
`storage_data/<session>/analysis.json`; resolving patches it, generating reads it.

We did **not** adopt a LangGraph checkpointer: `MemorySaver` dies on a uvicorn reload,
and `SqliteSaver` buys durability the JSON store already provides. Upgrade path is in the
architecture doc.

### Severity is assigned by topic first, magnitude second

The load-bearing detail of the whole conflict system.

The spec's own example is 82% vs 75% — a **9% delta**. A magnitude-based severity rule
calls that "medium", auto-resolves it, and never tells the user. But §20 step 9 requires
the system to ask. So `consistency/severity.py` escalates on **topic**, encoding §9's
critical list (overall status, Day 1 readiness, go-live dates, budget totals, synergy
realization, critical risks, SteerCo decisions, TSA exits, regulatory milestones).
Magnitude is the second axis, not the first.

### Image confidence is computed in Python, not taken from the model

The model is not the authority on how much to trust the model (§21.14). Its self-reported
confidence is an *input*, multiplied down by measured legibility, blur, resolution,
handwriting and cropping — then **capped at 0.90**. No image reading ever reaches the
confidence of a spreadsheet read, so a figure from a screenshot always loses an automatic
conflict against the tracker it was screenshotted from.

Anything read by vision or OCR lands in the review panel even at a high score: it is a
transcription, and nobody has confirmed it against the source system.

### The LLM does not do arithmetic

§11 forbids it, and `calculations.py` enforces it. Where a *source* reports a derived
value that disagrees with the computed one, ours wins and the disagreement is reported.
A tracker that gets its own arithmetic wrong should not have that error laundered into a
board pack.

## Bugs fixed from v1 (each one silently lost data)

| Where | Was | Now |
|---|---|---|
| `base.py::classify_table` | Both branches of a ternary returned `"task"` — classification was dead code. | Best-scoring specific type wins. |
| `base.py::parse_number` | `"1,234"` → `1.234`. | Locale heuristic: last separator is the decimal mark. |
| `base.py::normalize_header` | Naive substring matching — `"Not Started"` matched an alias, so data rows were mistaken for header rows and tables were split in half. | Exact → whole-word (≥4 chars) → prefix, and status values are never headers. |
| `main.py::download` | Path-traversal guard ran *after* `path.exists()`, and a URL segment never contains `".."` — it never fired. | `resolve()` + `is_relative_to()`. |
| `llm.py` | `model_dump_json()[:12000]` sliced JSON mid-token. | Whole entities dropped from the tail; payload stays parseable. |
| `llm.py` | `except Exception: pass` around every call — a broken API key looked exactly like a working one. | Logged, and recorded as a warning that reaches the data-quality report. |
| `standardize.py` | `except Exception: continue` silently dropped bad rows. | Each dropped row is reported with its file, location and reason. |
| `resolution.py` | Re-running resolution clobbered a user's decision with "a person must decide". | Idempotent: an already-resolved conflict is left alone. |
| `matching.py` | At a 0.6 threshold, "Migrate payroll" and "Migrate CRM" merged. | 0.75 — a false merge destroys data; a missed match only misses a conflict. |

## Tests

```bash
pytest -q          # 136, all green, no API key
```

| File | Covers |
|---|---|
| `test_acceptance.py` | **the §20 scenario, all 15 steps** — including the 409 |
| `test_config_and_llm.py` | provider swap, keyless fallback, the no-hard-coded-model-ID grep |
| `test_model_and_calculations.py` | the data model, and §11's deterministic arithmetic |
| `test_extractors.py` | every format, and the image pipeline against a stored vision fixture |
| `test_consistency.py` | matching, the check suite, severity, Modes A/B/C |
| `test_generators.py` | decks, workbooks, charts, the two reports |
| `test_api.py` | the analyze → resolve → generate round trip, and path traversal |
| `test_pipeline.py` | the original v1 suite, still green |

The vision fixture (`tests/fixtures/vision/risk_dashboard.json`) is currently
**hand-authored**, not captured from a live model. It proves the plumbing; it does not
prove the model can read a heatmap. Re-record it with
`python scripts/record_vision_fixture.py` and read the diff.

## Known scope cuts

See [docs/known_limitations.md](docs/known_limitations.md). The honest summary: no
ground-truth PMI corpus, no auth, local JSON storage, and a figure stated only in prose
(rather than a table) is not extracted without an LLM.

## Dataset augmentation plan (in progress — branch `katja-dataset`)

Addresses the "no ground-truth PMI corpus" gap above and the H2-initiative training-data
strategy (QMSum/ECTSum/AMI). Work happens on a local branch `katja-dataset` (tracks
`origin/katja`); **`main` is never touched and `origin/katja` is never merged**, per an
explicit instruction — this is a working-copy-only effort.

### Why, in one paragraph

This project's own `docs/evaluation_plan.md` flags its one hand-built synthetic sample
project as close to a tautology: the same team wrote both the test files and the
conflicts they're scored against. More generated-but-fabricated PMI data doesn't fix
that — it would still be *our* rules testing *our* rules. The fix is to build the corpus
from **real, externally validated content** (QMSum, ECTSum, AMI — not invented PMI
facts) reshaped into the agent's native formats, and to keep a held-out gold set that is
never used to tune anything. Where real content can't naturally produce something the
agent needs (e.g. two PMI documents disagreeing on the same milestone date — earnings
calls don't have milestones), that is a documented limitation, not something papered
over with fabricated data.

### The pipeline (real data → PMI-shaped files, not the reverse)

| Layer | Real source | Rendered into | Status |
|---|---|---|---|
| Executive/SteerCo digest | ECTSum (in-repo, 2,425 pairs) + QMSum general-query | xlsx KPI tracker, pptx exec slide, pdf excerpt | M1 in progress |
| Workstream-detail report | QMSum specific-query | xlsx workstream sheet, docx status doc | not started |
| Action-item extraction | AMI (manual download, host blocks automation) | varied formats — **not** Jira-shaped | not started |
| Conflict probes | small subset of the above, one field deliberately perturbed in a duplicate rendering | 2 formats, `synthetic_perturbation: true` logged | not started |
| Gold set | LLM-drafted + human-reviewed, and/or anonymized real artifacts if available | same shape as above, held out, never tuned against | not started |

Every rendered record ships a `ground_truth.json` (entities expected, source record
traced back to the real corpus, conflict-probe flag) so detection/extraction can be
scored automatically instead of eyeballed — see the full plan for the schema.

### Status so far
- ✅ M0 — `katja-dataset` branch checked out from `origin/katja`; `scripts/make_sample_*.py`
  confirmed to still run unmodified (baseline, untouched by this work).
- ⏳ M1 — ECTSum → exec-digest augmentation (`scripts/dataset/prep_ectsum.py`,
  `render_to_pmi_formats.py`) — paused mid-build.

Full plan (context, the tautology problem explained, both gold-set authoring options,
directory layout, build order M0–M6): saved locally at
`~/.claude/plans/please-dont-merge-it-quizzical-hammock.md` (not yet committed into
`docs/`).
