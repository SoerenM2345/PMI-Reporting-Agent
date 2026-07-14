# Known Limitations

Written per §21.17 — "Document incomplete functionality honestly."

This is the document to read before trusting anything the system produces.

## The guardrail

**Every output is a prototype and requires Senior Manager review before it goes to a
stakeholder.** It is printed on every slide, in every report, and in the UI. It is not
boilerplate: the system reads files written by people, and people write things down
wrong.

## Deviations from the spec

| # | Spec says | We did | Why |
|---|---|---|---|
| 1 | Streamlit frontend (§15, §17, §18.1) | React + JavaScript + Tailwind | §15 itself lists "React and JavaScript and TailwindCSS" as the alternative frontend. Deliverable #1 is read as "a frontend". |
| 2 | OpenAI (§15) | Anthropic (Claude) by default | §15 says the provider "should be possible to change". Claude is vision-capable, which is what the §5.6 image pipeline needs. The OpenAI client is kept working and is selectable with `LLM_PROVIDER=openai`. |
| 3 | 31 workflow nodes (§10) | ~13 LangGraph nodes | Several spec nodes are one line of Python. All 31 are mapped in [architecture.md](architecture.md#10-node-traceability). |
| 4 | `risk_score = probability × impact` (§6.5) | 5×5 scales, documented | The spec gives the formula but never the scales. See [pmi_data_model.md](pmi_data_model.md#risk-scales-65). |
| 5 | "Normalize dates to DD-MM-YYYY" (§7) | Stored as dates, *displayed* DD-MM-YYYY | Storing strings would break every temporal check in §8.3. |

## What does not work without an API key

The pipeline runs end to end with no key: extraction, standardization, all 39 checks,
conflict resolution and file generation are deterministic Python. What you lose:

| Feature | Without a key |
|---|---|
| **Image interpretation (§5.6)** | **Does not work at all.** The agent reports that it could not read the image and says its contents are missing from the report. It does not guess. Optionally, local OCR (`requirements-ocr.txt`) reads *text* — but a risk heatmap is colour and position, and OCR sees neither. |
| Executive summaries | Template prose from `app/llm/fallbacks.py`. Accurate, but not analysis. |
| Request parsing | Keyword matching. "SteerCo" still resolves to the Executive audience; unusual phrasings may not. |
| Entity extraction from prose | Regex only. A risk mentioned in a paragraph of a PDF, rather than in a table, will be missed. |

Every fallback is recorded as a warning and reaches the data-quality report. A keyless
run is honest about what it could not do — the failure mode we were most careful to
avoid is a report that looks identical whether or not the model ever ran.

## Extraction limits

- **Scanned PDFs** are sent to the vision model as a document. Without a key, the pages
  are reported as unreadable.
- **Merged cells** in Excel are read as a single value in the top-left cell; the rest
  read as empty.
- **Charts in PowerPoint** are read when they carry native series data. A chart pasted
  as a picture is not read (it is an image inside a deck, and we do not currently
  extract embedded images from slides).
- **Formulas with no cached value** — a workbook never opened in Excel — read as empty.
  This is detected and reported rather than guessed at.
- **`.xls`** (the pre-2007 binary format) is read by pandas but not by the formula check.
- **Entity matching** is deterministic (normalized text + token overlap at a 0.75
  threshold). It is tuned to prefer a *missed* match over a *false* one: a missed match
  means a conflict goes undetected, but a false match silently merges two different
  things and destroys one of them. The LLM is permitted to match semantically (§11) but
  is not currently wired in for it.

## Conflict detection limits

- Conflicts are detected between **matched entities**. Two files that describe the same
  risk in genuinely different words may not be matched, and their disagreement then goes
  unseen.
- A figure stated only in **prose** (e.g. "synergies captured to date: EUR 6.5 million"
  in a PDF paragraph) is not currently extracted as a `Synergy` entity without an LLM,
  so it cannot conflict with the synergy tracker. With a key and LLM entity extraction
  enabled, it would.
- **`PMI-012` (reporting period)** only fires when files carry explicit `StatusUpdate`
  periods. A deck that is silently three weeks stale, with no date on it, cannot be
  detected as stale by any means available to us — and this is a real and common failure
  mode in PMI reporting.

## Scale

This is a prototype, and the storage layer says so.

- Sessions are **local JSON files**. There is no database, no concurrency control, and
  no cleanup. Two people using the same session at once will race.
- There is **no authentication**. Do not expose it to a network you do not control.
- Uploads are capped at 25 MB per file (`UPLOAD_MAX_MB`).
- Everything is in-process and synchronous. A 50-file session with vision extraction on
  every screenshot will block the request thread for minutes.

## Not yet verified

Stated plainly, because an unverified claim in a limitations document defeats the point
of the document.

- **The Docker build has not been run.** Docker was not available on the development
  machine. The `Dockerfile` and `docker-compose.yml` are written and reviewed, and the
  application they wrap is verified working (uvicorn + the built React bundle, driven end
  to end), but `docker compose up` itself is untested. Run it before demoing.
- **The live vision path has not been run against a real model.** See "Testing" below.

## Testing

136 tests, all passing, running with **no API key**. Coverage: 88%.

The two provider clients (`app/llm/anthropic_client.py`, `app/llm/openai_client.py`) show
0% coverage. They only execute when a real key is present, and mocking the SDK to hit
them would test the mock, not the integration. They are exercised by
`scripts/record_vision_fixture.py` and `scripts/demo_acceptance.py`, both of which need a
key.

The image pipeline is tested against a **stored vision fixture**
(`tests/fixtures/vision/risk_dashboard.json`), which is currently **hand-authored** to
match the schema rather than captured from a live model. That proves the plumbing —
confidence scoring, region mapping, conflict detection, the deck picking up an
image-sourced risk. It does **not** prove that the model reads a risk heatmap correctly,
and that gap is the most important untested thing in this repository.

Only a live run does that. Re-record the fixture with:

```bash
ANTHROPIC_API_KEY=... python scripts/record_vision_fixture.py
```

and read the diff. If the model misses the GDPR risk, or scores it at 0.95 confidence,
that is a finding about the prompt — not a test to be patched.
