"""Standardized PMI data model (PDF spec, slide 5, step 4).

One schema for everything extracted from any input format:
tasks, milestones, risks, budget, KPIs, owners, dates, status.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceFormat(str, Enum):
    """Input formats, ordered by conflict-resolution priority (slide 5, step 6):
    Excel > Word/PDF > PowerPoint > HTML > Image."""

    EXCEL = "excel"
    WORD = "word"
    PDF = "pdf"
    POWERPOINT = "powerpoint"
    HTML = "html"
    IMAGE = "image"


#: Lower number = higher trust when resolving conflicts.
#: Images rank last: their content is inferred by OCR or a vision model rather than
#: read from structured markup, so an image never overrides a figure from any other
#: source. It can still surface a fact that exists nowhere else, which is its purpose.
SOURCE_PRIORITY: dict[SourceFormat, int] = {
    SourceFormat.EXCEL: 1,
    SourceFormat.WORD: 2,
    SourceFormat.PDF: 2,
    SourceFormat.POWERPOINT: 3,
    SourceFormat.HTML: 4,
    SourceFormat.IMAGE: 5,
}


class Status(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    OVERDUE = "overdue"
    AT_RISK = "at_risk"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Audience(str, Enum):
    EXECUTIVE = "Executive"
    PMO = "PMO"
    FINANCE = "Finance"


class SourceRef(BaseModel):
    """Where a record came from — kept on every item for traceability."""

    file_name: str
    file_format: SourceFormat
    location: Optional[str] = None  # sheet name, slide number, page, table index


class TaskItem(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[date] = None
    status: Status = Status.UNKNOWN
    progress_pct: Optional[float] = Field(default=None, ge=0, le=100)
    workstream: Optional[str] = None
    priority: Optional[str] = None
    source: SourceRef


class Milestone(BaseModel):
    id: str
    title: str
    due_date: Optional[date] = None
    status: Status = Status.UNKNOWN
    owner: Optional[str] = None
    workstream: Optional[str] = None
    source: SourceRef


class Risk(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    severity: Severity = Severity.MEDIUM
    likelihood: Optional[str] = None
    owner: Optional[str] = None
    mitigation: Optional[str] = None
    status: Status = Status.UNKNOWN
    workstream: Optional[str] = None
    source: SourceRef


class BudgetItem(BaseModel):
    id: str
    category: str
    planned: Optional[float] = None
    actual: Optional[float] = None
    currency: str = "EUR"
    workstream: Optional[str] = None
    source: SourceRef


class KPI(BaseModel):
    id: str
    name: str
    value: Optional[float] = None
    unit: Optional[str] = None
    target: Optional[float] = None
    workstream: Optional[str] = None
    source: SourceRef


class Conflict(BaseModel):
    """One detected inconsistency between sources (slide 5, step 5)."""

    entity_type: str  # "kpi", "task", "progress", ...
    entity_key: str  # what the conflicting values describe
    field: str
    values: dict[str, str]  # file_name -> value as string
    formats: dict[str, SourceFormat]  # file_name -> format
    critical: bool = False
    resolved_value: Optional[str] = None
    resolved_from: Optional[str] = None  # file the winning value came from
    resolution: Optional[str] = None  # "source_priority" | "user"


class PMIDataModel(BaseModel):
    """The single standardized model every extractor feeds into (step 4)."""

    project_name: str = "PMI Project"
    tasks: list[TaskItem] = []
    milestones: list[Milestone] = []
    risks: list[Risk] = []
    budget: list[BudgetItem] = []
    kpis: list[KPI] = []
    conflicts: list[Conflict] = []
    source_files: list[str] = []
    notes: list[str] = []  # free-text findings (e.g. from meeting notes)

    def overall_progress(self) -> Optional[float]:
        vals = [t.progress_pct for t in self.tasks if t.progress_pct is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 1)

    def tasks_by_owner(self) -> dict[str, list[TaskItem]]:
        out: dict[str, list[TaskItem]] = {}
        for t in self.tasks:
            out.setdefault(t.owner or "Unassigned", []).append(t)
        return out
