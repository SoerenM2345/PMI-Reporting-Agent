# User Guide

For the PMI professional: an IMO lead, a PMO analyst, a workstream lead, or whoever is
building the Steering Committee pack this week.

## What this does

You drop in the files you have. It reads them, notices where they disagree with each
other, asks you about the disagreements that matter, and produces a deck, a dashboard or
a chart — with every figure traceable to the file it came from.

## What it will not do

**It will not guess.** If your masterplan says 82% and your SteerCo deck says 75%, it
will not quietly pick one and print it. It will stop and ask you. If a risk register has
no owner for a critical risk, it will not leave a blank cell — it will put "NO OWNER" on
the slide in red.

This is the whole point. A tool that silently resolves a disagreement into a confident
number is worse than no tool, because it launders the disagreement into a fact — and the
fact goes to a board.

## Getting started

```bash
docker compose up
```

Then open <http://localhost:8000>.

Or, without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend ci && npm --prefix frontend run build
uvicorn app.main:app --reload
```

### The API key

Optional, but it changes what the system can do.

```bash
cp .env.example .env
# add ANTHROPIC_API_KEY=sk-ant-...
```

**Without a key**, everything still runs — extraction, all 39 consistency checks,
conflict resolution, and the generated files. What you lose is the semantic layer:
summaries become templates, and **images cannot be read at all**. The agent will tell
you so, in the report.

**With a key**, screenshots of risk dashboards, photos of whiteboards and scanned pages
are interpreted, and the executive summary is written rather than assembled.

## The workflow

### 1 · Upload

Drag in whatever you have. Excel, CSV, PowerPoint, Word, PDF, HTML exports, and images
(PNG, JPG). Screenshots and photos are genuinely supported — that is what the image
pipeline is for.

The agent assumes all the files belong to **one PMI project**.

### 2 · Project details

Optional, and worth thirty seconds.

- **Reporting date** — without it, the agent uses today to decide what is overdue.
- **Day 1 date** — without it, the check for Day-1 work scheduled *after* Day 1 cannot
  run at all. The report will tell you it was skipped.

### 3 · Ask for what you need

Plain language:

> *"Create a SteerCo presentation for the current PMI status."*
> *"Create a weekly IMO status report."*
> *"Create a Finance dashboard for integration costs and synergies."*
> *"Create a risk heatmap for the integration."*

If the agent cannot tell **who the report is for**, it asks. It does not guess, because
the audience reshapes the entire document: a Steering Committee wants decisions and
escalations; an IMO wants overdue tasks and missing updates. A report aimed at the wrong
audience is a report for nobody.

### 4 · Resolve the conflicts

This is the part that matters.

The agent shows every place your sources disagree, **with the location of each claim** —
not "two files disagree", but "sheet `Workplan` cell A7 says 82%, slide 4 of the SteerCo
deck says 75%".

Minor disagreements are resolved automatically by source priority (a tracker outranks a
deck; a deck outranks a screenshot). Disagreements that **change the management
message** — overall status, Day 1 readiness, go-live dates, budget totals, synergy
realization, critical risks — are put to you.

For each one you can either:

- **pick a source** — "the masterplan is right", or
- **type the correct value** — because sometimes both files are stale, and picking the
  least-wrong one is not a resolution.

You cannot generate a report while a critical conflict is open. You can override that,
and the outputs will say so on their face.

### 5 · Download

You get:

| File | What it is |
|---|---|
| `PMI_Report_<Audience>_<date>.pptx` | The deck. Editable. |
| `PMI_Dashboard_<Audience>_<date>.xlsx` | Ten sheets, filtered and formatted. |
| `conflict_report_<date>.md` | Every disagreement, what each source said, and why one won. |
| `data_quality_report_<date>.md` | What this run could **not** do. |

**Read the data-quality report before you send the deck.** It tells you what was read
off a blurry screenshot, which files failed, and what the agent refused to guess.

## Reading the outputs

### The data-quality score

A blunt instrument, deliberately. Its job is to stop you presenting a deck built from
three contradictory files and a photograph as though it were a clean set of accounts.

It goes **down** for things that are not your data's fault — a file that failed to parse,
an image that could not be read, an LLM that fell back to templates. From a reader's
point of view those are all the same thing: the report is thinner than it looks.

### "Not Reported"

Wherever you see this, the source did not say. It does **not** mean zero.

A workstream shown at 0% has told the Steering Committee it achieved nothing. A
workstream shown as "Not Reported" has told them it did not report. Those are different
meetings, and the agent will not conflate them.

### ⚠ NO OWNER / NO MITIGATION

Not a rendering bug. A critical risk with no mitigation action is, very often, the single
most useful thing in the pack.

### Low-confidence findings

Anything read from an image, a scan or a photo, with the confidence shown. Verify these
against the source system before you rely on them. The agent caps image confidence at
90% — it is a transcription, and transcriptions have a failure rate that reading the
spreadsheet does not.

## Trying it out

```bash
python scripts/make_sample_data.py
python scripts/make_sample_extras.py
python scripts/make_sample_images.py
```

That writes an anonymised sample integration project into `data/samples/` — with
deliberate inconsistencies planted in it (§19), including the 82%-vs-75% progress
disagreement and an ERP go-live date that differs between the masterplan and a photo of a
whiteboard. Upload the lot and see what the agent finds.
