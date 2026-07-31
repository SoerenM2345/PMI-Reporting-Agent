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
  upload → extract → standardize → calculate → match → check → resolve → plan → render
              │           │            │          │       │        │        │       │
         per-format   one schema  deterministic cross- 38 checks §9 A/B/C  one   pptx/xlsx/
         extractors   (§6, 14     Python only   source (§8.1-8.4)         Report docx/pdf/
         (§5)         entities)   (§11)         groups                    Content  html +
                                                                          (once)  2 reports
```

Everything left of `plan` is **analysis** — run once, persisted, never re-run to draw a
deck. Everything from `plan` right is **presentation** — planned once into a
`ReportContent`, then drawn by format-specific renderers, and revised in place through
chat. The two halves have separate stores and a staleness check between them
(see below).

Every stage keeps provenance. A number on slide 7 of the output can be traced to
`Integration_Masterplan.xlsx`, sheet `Workplan`, cell `A7` — with the confidence of
that reading attached.

The whole pipeline is driven by a **chat agent**, not a wizard. The user says "give me a
SteerCo deck", "these two disagree — trust the tracker", "adjust slide 3"; the agent
routes each turn to analysis, resolution, planning, revision or rendering. Reading the
files is a precondition of routing, not something a handler decides to do
(`agent/conversation.py`).

## Two shapes of the same system: session and project

The pipeline above is the **session** architecture: one chat → one session → one
`analysis.json`, rebuilt by re-reading *all* files whenever the set changes. It still
runs, and the endpoints and node table below still describe it.

Layered on top — and now the primary path — is the **project** architecture in
`app/project/`, a project-centric, continuously-updating workspace. The difference is
where knowledge lives and how it moves:

```
  a source arrives ─→ extract ONLY the new/changed file (content hash) ─→ cache records
  (file, message,   ─→ rebuild the model from the UNION of active files' cached records
   correction)          = standardize → calculate → match → check → resolve → quality
                     ─→ diff vs current → new knowledge VERSION + change_log
                     ─→ flag (never rewrite) affected drafts
