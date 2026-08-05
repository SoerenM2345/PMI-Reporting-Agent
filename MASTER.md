# MASTER — What This Codebase Does and How It Is Built

Single source of truth for the implementation. The functional spec is
`2026_DPID_PreCourseMeeting.pdf` (slides 5–7); this file describes how the code
realizes it. For how to *use* the app, see `README.md`.

## What this is

A **single-agent Automated Reporting & Status Updates system** for Post-Merger
Integration (PMI). A consultant uploads the files gathered over the week (Excel
trackers, PowerPoint updates, Word meeting notes, PDFs, HTML), types what they
need ("Create a SteerCo PowerPoint"), and the agent produces an
audience-specific PowerPoint report, Excel dashboard, or chart — including
task assignments per person and cross-source consistency checking.

This is **Version 2** (single agent, LangGraph) as defined in
`../UC2_V2_SingleAgent_Definition.md` — the counterpart to Version 1's
three-sub-agent design in `PMI-Coordination-Agent`.

## The 7-step workflow (spec slide 5 → `app/agent/graph.py`)

| # | Step | Node / code |
|---|------|-------------|
| 1 | User uploads PMI files + request | `POST /api/upload`, `POST /api/report` (`app/main.py`) |
| 2 | Ask role/audience (Executive/PMO/Finance) if unclear | `parse_request` node; graph ends early with `needs_audience`, UI asks, request is re-sent |
| 3 | Extract data from Excel/PPTX/PDF/Word/HTML | `extract` node → `app/extractors/` |
| 4 | Standardize into one PMI data model | `standardize` node → `app/agent/standardize.py` |
| 5 | Consistency checks (e.g. Excel 82% vs PPT 75%) | `check_consistency` → `app/agent/consistency.py::detect_conflicts` |
| 6 | Conflict handling: Option A ask user / Option B priority Excel > Word/PDF > PPT > HTML | `resolve_conflicts` node; priority in `app/models/pmi.py::SOURCE_PRIORITY` |
| 7 | Generate output (PPTX / XLSX dashboard / chart) | `generate_output` → `app/generators/` |

## Module map

```
app/
├── main.py               FastAPI: session, upload, report, download endpoints
├── models/pmi.py         Pydantic PMI schema: TaskItem, Milestone, Risk, BudgetItem,
│                         KPI, Conflict, PMIDataModel; SOURCE_PRIORITY
├── extractors/
│   ├── base.py           header-alias mapping (EN+DE), status/date/number/percent
│   │                     normalization, progress-mention regexes, action-item
│   │                     extraction from free text, table classification
│   ├── excel.py          pandas; header-row detection; all sheets; cell scan for "%"
│   ├── powerpoint.py     python-pptx; tables + text frames per slide
│   ├── word.py           python-docx; tables + paragraphs (meeting notes)
│   ├── pdf.py            pdfplumber; tables + page text
│   ├── html.py           BeautifulSoup4; tables + visible text
│   └── __init__.py       extension → extractor dispatch
├── agent/
│   ├── graph.py          LangGraph StateGraph wiring of the 7 steps
│   ├── state.py          AgentState TypedDict
│   ├── standardize.py    raw record dicts → validated PMIDataModel
│   ├── consistency.py    conflict detection (KPI + task level) and resolution
│   └── llm.py            OpenAI (gpt-5.5, env-switched) OR deterministic mock
├── generators/
│   ├── pptx_report.py    Deloitte-styled deck: title, exec summary, tasks-per-owner,
│   │                     milestones, risks, budget (Finance), KPIs, conflicts slide
│   ├── xlsx_dashboard.py Overview (+embedded chart), Tasks grouped by owner with
│   │                     autofilter, Milestones, Risks, Budget, Conflicts sheets
│   └── charts.py         matplotlib: risks-by-severity, tasks-by-status, budget
└── storage/json_store.py local JSON session store (spec: "Storage (Prototype): Local JSON")

static/index.html          drag-and-drop UI (vanilla JS, no build step)
scripts/make_sample_data.py generates sample inputs incl. the 82%-vs-75% conflict
tests/test_pipeline.py     unit + end-to-end + API round-trip tests
data/ectsum/               ECTSum dataset (train 1681 / val 249 / test 495) — see data/README.md
data/samples/              generated sample inputs
```

## Key design decisions

- **Extraction is deterministic-first.** Tables are parsed via fuzzy header
  mapping (`HEADER_ALIASES`, English + German); free text goes through regex
  action-item/progress extraction. The LLM never invents numbers — it only
  classifies the request and words the summary. This keeps outputs auditable
  (project rule: precision) and lets the whole pipeline run without a key.
- **LLM switch is environmental.** `OPENAI_API_KEY` set → OpenAI `gpt-5.5`
  (model name via `OPENAI_MODEL`); unset → deterministic mock. All LLM failures
  fall back to heuristics — the pipeline never hard-fails on the LLM.
- **Audience question = graph interrupt.** If step 2 can't infer the audience,
  the graph ends before extraction and the API returns `needs_audience: true`;
  the UI shows Executive/PMO/Finance chips and re-submits.
- **Conflicts carry provenance.** Every record keeps a `SourceRef`
  (file, format, sheet/slide/page). Conflicts store per-file values, the winning
  value, which file won, and whether resolution was `source_priority` or `user`.
- **Guardrail (from interview evidence, binding per UC2_V2 §2):** outputs are
  prototypes for **Senior Manager review before stakeholder distribution** —
  stated in the UI footer and README. Jira is intentionally not required.

## Known scope cuts (deliberate, per spec + UC2_V2 §7)

- **No meeting-recording/transcript ingestion** — slide 5's input list is
  documents only. Open team decision; Word meeting *notes* are supported.
- **SQLite** marked optional in spec — not used; local JSON only.
- **Conflict detection** covers same-name KPIs (incl. Overall Progress) and
  same-title tasks (status/progress). Fuzzy entity matching (near-identical
  titles) is future work.
- **ECTSum** is included for later evaluation of the generation step (see
  `data/README.md`), not wired into runtime.

## Roadmap — planned, not yet implemented

- **RAG + SM-review flywheel** (2026-07-24 decision, `docs/TrainingData_Decision.md` §8):
  replaces training on weak-fit proxy datasets with retrieval-augmented generation
  fed by the Senior Manager review step. Full build plan, milestones, and
  acceptance criteria: `docs/RAG_Flywheel_Engineering_Handoff.md`. Design
  reference for the review UI (static mockup, not wired): `static/review_mockup.html`.
  None of M1–M8 in that plan exist in this codebase yet — the "Key design
  decisions" and module map above describe the system as it runs today, not
  this roadmap. Check `OPEN_POINTS.md` #7/#15/#16 for current status before
  assuming any part of it is built.

## Testing

`pytest -q` from repo root: header/status/percent normalization units,
per-format extractor tests, conflict detection incl. the spec's 82/75 example
(asserts Excel wins by priority and ask-mode leaves critical conflicts open),
three full agent runs (PPTX, XLSX, audience-question path), and a FastAPI
TestClient round-trip (upload → report → download).
