"""LLM layer: OpenAI when OPENAI_API_KEY is set, deterministic mock otherwise.

The PDF spec names OpenAI GPT-5.5 (API). Mock mode exists so the whole pipeline is
testable with zero cost/keys; the switch is automatic via environment.
LLM duties: (a) parse the user request -> output type + audience,
(b) write the executive summary text for the generated report.
Everything numeric comes from the standardized data model, never from the LLM.
"""
from __future__ import annotations

import json
import os

from app.models.pmi import Audience, PMIDataModel

MODEL_NAME = os.environ.get("OPENAI_MODEL", "gpt-5.5")

OUTPUT_TYPES = ("powerpoint", "excel", "chart")

_REQUEST_HINTS = {
    "powerpoint": ["powerpoint", "pptx", "slide", "deck", "presentation", "steerco",
                   "steering", "präsentation"],
    "excel": ["excel", "xlsx", "dashboard", "spreadsheet", "sheet", "tabelle"],
    "chart": ["chart", "graph", "plot", "diagramm", "figure", "visual"],
}
_AUDIENCE_HINTS = {
    Audience.EXECUTIVE: ["executive", "steerco", "steering", "c-level", "board",
                         "management", "leadership", "geschäftsführung"],
    Audience.FINANCE: ["finance", "financial", "budget", "cost", "cfo", "finanz"],
    Audience.PMO: ["pmo", "project office", "workstream", "detailed", "team",
                   "operational", "imo"],
}


def llm_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def parse_request(request_text: str) -> dict:
    """-> {"output_type": ..., "audience": Audience|None, "topic": str}"""
    if llm_available():
        try:
            return _openai_parse(request_text)
        except Exception:
            pass  # fall back to heuristics — never block the pipeline
    return _heuristic_parse(request_text)


def write_summary(model: PMIDataModel, audience: Audience, request_text: str) -> list[str]:
    """Executive-summary bullets for the report."""
    if llm_available():
        try:
            return _openai_summary(model, audience, request_text)
        except Exception:
            pass
    return _mock_summary(model, audience)


# ------------------------------------------------------------------ heuristic / mock
def _heuristic_parse(request_text: str) -> dict:
    import re

    t = request_text.lower()

    def has_kw(kws: list[str]) -> bool:
        # word-boundary match so e.g. "board" doesn't fire inside "dashboard"
        return any(re.search(rf"\b{re.escape(k)}\b", t) for k in kws)

    output_type = next((ot for ot, kws in _REQUEST_HINTS.items() if has_kw(kws)),
                       "powerpoint")
    audience = next((a for a, kws in _AUDIENCE_HINTS.items() if has_kw(kws)), None)
    topic = "risks" if "risk" in t or "risiko" in t else "status"
    return {"output_type": output_type, "audience": audience, "topic": topic}


def _mock_summary(model: PMIDataModel, audience: Audience) -> list[str]:
    bullets: list[str] = []
    prog = model.overall_progress()
    kpi_prog = next((k.value for k in model.kpis
                     if "progress" in k.name.lower() and k.value is not None), None)
    shown = kpi_prog if kpi_prog is not None else prog
    if shown is not None:
        bullets.append(f"Overall integration progress stands at {shown:.0f}% "
                       f"across {len(model.source_files)} reporting source(s).")
    open_tasks = [t for t in model.tasks if t.status.value not in ("done",)]
    if model.tasks:
        bullets.append(f"{len(model.tasks)} tracked tasks, {len(open_tasks)} open; "
                       f"{len(model.tasks_by_owner())} owner(s) carry assignments.")
    high = [r for r in model.risks if r.severity.value in ("high", "critical")]
    if model.risks:
        bullets.append(f"{len(model.risks)} risks logged, {len(high)} rated high or "
                       f"critical — mitigation owners are assigned in the risk log.")
    if model.conflicts:
        unresolved = [c for c in model.conflicts if c.resolved_value is None]
        bullets.append(f"{len(model.conflicts)} cross-source inconsistencies detected; "
                       f"{len(model.conflicts) - len(unresolved)} auto-resolved by source "
                       f"priority, {len(unresolved)} awaiting user decision.")
    if audience == Audience.FINANCE and model.budget:
        planned = sum(b.planned or 0 for b in model.budget)
        actual = sum(b.actual or 0 for b in model.budget)
        bullets.append(f"Budget: {actual:,.0f} EUR spent against {planned:,.0f} EUR "
                       f"planned ({(actual / planned * 100) if planned else 0:.0f}% consumed).")
    if not bullets:
        bullets.append("No structured PMI data found in the uploaded files.")
    return bullets


# ------------------------------------------------------------------ OpenAI
def _client():
    from openai import OpenAI
    return OpenAI()


def _openai_parse(request_text: str) -> dict:
    rsp = _client().chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content":
                "Classify a PMI reporting request. Reply with JSON only: "
                '{"output_type": "powerpoint"|"excel"|"chart", '
                '"audience": "Executive"|"PMO"|"Finance"|null, "topic": string}'},
            {"role": "user", "content": request_text},
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(rsp.choices[0].message.content)
    aud = data.get("audience")
    return {
        "output_type": data.get("output_type", "powerpoint"),
        "audience": Audience(aud) if aud in [a.value for a in Audience] else None,
        "topic": data.get("topic", "status"),
    }


def _openai_summary(model: PMIDataModel, audience: Audience, request_text: str) -> list[str]:
    payload = model.model_dump_json(exclude={"notes"})[:12000]
    rsp = _client().chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content":
                f"You write PMI status summaries for a {audience.value} audience. "
                "Use ONLY numbers present in the data. Reply with JSON: "
                '{"bullets": [string, ...]} — 3 to 6 crisp bullets.'},
            {"role": "user", "content": f"Request: {request_text}\n\nData: {payload}"},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(rsp.choices[0].message.content).get("bullets", [])