```

The design principle is **incremental extraction, holistic re-derivation**. Extraction —
especially vision (§5.6) — is the only expensive, non-deterministic step, so it is the
only thing cached per file. The cheap, deterministic tail is re-run over the whole record
union, so a new Finance file can still conflict with a milestone read last week. Knowledge
is **versioned** (`knowledge/vN.json`), and every input — a file, a chat correction, a
conflict resolution — is a **source** that produces a new version. The one thing this must
never do is win a corrected value back from a file: a user's confirmed correction is
stored as a decision and re-applied on top of every future re-derivation.

Reports here are **editable free-text drafts**, versioned independently of knowledge; when
knowledge moves, a draft is *flagged* stale (per section, by dependency) but never
rewritten. Conflicts *inform* rather than block — a draft can always be made; only a
*final export* is held back when an unresolved critical figure would be presented as fact.
Export builds the deliverable from the saved draft, so it matches the approved text.

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
| Conversation | `app/agent/conversation.py` | Turns a chat message into an action and an action into replies. Owns intent routing and the `NEEDS_ANALYSIS` set. |
| Analysis / answers | `app/agent/{analysis,answers,knowledge}.py` | One way to read the files for every caller; the intent-to-answer router; what the *session* knows vs. what the *files* said. |
| Chat edits | `app/agent/{corrections,nl_updates,budget}.py` | User fills a gap the files left (§8.2); plain English that changes the data; the chat's context budget and compaction. |
| Report content | `app/report/{planner,content,facts,structure}.py` | The presentation layer. `planner` turns a `PMIDataModel` into one `ReportContent` — *what the report says*, decided once. `facts` computes every figure it may state; `structure` is the user-requested template. |
| Rendering | `app/report/render/` | One renderer per format (pptx, xlsx, docx, pdf, html, markdown). They draw a `ReportContent`; they never decide what it says. |
| Revision | `app/report/{ops,revise,guard}.py` | `ops` is the only way content is edited; `revise` turns "adjust slide 3" into ops; `guard` rejects any authored prose containing a figure outside the numeric corpus (§11). |
| Content store | `app/report/store.py` | Append-only versioned `content/vN.json`, plus the staleness check against the analysis fingerprint. |
| Generators | `app/generators/` | The direct audience decks (§12), workbook sheets (§13), chart types (§14), and the two reports that ship with every run. |
| Graph | `app/agent/graph.py` | Three compiled LangGraph graphs over shared nodes. |
| **Project store** | `app/project/{paths,models,repositories,json_repositories,locks}.py` | The project-centric store: `FileRecord`, `ProjectKnowledge`, `SourceEvent`/`AuditEvent`, `DraftRecord`, behind repository *protocols* (JSON today, swappable). Atomic, version-checked, fcntl-locked writes. |
| **Ingestion / rebuild** | `app/project/{files,rebuild}.py` | Content-hash file ingestion (skip unchanged, soft-delete removals) and the incremental engine that re-derives versioned knowledge from the active record union and re-applies confirmed corrections. |
| **Knowledge routing** | `app/project/{classify,facts}.py` | Classifies each message (fact / correction / question / instruction / scenario) and routes it: only confirmed, canonical-scoped facts update knowledge; proposed/uncertain become flagged open questions; instructions are audit-only. |
| **Drafts** | `app/project/{drafting,drafts}.py` | Editable free-text drafts (create from knowledge, section edit/regenerate, versions, restore) and per-section dependency-based staleness that flags but never rewrites. |
| **Orchestrator / export** | `app/project/{orchestrator,conflict_impact,docmodel,exporting}.py` | `/api/chat`'s brain (Markdown replies, not cards); the three-level conflict gate; and export of a saved draft to pptx/docx/pdf/xlsx/html/markdown via a normalized document. |
| Storage | `app/storage/` | `json_store` (session: meta/project/analysis) and `chat_store` (projects, chats, transcripts). Local JSON/SQLite (§15). |
| API | `app/main.py` | FastAPI. Session path (upload/analyze/conflicts/generate/content) **and** project path (`/api/chat`, project files, drafts, export). Serves the built React bundle. |
| Frontend | `frontend/` | React + JavaScript + Tailwind (Vite). Session chat, plus the project **Workspace** (Markdown chat + editable report). |

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

### What the report says is decided once, then drawn

A deck, a workbook, a Word doc and an HTML preview of the same run must agree — down to
the figure on the tile and the wording of the title. The way to guarantee that is to
plan the report *once*, into a format-neutral `ReportContent` (`report/planner.py`), and
have every renderer in `report/render/` be a straight mapping from block to furniture.

**Renderers draw; they never decide.** A renderer that re-derives a number or re-writes a
title makes the deck disagree with the preview the user approved — silently, because
nothing compares them but one test
(`test_api_content.py::test_what_the_preview_says_is_what_the_deck_says`). Every figure
the report is entitled to state is computed up front in `report/facts.py`; renderers read
it, they do not recompute it.

(`generators/` still holds the four direct audience templates from §12. The
planner-driven `report/` layer is the path the chat agent uses; both draw from the same
analysis and the same calculations.)

### Content is versioned, and it can go stale

Presentation content lives in `content/vN.json`, **append-only** and kept deliberately
separate from `analysis.json` — a revert or an edit writes a *new* version rather than
mutating the last one, so history is intact and a bad edit is one revert away
(`report/store.py`).

The danger is a draft that looks current but isn't: resolve a conflict *after* planning
and `vN.json` still states the losing source's figure. So every stored content carries an
`analysis_fingerprint` (model + quality + **source files**), and `store.is_stale`
compares it against the live analysis. `/api/generate` re-plans on a mismatch rather than
shipping a stale draft. Uploading more files mid-chat changes the fingerprint, which is
why the same file set is part of it — an analysis is only valid for the files it was
built from.

### A revision can never write a number

Chat edits go through `report/ops.py`, and `ReviseOp` has **no field that reaches a cell,
tile or fact** — it moves and rewords, it does not value. On top of that, `guard.check_text`
rejects any authored prose containing a figure outside the run's numeric corpus. The two
together are how §11 survives contact with free-text editing: the model may rewrite a
sentence, but it cannot introduce a number the pipeline did not compute.

### The transcript is not the source of truth

`analysis.json` and `content/vN.json` are. That is the *only* reason `agent/budget.py` is
allowed to compact old chat turns when the context budget runs out — nothing load-bearing
is stored in the conversation, so summarising it away loses nothing. If a decision ever
gets stored in the transcript, compaction has to change with it.

### The project workspace (`app/project/`)

Everything above is the session path. The project path applies the same rules — the LLM
never does arithmetic, missing means missing, provenance is kept, a correction is never
lost — but reorganises them around a versioned, project-scoped knowledge base shared by
every chat in a project. Its load-bearing decisions:

- **Incremental extraction, holistic re-derivation.** A file is extracted once and its
  records cached by SHA-256 (`files.py`); a rebuild re-runs only the cheap deterministic
  tail over the union of *active* files' records (`rebuild.py`), so unchanged files — and
  their vision calls — are never re-processed, yet cross-source conflict detection stays
  correct. A test asserts a cached read standardizes identically to a fresh one.

- **Knowledge vs audit are separate, and authority gates supersession.** Only fact-bearing,
  `confirmed`, canonical-scoped inputs update knowledge; a formatting request or a question
  is audit-only; a `proposed`/`uncertain` value is kept *beside* the current one and
  flagged; a `scenario` never touches canonical knowledge (`classify.py`, `facts.py`).
  Confirmed facts, assumptions, and open questions are three separate stores — a user's
  certainty is never conflated with a guess.

- **Corrections survive re-derivation.** A confirmed correction is stored as a
  `UserDecision` and re-applied onto every freshly standardized model *before* anything is
  derived from it, so re-reading the files never wins a corrected value back.

- **Writes are atomic and version-checked.** Rebuilds run under an `fcntl` project lock and
  hand `save_next` the version they read, so two concurrent rebuilds can neither clobber
  each other nor mint the same version (a stress test proves gapless versions under
  concurrency).

- **Drafts are flagged, never rewritten.** A draft records, per section, what it depended
  on; when knowledge moves, only the sections whose dependencies changed are marked stale,
  and a dependency that can't be resolved conservatively stales the whole draft — but the
  text is never touched, so a hand-edit is safe (`drafts.py`).

- **Conflicts inform, not block.** `conflict_impact.assess` grades conflicts into
  `non_blocking` / `requires_user_attention` / `blocking_final_export` and returns a
  capability state; a draft can always be made, and only a *final export* is gated.

- **Export comes from the saved draft.** `exporting.py` parses the draft's Markdown into a
  `NormalizedDoc` and builds each format from that — so an export reflects the user's edits
  and cannot re-plan a different narrative.

Storage, per project:

```
storage_data/projects/<project_id>/
  sources/
    files/<file_id>/…        the raw uploaded file
    records/<file_id>.json   its cached extractor output (by content hash)
    file_index.json          FileRecord[] — hash, status, active flag
    events.jsonl             SourceEvent log (knowledge sources)
    audit.jsonl              AuditEvent log (messages, drafts, exports)
  knowledge/
    current.json  versions/vN.json  .lock
  drafts/<draft_id>/current.json + vN.json
  exports/                   generated deliverables
