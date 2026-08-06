# Corpus Integration Plan

How the `Syntetic_data` and `Syntetic_data_with_errors` folders become a first-class,
runnable evaluation fixture inside this repository — and what the front end looks like today,
since that is where a human sees the result.

Part 1 is a description of what exists. Part 2 is the technical work. The study design that
sits on top of it is a separate document: [`evaluation_study_design.md`](evaluation_study_design.md).

---

## Part 1 — The front end as it stands

### Stack and size

| | |
|---|---|
| Framework | React 18 + Vite 5, plain JavaScript (no TypeScript) |
| Styling | Tailwind 3, with PMI-specific tokens (`bg-rag-red`, `bg-rag-amber`) |
| Tests | Vitest + Testing Library, co-located `*.test.jsx` (3 files today) |
| Size | ~4,500 LOC across 25 components |
| Served by | FastAPI `GET /` — returns the Vite build if present, a legacy `static/index.html` if not, and an explicit "frontend not built" page otherwise |
| API surface consumed | `/api/session`, `/api/chats`, `/api/chat`, `/api/projects`, `/api/generate`, `/api/models` (47 routes exist in `main.py`; the UI uses a subset) |

### Structure

`App.jsx` holds all state by explicit convention. Two mutually exclusive main views:

- **Conversation** — the chat transcript. `Sidebar` (chat list) · `Composer` (input +
  attachments) · `MessageBubble` · `Thinking` · `ModelPicker` · `Artifacts` ·
  `PreviewPanel` / `PreviewBody`.
- **Project workspace** — `ProjectWorkspace`, a knowledge editor plus a versioned,
  editable report draft (`EditableReport`, `StatusPill`), both keyed by `project_id`.

Three components carry the product's actual argument:

- **`ConflictCard`** — one cross-source disagreement and its resolution UI. Deliberately asks
  *"which value should be used"*, not *"which file do you prefer"*, and always offers a free
  field for the correct figure, because when both sources are stale, picking the less-wrong
  one is not a resolution. Shows sheet / cell / slide / page / image region for every claim.
- **`LowConfidencePanel`** — every figure read out of an image, with its confidence bar, so a
  user knows which numbers to verify before walking into a room.
- **`Downloads`** — generated artefacts.

### The two invariants the UI is built around

1. **The front end computes nothing.** Every figure comes from the backend; the preview a user
   approves is byte-identical to what the renderer emits. This is what makes end-to-end
   fabrication testing meaningful — a number on screen can always be traced to a source.
2. **The transcript is append-only.** Uploading new files does not wipe the prior analysis; it
   appends a turn saying the earlier draft no longer matches. A conversation you can silently
   rewrite is not a record of anything.

`POST /api/generate` returns **409** while unresolved critical conflicts remain. The UI's job
at that moment is to render `ConflictCard`s rather than a report. **For evaluation this is the
single most important behaviour in the system**, and it is only observable through the API — so
the harness in Part 2 must drive the API, not the internal functions.

### Gaps relevant to evaluation

- No run identifier or model/version stamp is surfaced in the UI, so a screenshot of a report
  cannot be traced to the run that produced it. Needed for human rating (Part 2, step 7).
- Thin front-end test coverage (3 of 25 components). Not blocking, but the conflict-resolution
  path deserves a test because it is the honesty surface.

---

## Part 2 — Integrating the corpora

### What is being integrated

| Folder | Contents | What it tests |
|---|---|---|
| `Syntetic_data` | 21 documents, one fact base, **6 conflicts planted by design** | Extraction, cross-source conflict *detection*, escalation, transcript→minutes summarisation |
| `Syntetic_data_with_errors` | Byte-identical copy + **10 injected flaws** (`00_ERROR_KEY.xlsx`) | Robustness: corruption, metadata contradiction, role collision, plan-vs-report date drift, arithmetic that does not follow |

