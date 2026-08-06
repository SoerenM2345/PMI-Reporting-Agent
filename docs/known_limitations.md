# Known Limitations

Written per §21.17 — "Document incomplete functionality honestly."

This is the document to read before trusting anything the system produces.

## The guardrail

**Every output is a prototype and requires Senior Manager review before it goes to a
stakeholder.** It is printed on every slide, in every report, and in the UI. It is not
boilerplate: the system reads files written by people, and people write things down
wrong.

## Explicit V2 scope exclusions

Stated here, not just implied by absence, per REQ-10 and REQ-28:

- **No automated status collection from workstream leads.** V2 presumes a human has
  already uploaded files; it never polls or pulls status directly from a workstream lead.
  Any claim that this system "reduces manual effort" is bounded by that: it reduces the
  effort of *reconciling and reporting* files that already exist, not the effort of
  *producing* status updates in the first place. No code path in `app/` attempts such a
  pull.
- **No sentiment, tone, or cultural-signal enrichment.** The system extracts stated facts
  (dates, owners, figures, statuses) and never analyses how something was said. This was
  floated by interviewees as a possible future direction, not a near-term requirement; if
  revisited, it needs a named data source and method first, not a default-on heuristic.

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
- **A stated aggregate figure is not compared against its own computed roll-up.**
  `derive_workstreams()` (`app/agent/standardize.py`) already computes each workstream's
  progress as the mean of its tasks' `progress_percentage` — in Python, correctly, exactly
  as designed. But that computed value lives on the `Workstream` entity, a different
  collection from the `KPI` entities other documents' stated figures would standardize
  into, and cross-source matching does not currently compare across entity types. A
  workstream one-pager or dashboard that directly *states* "66% complete" is never checked
  against the tracker's own computed 59% — confirmed empirically: run the Dell-EMC v1.0
  corpus (`data/corpus/dellemc_vcio/v1.0/`) through the deterministic (Z) condition and
  conflict C1 (three documents stating three different WS3 progress figures) is not
  detected, with zero `kpi`-type records extracted from either the tracker or the
  workstream one-pager despite the "Progress vs. plan\n66%" text being present verbatim in
  the one-pager's extracted text. The gap is not extraction — the text is there — it is
  that nothing looks for it, and nothing would compare it against the derived figure if it
  were found.
- **A source's own text stating "this record is out of date" is not wired into
  conflict resolution.** The Dell-EMC corpus's escalation mail contains, verbatim,
  *"Das unterzeichnete Protokoll der Sitzung 01 fuehrt weiterhin D. Okonjo; ein
  Korrigendum reiche ich nicht nach"* ("the signed minutes still list D. Okonjo; I will
  not file a correction for that") — an explicit, machine-detectable admission that a
  higher-priority formal record was never amended. That text is extracted (it lands in a
  free-text `note` record), but conflict resolution (`app/agent/consistency/resolution.py`)
  only ever sees structured entity fields (e.g. `Task.owner`), which are evaluated with no
  connection back to the surrounding prose they were pulled from. Even a resolution rule
  built to detect "superseded"/"will not correct" language (a real, generalizable signal —
  not specific to this corpus) has nothing to attach it to under the current data flow. C6
  (the "was OP-01 reassigned without amending the signed minutes" conflict) fails for this
  reason, not for lack of a stale/critical severity concept.

  Both of the above were investigated and left unfixed deliberately rather than patched
  narrowly: a fix confined to this corpus's exact wording or entity names would be
  overfitting the detector to the test, not fixing the underlying gap. The real fix is
  cross-entity-type matching (compare a `KPI` against a `Workstream`'s computed value) and
  a link from free-text signals back to the structured conflicts they qualify — both
  genuine, multi-file changes to the extraction/matching layer, out of scope for a
  single-session patch. See `docs/PROTOCOL.md` "Infrastructure status" for how this affects
  the evaluation study specifically.

## Scale

This is a prototype, and the storage layer says so.

- Sessions are **local JSON files**. There is no database, no concurrency control, and
  no cleanup. Two people using the same session at once will race.
- There is **no authentication**. Do not expose it to a network you do not control.
- Uploads are capped at 25 MB per file (`UPLOAD_MAX_MB`).
- Everything is in-process and synchronous. A 50-file session with vision extraction on
  every screenshot will block the request thread for minutes.

## Verification status

Stated plainly, because an unverified claim in a limitations document defeats the point
of the document.

- ~~The Docker build has not been run.~~ **Resolved.** The image now builds and has
  been driven end to end inside the container: the React bundle is served, files upload,
  analysis runs, the text preview is returned, and a PDF is generated (so `fpdf2`
  installs correctly from `requirements.txt`). `chats.db` is written inside
  `/app/storage_data`, which `docker-compose.yml` already bind-mounts, so chats survive
  a restart with no compose change.

  The image also runs as a **non-root** user (`pmi`, uid 10001) and no longer ships the
  test runner — `requirements-dev.txt` carries `pytest`/`pytest-cov`/`httpx`. Verified in
  the container: correct uid, `pytest` absent, `/app/storage_data` writable, the full
  upload → analyse → preview → PDF flow working, and chats surviving a `docker restart`.
- **The live vision path has not been run against a real model.** See "Testing" below.

## Functional requirements not yet met

Against `Functional_Test_Requirements.md`'s 28 machine-verifiable requirements. The gap
column states what's actually missing, not just "no test" — most of these need a feature,
not a test.

| REQ | What's missing | Size |
|---|---|---|
| REQ-4 | German OCR (`pytesseract` call has no `lang=` argument — English only), and the fallback order is inverted from spec: vision runs first, OCR is the fallback, not "OCR primary, vision fallback on low confidence" (`_OCR_CONFIDENCE` is a hardcoded constant, never measured against a real score) | Medium — two independent fixes in `app/extractors/image.py` |
| REQ-41 | No role-based access control anywhere. No roles, no permission checks, no login | Large — a real auth/RBAC system, currently entirely absent |
| REQ-45 | No network-egress allowlist or infra-level sandbox enforcement; relies on convention (the corpus being synthetic) rather than a technical control | Large — infra/deployment work, not application code |
| REQ-47 | No second, independently-annotated 15-30 case gold set with Cohen's kappa agreement exists. The Dell-EMC corpus (`data/corpus/dellemc_vcio/`) is a different artifact: one generator process, audited by its own author, not cross-annotated — it does not satisfy this requirement even though it looks similar | Large — needs a second annotator's time, not code |
| REQ-63 | No benchmark against an externally deployed rule-based PM tool. The closest analog is this project's own internal "Z" no-LLM condition (`docs/evaluation_study_design.md` Design A), which measures this system's own floor, not incremental value over a competing product | Needs access to a comparison tool, not code |

REQ-44 (no OpenAI in production) and REQ-48 (manual-baseline timing study) are governance
sign-offs and human-participant studies respectively — not code gaps, see
`docs/PROTOCOL.md` and `docs/evaluation_study_design.md` §4 "Cost and effort" for where
each is tracked.

## Testing

288 tests, all passing, running with **no API key** — enforced rather than assumed:
`conftest.py::_no_live_provider` forces `LLM_PROVIDER=none` and strips the provider env
vars, so the result does not depend on a developer's `.env` or shell. Before that fixture
existed the suite silently made real, paid API calls whenever `.env` named a working key.

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