storage_data/chats.db        projects, chats, transcripts (unchanged)
```

Business logic reaches all of this only through the repository protocols in
`repositories.py`, so the JSON/JSONL backend can become SQLite/Postgres without the agent
code changing. Migration from the session layout is `migrate.py`: one project per orphaned
session, copy-before-delete, idempotent.

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
| 24 | identify_management_messages | `report/messages.py` (§12.5 titles); `generators/pptx_report.py::_status_message` for the direct templates |
| 25 | plan_pmi_report | `report/planner.py::plan` → one `ReportContent`; audience selects the structure |
| 26 | generate_pmi_charts | `generators/charts.py`, named via `report/charts_registry.py` |
| 27 | generate_powerpoint | `report/render/pptx.py` (planner-driven); `generators/pptx_report.py` (direct templates) |
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
  content/        the presentation layer, append-only
    v1.json v2.json …   each planned/revised ReportContent
    HEAD                current version pointer
  uploads/        the files themselves
output/<session>/ generated deliverables
```

`analysis.json` is the analysis half; `content/` is the presentation half, versioned so a
revision or revert never destroys an earlier draft (`report/store.py`). Chat transcripts,
projects and their chats live separately (`storage/chat_store.py`) and are not the source
of truth for any figure — see "The transcript is not the source of truth" above.

## Known deviations from the spec

Listed in full in [known_limitations.md](known_limitations.md), and summarised in the
README.