Note the arithmetic: the error corpus is a *copy* of the clean one, so it contains
**16 findable issues** (6 designed conflicts + 10 injected errors), not 10. Any scorer must
treat those as two separate labelled sets or the precision figure will be wrong.

The two folders answer different questions and should never be merged into one run.

### Step 1 — Move and version the fixtures (½ day)

Corpora currently sit at the repository root, mixed in with source. Move to:

```
data/corpus/dellemc_vcio/v1.0/
├── clean/                 21 documents
├── with_errors/           21 documents (1 renamed, 1 truncated)
├── generators/            case.py + g2_*.py + audit.py + inject_errors.py
├── ground_truth.json      ← step 2
├── error_key.json         ← step 2
├── MANIFEST.sha256        every file hashed
└── DATASHEET.md           ← step 8
```

Two things to fix while moving:

- **Rename `Syntetic_` → `synthetic_`.** Cheap now, permanent in a thesis repository later.
- **Freeze v1.0.** The corpus must be immutable once a result is recorded against it. Further
  work (weeks 1–2, adversarial documents) becomes v1.1 with its own manifest.

### Step 2 — Export ground truth (1 day) — *the blocking item*

`generators/case.py` already holds every record; nothing new needs authoring. Export to the
schema `MASTER.md` already specifies for the dataset-augmentation work, so both efforts land
on one format:

```jsonc
{
  "corpus_version": "dellemc_vcio_v1.0",
  "entities": {
    "milestones": [{"id": "M-07", "title": "...", "baseline": "2016-10-07",
                    "forecast": "2016-10-21", "status": "delayed", "workstream": "WS3",
                    "gate_relevant": true,
                    "stated_in": [{"file": "...xlsx", "sheet": "Meilensteine", "row": 11}]}],
    "tasks": [...], "risks": [...], "synergies": [...],
    "decisions": [...], "actions": [...], "dependencies": [...]
  },
  "conflicts": [{"id": "C2", "field": "M-07 forecast date", "kind": "designed",
                 "claims": [{"file": "...roadmap.pptx", "value": "2016-10-07"},
                            {"file": "...Wochenprotokoll.docx", "value": "2016-10-14"},
                            {"file": "...Mailverlauf.html", "value": "2016-10-21"}],
                 "correct": "2016-10-21", "resolution_rule": "most recent dated source",
                 "must_escalate": true}],
  "errors": [{"id": "E-01", "kind": "injected", "class": "corrupted_file",
              "file": "...Merger_Agreement_Key_Terms.pdf",
              "expected_behaviour": "report_unreadable"}]
}
```

Three fields carry the weight:

- `stated_in` — makes **extraction recall** computable per entity and per source file.
- `must_escalate` — makes **critical-conflict escalation** a pass/fail per conflict rather
  than a judgement call. C5 and C6 have no correct value; their expected behaviour is
  *surface the staleness*, so they need `"correct": null, "expected_behaviour": "flag_stale"`.
- `expected_behaviour` on errors — E-01 must produce an explicit *unreadable file* report.
  `MASTER.md` states that "there was nothing in it" and "I could not open it" are different
  statements. A silent skip on E-01 is a stop-ship defect, and the scorer must be able to say so.

Write `generators/export_ground_truth.py`; extend `audit.py` to assert the export matches the
documents it describes, so the ground truth cannot silently drift from the corpus.

### Step 3 — Manifest and integrity check (½ day)

`MANIFEST.sha256` plus a test that recomputes it. The whole value of the flawed corpus is that
exactly six files differ from the clean one; if someone opens a workbook in Excel and saves it,
that property is gone and no one notices. The test makes it noisy.

### Step 4 — The harness (2 days)

`scripts/eval/run_corpus.py`, driving the **public API** exactly as the front end does:

```
POST /api/session  →  POST /api/upload (×21)  →  POST /api/analyze
   →  GET /api/conflicts/{id}          # record what was detected, before resolution
   →  POST /api/generate               # MUST be 409 if critical conflicts are open
   →  POST /api/conflicts/{id}/resolve # apply ground-truth resolutions
   →  POST /api/generate               # now expect 200
   →  GET /api/quality/{id}, /api/issues/{id}, download artefacts
```

