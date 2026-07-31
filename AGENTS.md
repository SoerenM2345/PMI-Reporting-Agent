# PMI Reporting Agent

Agent that turns fragmented Post-Merger Integration files into audience-specific
reports. Spec is `agent.md` (gitignored). Design rationale: `MASTER.md`, `docs/`.

## Environment

System python is 3.9.6; this code needs **3.12+**. A `.venv` exists — use it.

- `.venv/bin/python -m pytest -q` — run tests (288, all green, **no API key needed**)

  `conftest.py::_no_live_provider` forces `LLM_PROVIDER=none` and strips the provider
  env vars, so the result does not depend on your `.env` or your shell. Verified green
  three ways: with a `.env` naming a live key, with hostile exported env vars, and with
  no `.env` at all. Before that fixture existed the suite made **real, paid API calls**
  (58s vs 6s) and failed 3 tests. Do not remove it to "test against a real model" —
  write that as a script instead.
- `.venv/bin/uvicorn app.main:app --reload` — run the app
- `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt` — rebuild the venv from scratch
- `npm --prefix frontend run build` — FastAPI serves `frontend/dist`; it's gitignored, so rebuild after a clean clone
- `python scripts/make_sample_{data,extras,images}.py` — the 11 §19 sample files (tests auto-generate these)

## Invariants that fail silently — read before editing

- **Model IDs live only in `app/config.py`.** A grep test enforces §21.10; one elsewhere fails the suite.
- **`HEADER_ALIASES` in `extractors/base.py` drives header-*row detection*, not just column mapping.** A short/generic alias makes data rows look like header rows and splits tables in half, losing every row below. Aliases <4 chars only match exactly.
- **The LLM never does arithmetic (§11).** Risk scores, variances, overdue flags: `agent/calculations.py`. Where a source's own arithmetic disagrees, ours wins and the error is reported.
- **Never return empty on failure.** An unreadable file emits a `note` record with `is_warning=True` so it reaches the data-quality report. Empty == "the file was blank", which is a different claim.
- **Missing means missing.** Unstated fields are `None` → rendered "Not Reported", never `0`.
- **Conflict severity escalates on *topic*, not magnitude** (`consistency/severity.py`). The spec's 82-vs-75 case is only a 9% delta; magnitude alone would auto-resolve it and the acceptance test would fail.
- **Renderers draw; they never decide.** What a report *says* is planned once in `app/report/planner.py` and rendered by `report/render/*` + `generators/pptx_report.py`. Re-deriving a figure or a title inside a renderer makes the deck disagree with the text preview the user approved — silently, because nothing compares them but `tests/test_api_content.py::test_what_the_preview_says_is_what_the_deck_says`.
- **A revision can never write a number.** `ops.ReviseOp` has no field that reaches a cell, tile or fact, and `guard.check_text` rejects any authored prose containing a figure outside `content.numeric_corpus_cached()`. Adding a `value:` field to that schema would quietly undo §11.
- **Stored content goes stale.** Resolve a conflict after planning and `content/vN.json` still states the losing source's figure. `report/store.is_stale` compares an `analysis_fingerprint`; `/api/generate` re-plans rather than rendering a stale draft. Removing that check produces confidently wrong decks.
- **`§9`'s source-priority override lives on `PMIProject`, not on settings.** Writing it to `get_settings()` makes one session's judgement about which files to trust govern every other session in the process, until restart. Pass it as `resolve_conflicts(..., priority_override=...)`.
- **Reading the files is a precondition of routing, not a handler's job** (`agent/conversation.py::respond`). When `_plan` owned it, the agent worked or dead-ended depending on which verb the user typed — "give me a deck" was `request_report` and read the files, "generate a deck" was `render` and replied "I haven't read the files yet", advice with no action behind it. Add an intent to `NEEDS_ANALYSIS` rather than re-checking inside a handler.
- **An analysis is only valid for the file set it was built from** (`conversation._analysis_covers`). Uploading more files mid-chat used to change nothing — `respond` re-analysed only when there was *no* analysis — so the report stayed built from the original files while looking current. The fingerprint in `report/store.py` includes `source_files` for the same reason.
- **Never diagnose a gap you have not measured.** The planner used to explain a missing summary as "the semantic layer was unavailable"; the real cause was a caller that never passed `bullets`. A report that misreports its own limitations sends the reader to debug the wrong thing.
- **Coerce by inspecting annotation *types*, not `str(annotation)`** (`agent/corrections.py`). `Optional[date]` renders as `typing.Optional[datetime.date]`, so a "date but not datetime" string check is false for every optional date field. `setattr` on a Pydantic model does not validate — pass values through `TypeAdapter` before writing them.
- **The chat transcript is not the source of truth.** `analysis.json` and `content/vN.json` are. That is the only reason `agent/budget.py` may compact old turns. If a decision ever gets *stored* in the transcript, compaction has to change.

## Patterns

- **Add a consistency check:** decorate with `@conflict_check` / `@issue_check` in `agent/consistency/` — it auto-registers.
- **Add an extractor:** a module exposing `suffixes`, `format`, `extract(path) -> list[dict]`. The dispatch table in `extractors/__init__.py` derives itself.
- **Generator tests assert structure** (slide titles, sheet names), never bytes — pptx/xlsx zips carry timestamps.
- `tests/conftest.py::FakeVisionClient` replays a stored vision reading and **declines non-vision schemas on purpose**, so the rest of the pipeline exercises its keyless fallbacks.

## Gotchas

- `python3 -c "...f\"{x}\"..."` inside a shell heredoc → SyntaxError (backslash in f-string). Write a temp `.py` file instead.
- Docker **is** available and the image is verified: `docker build -t pmi-agent .` then
  `docker compose up`. Driven end to end in-container (upload → analyse → preview →
  generate → restart), running as non-root `pmi`. Test deps live in
  `requirements-dev.txt`, so `pip install -r requirements.txt -r requirements-dev.txt`
  to run the suite locally. Changing `requirements.txt` invalidates the pip layer and
  makes the rebuild take ~5 min (PyMuPDF alone is a 25 MB wheel).
