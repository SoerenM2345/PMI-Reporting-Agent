# PMI Reporting Agent

Automated Reporting & Status Updates for Post-Merger Integration —
TUM Project Study x Deloitte 2026. Upload your weekly PMI files, describe the
report you need, get an audience-specific PowerPoint, Excel dashboard, or chart.

Spec: `2026_DPID_PreCourseMeeting.pdf` (single-agent workflow, slides 5–7).
Implementation details: `MASTER.md`.

## Quick start

```bash
git clone https://github.com/SoerenM2345/PMI-Reporting-Agent.git
cd PMI-Reporting-Agent
pip install -r requirements.txt

# optional — enables real LLM summaries; without it a deterministic mock is used
cp .env.example .env   # then paste your OPENAI_API_KEY and export it

uvicorn app.main:app --reload
```

Open **http://localhost:8000**.

### Docker

```bash
docker build -t pmi-reporting-agent .
docker run -p 8000:8000 -e OPENAI_API_KEY=$OPENAI_API_KEY pmi-reporting-agent
```

## How to use it (as a PMI consultant)

1. **Drop your files** into the drag-and-drop zone — everything you collected
   over the week: Excel trackers, PowerPoint workstream updates, Word meeting
   notes, PDFs, HTML exports. (`.xlsx .pptx .docx .pdf .html`)
2. **Type your request**, e.g.
   - *"Create a SteerCo PowerPoint with tasks per owner"*
   - *"Create a Finance Excel dashboard"*
   - *"Create a chart about risks"*
3. **Audience** — pick Executive / PMO / Finance, or leave on auto-detect;
   the agent asks if it can't tell from the request.
4. **Conflicts** — when sources disagree (Excel says 82%, PowerPoint says 75%),
   the agent either auto-resolves by source priority
   (Excel > Word/PDF > PowerPoint > HTML) or, in "Ask me" mode, flags critical
   conflicts for your decision.
5. **Download** the generated report. Every conflict, resolution, and source
   file is listed in the output for auditability.

> **Guardrail:** outputs are drafts. Senior Manager review is required before
> anything reaches a stakeholder (hard requirement from interviews 2 & 4).

## Try it with sample data

```bash
python scripts/make_sample_data.py
```

creates `data/samples/` with a realistic tracker, weekly-update deck, and
meeting notes — including a deliberate 82%-vs-75% progress conflict so you can
see the consistency check fire.

## Run the tests

```bash
pytest -q
```

## API (if you'd rather script it)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/session` | new session → `{session_id}` |
| POST | `/api/upload?session_id=…` | multipart file upload |
| POST | `/api/report` | `{session_id, request_text, audience?, conflict_strategy}` → summary, conflicts, output files (or `needs_audience: true`) |
| GET | `/api/download/{session_id}/{filename}` | fetch a generated file |

## Repository layout

See `MASTER.md` for the full module map and design decisions.
`data/ectsum/` holds the ECTSum dataset (Mukherjee et al. 2022) for later
evaluation of the report-generation step — see `data/README.md`.
