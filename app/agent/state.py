"""LangGraph state for the 7-step workflow."""
from __future__ import annotations

from typing import Optional, TypedDict

from app.models.pmi import Audience, PMIDataModel


class AgentState(TypedDict, total=False):
    # step 1 — inputs
    session_id: str
    file_paths: list[str]
    request_text: str
    conflict_strategy: str  # "priority" (Option B) | "ask" (Option A)
    user_conflict_choices: dict[str, str]
    # step 2
    audience: Optional[Audience]
    needs_audience: bool
    output_type: str  # powerpoint | excel | chart
    topic: str
    # steps 3-4
    raw_records: list[dict]
    data_model: Optional[PMIDataModel]
    # step 7
    summary_bullets: list[str]
    output_files: list[str]
    errors: list[str]
