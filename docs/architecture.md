# Architecture

How the system is built, and why it is built that way. The functional spec is
`agent.md`; this document maps it onto the code.

## The shape of the problem

A PMI professional has a folder of files from this week: a masterplan, a SteerCo deck
somebody edited on a plane, meeting minutes, a portal export, and a screenshot of a
risk dashboard because nobody could find the original. They disagree with each other.
Some of them are wrong. The consultant needs a Steering Committee deck by Thursday.

Two properties follow from that, and they shape every design decision below:

1. **The sources conflict, and the conflicts matter.** A tool that silently picks one
   number is worse than no tool, because it launders a disagreement into a fact.
2. **A confident wrong number is the worst possible output.** These decks go to boards.
   Everything here is built so that the system would rather say "I don't know" or
   "these two files disagree" than produce a plausible figure it cannot defend.

## Pipeline

```
     upload ─→ extract ─→ standardize ─→ calculate ─→ match ─→ check ─→ resolve ─→ generate
                  │            │             │           │        │         │          │
             per-format    one schema   deterministic  cross-  38 checks  §9 A/B/C  pptx/xlsx/
             extractors    (§6, 14      Python only    source  (§8.1-8.4)           charts +
             (§5)          entities)    (§11)          groups                       2 reports
```

Every stage keeps provenance. A number on slide 7 of the output can be traced to
`Integration_Masterplan.xlsx`, sheet `Workplan`, cell `A7` — with the confidence of
that reading attached.

## Module map

| Area | Module | Does |
|---|---|---|
| Config | `app/config.py` | Every model ID, threshold and policy knob. The only place a model ID may appear (§21.10, enforced by a test). |
| LLM | `app/llm/` | Provider abstraction (Anthropic default, OpenAI kept, Null for no-key). One method: `structured()`, always returning a validated Pydantic object (§11). |
| Extractors | `app/extractors/` | One module per format. Each exposes `suffixes`, `format`, `extract(path) -> list[dict]`. |
| Model | `app/models/` | The 14 spec entities (§6), provenance (§6.14), conflicts and quality (§8, §9). |
| Calculations | `app/agent/calculations.py` | Risk scores, budget variances, synergy remainders, overdue flags. Deterministic Python — never the LLM (§11). |
| Matching | `app/agent/matching.py` | "ERP go-live" in the plan and "ERP Go Live" in the deck are one milestone. |
| Checks | `app/agent/consistency/` | 32 registered checks across four families, plus 7 derived-value checks in `calculations.py`. |
| Quality | `app/agent/data_quality.py` | The score, and the honest account of what the run could not do. |
| Generators | `app/generators/` | Four audience decks (§12), ten workbook sheets (§13), ten chart types (§14), and the two reports that ship with every run. |
| Graph | `app/agent/graph.py` | Three compiled LangGraph graphs over shared nodes. |
| API | `app/main.py` | FastAPI. Also serves the built React bundle. |
| Frontend | `frontend/` | React + JavaScript + Tailwind (Vite). |

## Decisions worth explaining

### Three graphs, not one

`ANALYSIS_GRAPH`, `GENERATION_GRAPH`, `FULL_GRAPH` — over one set of node functions.

The split exists because **generation must never re-run extraction.** The original
design ran a single graph, so the human-in-the-loop round trip re-ran it from the top.
Once image extraction (§5.6) landed, that meant paying for a vision call every time the
user resolved a conflict — and re-rolling the dice on what the model saw, so the answer
could change underneath them between the question and their reply.

Analysis runs once and is persisted (`storage_data/<session>/analysis.json`).
Resolving a conflict patches that file. Generating reads it.

### No LangGraph checkpointer

We considered `interrupt()` with a checkpointer for the human-in-the-loop step and
rejected it. `MemorySaver` dies on a uvicorn reload, which is fatal for a demo;
`SqliteSaver` adds a dependency and `thread_id` plumbing to buy durability the
prototype already gets free from the JSON session store.

*Upgrade path:* if this ever needs durable multi-turn agents, `SqliteSaver` plus a
`thread_id` per session is the change, and the node functions do not move.

### ~13 nodes, not §10's 31

§10 lists 31 workflow nodes. Implementing 31 LangGraph nodes would be ceremony — several
are one line of Python. The traceability table below maps all 31 to where they live.

### The LLM does not do arithmetic

§11 says the model must not be the final authority for calculations, dates, budget
variances, synergy figures, risk scores, or file generation. It isn't. `calculations.py`
computes all of them in plain Python, and where a *source* reports a derived value that
disagrees with the computed one, the computed value wins and the disagreement is
reported (`MATH-003`, `MATH-007`). A tracker that gets its own arithmetic wrong should
not have that error laundered into a board pack.

