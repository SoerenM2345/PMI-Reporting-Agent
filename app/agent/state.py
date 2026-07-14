"""LangGraph state for the 7-step workflow."""
from __future__ import annotations

from typing import Optional, TypedDict

from typing import Any

from app.models.pmi import Audience, DataQualityReport, PMIDataModel, PMIProject


class AgentState(TypedDict, total=False):
    # step 1 — inputs
    session_id: str
    file_paths: list[str]
    request_text: str
    #: What the user told us that no file contains (§4 step 1): reporting date,
    #: Day 1 date, phase. Without these, whole check families cannot run.
    project: Optional[PMIProject]
    #: "ask" (Mode A) | "priority" (Mode B) | "hybrid" (Mode C, the default)
    conflict_strategy: Optional[str]
    #: conflict_id -> a file name, or {"value": "..."} to state the truth (§9)
    user_conflict_choices: dict[str, Any]
    # step 2
    audience: Optional[Audience]
    needs_audience: bool
    output_type: str  # powerpoint | excel | chart
    topic: str
    # steps 3-4
    raw_records: list[dict]
    data_model: Optional[PMIDataModel]
    # steps 5-6
    quality_report: Optional[DataQualityReport]
    # step 7
    summary_bullets: list[str]
    output_files: list[str]
    #: Hard failures — a file that could not be read at all.
    errors: list[str]
    #: Soft caveats the user must see: an LLM call that fell back to a heuristic,
    #: a low-confidence image reading, a row that could not be parsed. These feed
    #: the data-quality report (§21.17) rather than being swallowed.
    warnings: list[str]
