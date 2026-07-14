# PMI Reporting Agent

Agentic AI for automated Post-Merger Integration reporting.
*TUM Project Study x Deloitte 2026.*

Upload the week's integration files — a masterplan, a SteerCo deck, meeting minutes, a
portal export, a screenshot of a risk dashboard — and get back an audience-specific
PowerPoint, Excel dashboard or chart, with every figure traceable to the file it came
from.

Functional spec: `agent.md`. Implementation notes: [`MASTER.md`](MASTER.md).

## The idea

PMI reporting is not hard because the analysis is hard. It is hard because the
information is scattered across a dozen files that **disagree with each other**, and
somebody has to reconcile them by Thursday.

So this agent's most important behaviour is not what it produces. It is what it
**refuses** to produce:

- Your masterplan says 82% and your SteerCo deck says 75%? It stops and asks you. It
  does not quietly pick one.
- A critical risk has no mitigation owner? That goes on the slide, in red, rather than
  becoming a blank cell.
- It read a figure off a blurry photo of a whiteboard? The figure is in the report *and*
  in a "please verify" panel, with a confidence score.
- No vision model configured? It says the screenshot could not be read. It does not
  return an empty result and let you assume the file was blank.

A tool that silently resolves a disagreement into a confident number is worse than no
tool, because it launders the disagreement into a fact — and the fact goes to a board.

## Quick start

```bash
docker compose up
```

→ <http://localhost:8000>

Or locally:

```bash
python -m venv .venv && source .venv/bin/activate   # Python 3.12+
pip install -r requirements.txt
npm --prefix frontend ci && npm --prefix frontend run build
uvicorn app.main:app --reload
```

### API key (optional)

```bash
cp .env.example .env     # add ANTHROPIC_API_KEY=...
```

**Without a key everything still runs** — extraction, all 39 consistency checks, conflict
resolution, and every generated file. What you lose is the semantic layer: summaries
become template prose, and **images cannot be interpreted at all**. Every fallback is
recorded in the data-quality report, so a keyless run is honest about what it could not
do.

The provider is swappable (`LLM_PROVIDER=anthropic|openai|none`), and no model ID is
hard-coded anywhere but `app/config.py` — there is a test that enforces it.

### Try it on the sample project

```bash
python scripts/make_sample_data.py
python scripts/make_sample_extras.py
python scripts/make_sample_images.py
```

11 files with deliberate inconsistencies planted in them: the 82-vs-75 progress
disagreement, an ERP go-live date that differs between the masterplan and a photo of a
whiteboard, a budget total that does not match its own lines, and a critical risk that
exists *only* in a screenshot.

## How it works

```
upload → extract → standardize → calculate → match → check → resolve → generate
```

| Stage | What happens |
|---|---|
| **Extract** | One extractor per format: Excel, CSV, PowerPoint, Word, PDF, HTML, images. Every value keeps its origin — file, sheet, cell, slide, page, image region. |
| **Standardize** | Into the 14 entities of the spec's data model. A field the source did not state stays `None` — never a guess, never a zero. |
| **Calculate** | Risk scores, budget variances, synergy remainders, overdue flags. Deterministic Python, never the LLM. Where a source's own arithmetic is wrong, ours wins and the error is reported. |
| **Match** | "ERP go-live" in the plan and "ERP Go Live" in the deck are one milestone. Without this, no conflict is detectable at all. |
| **Check** | 39 checks: cross-source, mathematical, temporal, completeness. |
| **Resolve** | Minor conflicts settle by source priority (tracker > deck > screenshot). Conflicts that change the management message go to you. |
| **Generate** | Four audience decks, a ten-sheet workbook, ten chart types — plus a conflict report and a data-quality report, on every run. |

## The outputs

| File | What it is |
|---|---|
| `PMI_Report_<Audience>_<date>.pptx` | Editable deck. Management-message titles, source notes, limitations slide. |
| `PMI_Dashboard_<Audience>_<date>.xlsx` | Ten sheets, filtered, frozen, RAG-formatted. |
| `conflict_report_<date>.md` | Every disagreement, what each source said and **exactly where**, which value won, and why. |
| `data_quality_report_<date>.md` | What this run could **not** do. |

The deck states one number per fact, because a deck must. The other two files are where
the arithmetic behind that number is shown.

## API

| | |
|---|---|
| `POST /api/session` | new session |
| `POST /api/project` | project name, reporting date, Day 1 date, source-priority override |
| `POST /api/upload?session_id=` | add files |
| `POST /api/analyze` | extract → check → auto-resolve. Returns conflicts and a quality score. |
| `GET  /api/conflicts/{sid}` | what the sources disagree about |
| `POST /api/conflicts/{sid}/resolve` | pick a source, **or supply the correct value** |
| `POST /api/generate` | build the deliverable. **409** while a critical conflict is open. |
| `GET  /api/quality/{sid}` | the data-quality report |
| `GET  /api/download/{sid}/{file}` | fetch an output |
| `POST /api/report` | one-shot: analyse and generate |

Full schema at `/docs`.

## Tests

```bash
pytest -q            # 136 tests, no API key required
pytest -q --cov=app
```

`tests/test_acceptance.py` drives the spec's §20 scenario end to end — including
asserting that generation is **refused** while the progress conflict is open.

## Docs

| | |
|---|---|
| [architecture.md](docs/architecture.md) | How it is built, plus the 31-node spec traceability table |
| [pmi_data_model.md](docs/pmi_data_model.md) | The 14 entities, and the decisions the spec left open |
| [reporting_logic.md](docs/reporting_logic.md) | The 39 checks, conflict severity, audience templates |
| [user_guide.md](docs/user_guide.md) | For the PMI professional |
| [evaluation_plan.md](docs/evaluation_plan.md) | How to tell if it is good — and whether it is dangerous |
| [known_limitations.md](docs/known_limitations.md) | **Read this before trusting it** |
| [uat_questionnaire.md](docs/uat_questionnaire.md) | For practitioner testing |

## Deviations from the spec

Four, all deliberate, all documented in [known_limitations.md](docs/known_limitations.md):

1. **React + JavaScript + Tailwind** instead of Streamlit — which is §15's own listed
   alternative frontend.
2. **Anthropic (Claude)** as the default LLM instead of OpenAI — §15 requires the
   provider be swappable, and Claude is vision-capable, which the image pipeline needs.
   The OpenAI client is kept working and selectable.
3. **~13 LangGraph nodes** instead of §10's 31 — several spec nodes are one line of
   Python. All 31 are mapped in the architecture doc.
4. **Risk scales are 5×5**, and dates are *stored* as dates and *displayed* DD-MM-YYYY.
   The spec left both open.

## Guardrail

**Every output is a prototype and requires Senior Manager review before distribution to
stakeholders.** It is printed on every slide and in every report. It is not boilerplate:
the system reads files written by people, and people write things down wrong.

## Stack

Python 3.12 · FastAPI · LangGraph · Pydantic · Anthropic (swappable) · pandas ·
openpyxl · XlsxWriter · python-pptx · python-docx · PyMuPDF · pdfplumber ·
BeautifulSoup4 · Pillow · matplotlib · React · Tailwind · Vite · Docker
