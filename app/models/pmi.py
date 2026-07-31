"""The standardized PMI data model (spec §6).

This module is the import surface for the whole package: `from app.models.pmi
import ...` keeps working for every name it ever exposed. The entities themselves
live in `enums.py` / `source.py` / `entities.py` / `quality.py` — 14 spec entities
in one file was unreadable.

Aliases at the bottom map the original v1 names (`TaskItem`, `SourceRef`) onto the
spec's names (`Task`, `SourceReference`), which the codebase now uses.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.models.entities import (
    BudgetItem,
    Decision,
    Dependency,
    GovernanceMeeting,
    Issue,
    KPI,
    Milestone,
    PMIProject,
    Risk,
    StatusUpdate,
    Synergy,
    Task,
    Workstream,
)
from app.models.enums import (
    SEVERITY_ALIASES,
    SEVERITY_SCALE,
    SOURCE_PRIORITY,
    STATUS_ALIASES,
    WORKSTREAM_ALIASES,
    Audience,
    BudgetCategory,
    DecisionBody,
    ExtractionMethod,
    ImageContentType,
    IntegrationPhase,
    IntegrationType,
    MeetingType,
    RiskCategory,
    Severity,
    SourceFormat,
    Status,
    SynergyType,
    Trend,
    normalize_workstream,
    source_priority,
)
from app.models.quality import (
    Conflict,
    ConflictEvidence,
    DataQualityReport,
    ScoreComponent,
    ValidationIssue,
)
from app.models.source import ImageRegion, SourceReference


class PMIDataModel(BaseModel):
    """Everything extracted from one PMI project's files, standardized (§6)."""

    project: PMIProject = Field(
        default_factory=lambda: PMIProject(project_id="p_default")
    )

    # §6.2 - 6.13
    workstreams: list[Workstream] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    budget: list[BudgetItem] = Field(default_factory=list)
    synergies: list[Synergy] = Field(default_factory=list)
    kpis: list[KPI] = Field(default_factory=list)
    meetings: list[GovernanceMeeting] = Field(default_factory=list)
    status_updates: list[StatusUpdate] = Field(default_factory=list)

    # §8 findings. `issues` above is the PMI entity (§6.6); these are check results.
    conflicts: list[Conflict] = Field(default_factory=list)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)

    source_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    #: Rows/values we could not parse. Surfaced, never swallowed (§21.17).
    warnings: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------- convenience
    @property
    def project_name(self) -> str:
        """Something safe to print. Never a name the project does not have.

        The header defaults to empty rather than to "PMI Project" so that a
        caller resolving a *real* name (`context.builder.resolve_document_name`)
        can tell "unknown" from "known". Display sites want a string, and this
        is the one place that decides what an unknown one looks like.
        """
        return self.project.project_name or "(unnamed project)"

    def overall_progress(self) -> Optional[float]:
        """Mean task progress. Returns None rather than 0 when nothing is known —
        a project with no progress data is not a project at 0% (§7)."""
        values = [t.progress_percentage for t in self.tasks
                  if t.progress_percentage is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    def tasks_by_owner(self) -> dict[str, list[Task]]:
        out: dict[str, list[Task]] = {}
        for task in self.tasks:
            out.setdefault(task.owner or "Unassigned", []).append(task)
        return out

    def open_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.status.is_open]

    def overdue_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.is_overdue]

    def critical_risks(self) -> list[Risk]:
        return [r for r in self.risks
                if r.rating in (Severity.HIGH, Severity.CRITICAL)]

    def unresolved_conflicts(self) -> list[Conflict]:
        return [c for c in self.conflicts if not c.is_resolved]

    def low_confidence_items(self) -> list[tuple[str, str, float]]:
        """(entity_type, label, confidence) for everything a human should check —
        §5.6's "low-confidence findings shown to the user for review".

        Includes anything read from an image or by OCR, even at a high score. A crisp
        screenshot read at 0.88 is not *low* confidence, but it is a transcription that
        nobody has confirmed against the source system — and §21.14 says image
        extraction is lower confidence "unless confirmed". The user is the only one who
        can confirm it.
        """
        out: list[tuple[str, str, float]] = []
        collections: list[tuple[str, list, str]] = [
            ("task", self.tasks, "title"),
            ("milestone", self.milestones, "name"),
            ("risk", self.risks, "title"),
            ("issue", self.issues, "title"),
            ("dependency", self.dependencies, "description"),
            ("decision", self.decisions, "title"),
            ("budget", self.budget, "category"),
            ("synergy", self.synergies, "title"),
            ("kpi", self.kpis, "name"),
        ]
        for kind, items, label_attr in collections:
            for item in items:
                if item.needs_review:
                    out.append((kind, getattr(item, label_attr, "?"), item.confidence))
        return out

    def entity_count(self) -> int:
        return sum(
            len(x) for x in (
                self.workstreams, self.tasks, self.milestones, self.risks,
                self.issues, self.dependencies, self.decisions, self.budget,
                self.synergies, self.kpis, self.meetings, self.status_updates,
            )
        )


# --------------------------------------------------------------------- aliases
#: v1 names, kept so nothing that imported them breaks. New code should use the
#: spec names on the right.
TaskItem = Task
SourceRef = SourceReference

__all__ = [
    # container
    "PMIDataModel", "PMIProject",
    # entities (§6)
    "Workstream", "Task", "Milestone", "Risk", "Issue", "Dependency", "Decision",
    "BudgetItem", "Synergy", "KPI", "GovernanceMeeting", "StatusUpdate",
    # provenance (§6.14)
    "SourceReference", "ImageRegion",
    # quality (§8, §9)
    "Conflict", "ConflictEvidence", "ValidationIssue", "DataQualityReport",
    "ScoreComponent",
    # enums (§7)
    "SourceFormat", "Status", "Severity", "Audience", "Trend", "RiskCategory",
    "SynergyType", "BudgetCategory", "DecisionBody", "MeetingType",
    "IntegrationType", "IntegrationPhase", "ImageContentType", "ExtractionMethod",
    "SOURCE_PRIORITY", "source_priority", "STATUS_ALIASES", "SEVERITY_ALIASES",
    "SEVERITY_SCALE", "WORKSTREAM_ALIASES", "normalize_workstream",
    # v1 aliases
    "TaskItem", "SourceRef",
]
