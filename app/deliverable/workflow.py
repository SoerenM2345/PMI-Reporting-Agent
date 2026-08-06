"""Durable state for the report review-and-approval conversation."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel


ReviewFormat = Literal["powerpoint", "pdf", "word", "html", "chart"]

FORMAT_LABELS = {
    "powerpoint": "PowerPoint",
    "pdf": "PDF",
    "word": "Word",
    "html": "HTML",
    "chart": "chart",
}
FORMAT_ALIASES = {
    "powerpoint": "powerpoint", "pptx": "powerpoint", "ppt": "powerpoint",
    "deck": "powerpoint", "slides": "powerpoint", "presentation": "powerpoint",
    "pdf": "pdf",
    "word": "word", "docx": "word", "doc": "word", "document": "word",
    "html": "html", "web": "html", "webpage": "html", "web page": "html",
    "dashboard": "html",
    "chart": "chart", "charts": "chart", "graph": "chart", "graphs": "chart",
    "image": "chart", "picture": "chart", "plot": "chart", "png": "chart",
}
PLANNING_FORMAT = {
    "powerpoint": "pptx", "word": "docx", "pdf": "pdf",
    "html": "html", "chart": "chart",
}


class ReportWorkflow(BaseModel):
    selected_format: Optional[ReviewFormat] = None
    request_text: str = ""
    state: Literal[
        "idle", "awaiting_output_format", "awaiting_preview_revision",
        "awaiting_generation_approval", "approved", "generated",
    ] = "idle"
    version: Optional[int] = None


def normalize_format(value: Optional[str]) -> Optional[ReviewFormat]:
    raw = " ".join((value or "").strip().casefold().strip(" .?!").split())
    if raw in FORMAT_ALIASES:
        return FORMAT_ALIASES[raw]  # type: ignore[return-value]
    return None


def planning_format(value: str) -> str:
    normalized = normalize_format(value)
    return PLANNING_FORMAT.get(normalized or "", "")


def load(session_id: str) -> ReportWorkflow:
    path = _path(session_id)
    if not path.is_file():
        return ReportWorkflow()
    try:
        return ReportWorkflow.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ReportWorkflow()


def save(session_id: str, state: ReportWorkflow) -> ReportWorkflow:
    path = _path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return state


def update(session_id: str, **changes) -> ReportWorkflow:
    state = load(session_id).model_copy(update=changes)
    return save(session_id, state)


def _path(session_id: str) -> Path:
    from app.storage import json_store

    return json_store.session_dir(session_id) / "report_workflow.json"