The model classifies the request, interprets images, matches entities, and writes prose.
Every one of its outputs is schema-validated by Pydantic before it enters the pipeline.

### Images are the least-trusted source

§9 ranks images last, and §21.14 says to treat image extraction as low-confidence unless
confirmed. So:

- Confidence is computed in **Python** from measured image quality (resolution, blur)
  and the model's self-report — the model is not the authority on how much to trust the
  model.
- It is **capped at 0.90**. No image reading ever reaches full confidence.
- With no vision model and no local OCR, the extractor says the image could not be
  read. It does not return an empty list and let the report proceed as though the file
  were blank. "There was nothing in it" and "I could not open it" are different claims.

### Severity is assigned by topic, not just magnitude

This is the load-bearing detail of the whole conflict system.

The spec's own example (§8, §20) is a tracker saying 82% and a deck saying 75%. That is
a 9% relative delta. A severity rule based on the *size* of a disagreement would rank it
"medium", auto-resolve it by source priority, and never tell the user — but §20 step 9
requires the system to ask.

So `app/agent/consistency/severity.py` escalates on **topic** first, encoding §9's list
of critical conflicts (overall status, Day 1 readiness, go-live dates, budget totals,
synergy realization, critical risks, SteerCo decisions, TSA exits, regulatory
milestones). Magnitude is a second axis, not the first.

## §10 node traceability

All 31 spec nodes, and where each one lives.

| # | §10 node | Where |
|---|---|---|
| 1 | receive_pmi_request | `main.py::analyze` |
| 2 | create_project_session | `main.py::create_session` + `json_store.new_session` |
| 3 | validate_uploaded_files | `graph.py::validate_files` |
| 4 | detect_output_type | `graph.py::parse_request` → `llm/tasks.py::parse_request` |
| 5 | detect_target_audience | same |
| 6 | ask_audience_if_missing | `graph.py::_after_parse` → returns `needs_audience` |
| 7 | detect_reporting_period | `main.py::set_project` (user-supplied, §4 step 1) |
| 8 | classify_pmi_document_types | `extractors/base.py::classify_table` |
| 9 | extract_spreadsheet_data | `extractors/excel.py`, `extractors/csv.py` |
| 10 | extract_powerpoint_data | `extractors/powerpoint.py` |
| 11 | extract_pdf_data | `extractors/pdf.py` |
| 12 | extract_word_data | `extractors/word.py` |
| 13 | extract_html_data | `extractors/html.py` |
| 14 | extract_image_data | `extractors/image.py` + `utils/images.py` |
| 15 | classify_pmi_entities | `extractors/base.py::classify_table` + `rows_to_records` |
| 16 | standardize_pmi_data | `agent/standardize.py` |
| 17 | validate_pmi_data_model | Pydantic, at construction |
| 18 | match_entities_across_sources | `agent/matching.py` |
| 19 | run_pmi_consistency_checks | `agent/consistency/` (32 checks) |
| 20 | calculate_data_quality_score | `agent/data_quality.py::build_report` |
| 21 | resolve_low_priority_conflicts | `consistency/resolution.py` (Mode C auto path) |
| 22 | ask_user_about_critical_conflicts | `main.py::generate` returns **409**; UI shows the cards |
| 23 | apply_user_resolutions | `main.py::resolve_conflicts_route` → `resolution.py::apply_resolutions` |
| 24 | identify_management_messages | `generators/pptx_report.py::_status_message` and friends |
| 25 | plan_pmi_report | audience → deck template (`_steerco_deck`, `_pmo_deck`, …) |
| 26 | generate_pmi_charts | `generators/charts.py` |
| 27 | generate_powerpoint | `generators/pptx_report.py` |
| 28 | generate_excel_dashboard | `generators/xlsx_dashboard.py` |
| 29 | run_output_quality_checks | `graph.py::verify_outputs` — re-opens every file it wrote |
| 30 | generate_data_quality_report | `generators/quality_report.py` |
| 31 | deliver_outputs | `main.py::download` |

## Storage

Local JSON, per §15's "Storage (Prototype): Local project directories, JSON".

```
storage_data/<session>/
  meta.json       uploaded files, run history
  project.json    what the user told us (§4 step 1)
  analysis.json   the full analysis — model, conflicts, quality report
  uploads/        the files themselves
output/<session>/ generated deliverables
```

## Known deviations from the spec

Listed in full in [known_limitations.md](known_limitations.md), and summarised in the
README.