Emits one `run.json` per run: run ID, git SHA, corpus version + manifest hash, provider,
**exact model ID**, temperature, seed, prompt-file hashes, wall-clock, token counts and cost,
every API status code, and the full conflict and quality payloads. Without this, no result is
reproducible and none of it belongs in a thesis.

The 409 assertion is the most valuable single line in the harness. It is the difference between
a system that escalates and one that merely logs.

### Step 5 — The scorer (2 days)

`scripts/eval/score.py`, consuming `run.json` + `ground_truth.json`, emitting a flat CSV
(one row per run × metric) ready for R or pandas. Metric definitions in
[`evaluation_study_design.md`](evaluation_study_design.md) §4; the scorer implements them, it
does not define them.

Two need care:

- **Fabrication** — every numeric token in the generated deck/workbook must resolve to a
  `stated_in` location or a documented derivation. Implement as: extract numbers → match
  against ground truth ∪ arithmetic closure over it → anything left is a candidate fabrication
  → **manual adjudication**, because a correctly derived subtotal is not a fabrication and no
  regex knows the difference. Report adjudicated, not raw.
- **Conflict precision** — needs the union set (6 + 10) in the error condition, and a decision
  on how to treat a conflict that is real but was not planted. Recommendation: a third
  category, `unplanted_true_positive`, counted separately and adjudicated. Scoring it as a
  false positive punishes the agent for being right.

### Step 6 — Wire into pytest, but keep it out of the default run (½ day)

`tests/test_corpus_dellemc.py`, marked `@pytest.mark.corpus` and deselected by default so
`pytest -q` stays at 136 green tests with no API key. Two tiers:

- **Keyless smoke** (CI-safe): all 21 files parse, the manifest matches, ground truth is
  self-consistent, E-01 is reported as unreadable rather than skipped.
- **Full run** (needs a key, nightly or manual): the metric suite.

### Step 7 — Surface a run ID in the UI (½ day)

So a rated report can be traced to the run that produced it. Blocks the human-evaluation arm.

### Step 8 — Datasheet (1 day)

`DATASHEET.md` following *Datasheets for Datasets*: motivation, composition, collection
process, preprocessing, uses, distribution, maintenance. **The provenance split already
recorded in `00_README_Corpus.md` — what is `[PUBLIC]` and traceable to the SEC filing or the
advisory case study, and what is `[SYNTHETIC]` — is the core of it and is already written.**
Must state plainly that operational content is invented and that no statement is attributed to
any real named individual.

### Order and effort

| Step | Effort | Blocks |
|---|---|---|
| 2 · Ground truth export | 1 d | **everything** |
| 1 · Move and version | ½ d | 3, 4 |
| 3 · Manifest | ½ d | validity of the error condition |
| 4 · Harness | 2 d | 5, 6 |
| 5 · Scorer | 2 d | all quantitative results |
| 6 · pytest wiring | ½ d | regression protection |
| 7 · Run ID in UI | ½ d | human-evaluation arm |
| 8 · Datasheet | 1 d | publication |

**≈ 8 working days** to a state where a result can be produced and defended. Steps 2 and 5 are
where the intellectual work is; the rest is plumbing.

### Two decisions to take before starting

1. **Which repository is canonical.** `~/Downloads/Projects/PMI/PMI-Reporting-Agent` is an
   older tree that also received an image extractor. This repo already has its own, written
   against §5.6. Retire one before more work lands in both.
2. **Whether the corpus is a fixture or a dataset.** A fixture lives in `tests/fixtures/` and
   serves regression testing. A dataset lives in `data/`, has a datasheet and a version, and
   can be cited. The plan above assumes the second, because the thesis needs something
   citable. That choice is worth making explicitly rather than by accident.
