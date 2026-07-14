"""The standardized PMI entities (spec §6).

Field names follow the spec verbatim so the model can be diffed against §6 directly.

Two conventions run through every entity:

1. **`source_references` is a list, not a single ref.** The same task can appear in
   the masterplan *and* in a status deck; entity matching merges them into one
   object carrying both refs. That is what makes cross-source conflict detection
   possible at all.

2. **Missing means missing.** §7: "The agent must never silently invent missing PMI
   information." An unknown probability is `None`, not a guess — and a `risk_score`
   that therefore cannot be computed is `None` too, with a completeness issue raised
   against it. Nothing here defaults a number into existence.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import (
    BudgetCategory,
    DecisionBody,
    IntegrationPhase,
    IntegrationType,
    MeetingType,
    RiskCategory,
    Severity,
    Status,
    SynergyType,
    Trend,
)
from app.models.source import SourceReference

#: Scale bands for `risk_score = probability x impact` on a 5x5 matrix.
#: The spec gives the formula (§6.5) but not the scales; documented in
#: docs/pmi_data_model.md.
_RISK_BANDS: tuple[tuple[int, Severity], ...] = (
    (4, Severity.LOW),
    (9, Severity.MEDIUM),
    (15, Severity.HIGH),
)

#: Used when a register gives one rating column instead of probability x impact.
_IMPACT_BANDS: dict[int, Severity] = {
    1: Severity.LOW,
    2: Severity.LOW,
    3: Severity.MEDIUM,
    4: Severity.HIGH,
    5: Severity.CRITICAL,
}


class _Sourced(BaseModel):
    """Mixin: everything extracted carries its provenance."""

    source_references: list[SourceReference] = Field(default_factory=list)

    @property
    def primary_source(self) -> Optional[SourceReference]:
        return self.source_references[0] if self.source_references else None

    @property
    def confidence(self) -> float:
        """Best confidence across the sources that agree on this entity. An entity
        corroborated by a tracker is trustworthy even if a screenshot also mentioned it."""
        if not self.source_references:
            return 0.0
        return max(r.extraction_confidence for r in self.source_references)

    @property
    def is_low_confidence(self) -> bool:
        from app.config import get_settings

        return self.confidence < get_settings().low_confidence_threshold

    @property
    def needs_review(self) -> bool:
        """True when NO source for this entity is a direct, deterministic read.

        An entity corroborated by a tracker does not need reviewing just because a
        screenshot also mentioned it — the tracker settles it. It is the entity that
        exists *only* in a picture that a human has to confirm.
        """
        if not self.source_references:
            return False
        return all(ref.needs_review for ref in self.source_references)

    @property
    def source_files(self) -> list[str]:
        seen: list[str] = []
        for ref in self.source_references:
            if ref.file_name not in seen:
                seen.append(ref.file_name)
        return seen


# --------------------------------------------------------------- §6.2 Workstream
class Workstream(_Sourced):
    workstream_id: str
    name: str
    lead: Optional[str] = None
    sponsor: Optional[str] = None
    status: Status = Status.UNKNOWN
    progress_percentage: Optional[float] = Field(default=None, ge=0, le=100)
    summary: Optional[str] = None
    achievements: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    open_risks: list[str] = Field(default_factory=list)
    open_issues: list[str] = Field(default_factory=list)
    upcoming_milestones: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------- §6.3 Task
class Task(_Sourced):
    task_id: str
    title: str
    description: Optional[str] = None
    workstream: Optional[str] = None
    owner: Optional[str] = None
    supporting_owner: Optional[str] = None
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    completion_date: Optional[date] = None
    status: Status = Status.UNKNOWN
    progress_percentage: Optional[float] = Field(default=None, ge=0, le=100)
    priority: Optional[str] = None
    dependency_ids: list[str] = Field(default_factory=list)
    is_day_1_critical: bool = False
    #: Derived in calculations.py against the reporting date — never trusted from a source.
    is_overdue: bool = False
    escalation_required: bool = False


# ---------------------------------------------------------------- §6.4 Milestone
class Milestone(_Sourced):
    milestone_id: str
    name: str
    description: Optional[str] = None
    workstream: Optional[str] = None
    owner: Optional[str] = None
    planned_date: Optional[date] = None
    forecast_date: Optional[date] = None
    actual_date: Optional[date] = None
    status: Status = Status.UNKNOWN
    #: Derived: forecast/actual minus planned. Positive = late.
    delay_days: Optional[int] = None
    is_day_1_critical: bool = False
    is_go_live: bool = False
    dependency_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------- §6.5 Risk
class Risk(_Sourced):
    risk_id: str
    title: str
    description: Optional[str] = None
    category: RiskCategory = RiskCategory.UNKNOWN
    workstream: Optional[str] = None
    owner: Optional[str] = None
    #: 1-5. None when the source did not state it — we do not infer the missing
    #: factor of a product (§7).
    probability: Optional[int] = Field(default=None, ge=1, le=5)
    impact: Optional[int] = Field(default=None, ge=1, le=5)
    #: probability x impact, computed in calculations.py (§11: never the LLM).
    risk_score: Optional[int] = Field(default=None, ge=1, le=25)
    status: Status = Status.UNKNOWN
    mitigation_action: Optional[str] = None
    mitigation_owner: Optional[str] = None
    mitigation_due_date: Optional[date] = None
    trend: Trend = Trend.UNKNOWN
    escalation_required: bool = False

    @property
    def rating(self) -> Severity:
        """Band the risk for display and RAG colouring.

        With both factors known, band the 1-25 product. With only impact known —
        the common case, since most registers carry a single "High/Medium/Low"
        column — report that impact band as-is rather than multiplying in an
        invented likelihood. A "Critical" row must not render as "High" because we
        guessed a median probability for it.
        """
        if self.risk_score is not None:
            for ceiling, band in _RISK_BANDS:
                if self.risk_score <= ceiling:
                    return band
            return Severity.CRITICAL

        if self.impact is not None:
            return _IMPACT_BANDS.get(self.impact, Severity.MEDIUM)

        return Severity.MEDIUM

    @property
    def is_fully_scored(self) -> bool:
        return self.probability is not None and self.impact is not None


# -------------------------------------------------------------------- §6.6 Issue
class Issue(_Sourced):
    issue_id: str
    title: str
    description: Optional[str] = None
    workstream: Optional[str] = None
    owner: Optional[str] = None
    severity: Severity = Severity.MEDIUM
    status: Status = Status.UNKNOWN
    resolution_action: Optional[str] = None
    resolution_owner: Optional[str] = None
    due_date: Optional[date] = None
    escalation_required: bool = False


# --------------------------------------------------------------- §6.7 Dependency
class Dependency(_Sourced):
    dependency_id: str
    description: str
    providing_workstream: Optional[str] = None
    receiving_workstream: Optional[str] = None
    owner: Optional[str] = None
    required_date: Optional[date] = None
    status: Status = Status.UNKNOWN
    impact_if_delayed: Optional[str] = None
    related_task_ids: list[str] = Field(default_factory=list)
    related_milestone_ids: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------- §6.8 Decision
class Decision(_Sourced):
    decision_id: str
    title: str
    description: Optional[str] = None
    decision_body: DecisionBody = DecisionBody.UNKNOWN
    decision_owner: Optional[str] = None
    decision_deadline: Optional[date] = None
    status: Status = Status.UNKNOWN
    options: list[str] = Field(default_factory=list)
    recommended_option: Optional[str] = None
    impact: Optional[str] = None
    escalation_level: Optional[str] = None


# -------------------------------------------------------------- §6.9 Budget Item
class BudgetItem(_Sourced):
    budget_item_id: str
    category: str
    standard_category: BudgetCategory = BudgetCategory.OTHER
    workstream: Optional[str] = None
    budget: Optional[float] = None
    actual: Optional[float] = None
    committed: Optional[float] = None
    forecast: Optional[float] = None
    #: Derived: budget - forecast (calculations.py). A source-reported variance that
    #: disagrees is flagged, and ours wins (§11).
    variance: Optional[float] = None
    variance_percentage: Optional[float] = None
    currency: str = "EUR"
    reporting_period: Optional[str] = None


# ------------------------------------------------------------------ §6.10 Synergy
class Synergy(_Sourced):
    synergy_id: str
    title: str
    description: Optional[str] = None
    synergy_type: SynergyType = SynergyType.UNKNOWN
    workstream: Optional[str] = None
    owner: Optional[str] = None
    baseline: Optional[float] = None
    target_value: Optional[float] = None
    realized_value: Optional[float] = None
    forecast_value: Optional[float] = None
    #: Derived: target - realized.
    remaining_value: Optional[float] = None
    currency: str = "EUR"
    planned_realization_date: Optional[date] = None
    status: Status = Status.UNKNOWN
    confidence_level: Optional[str] = None


# ---------------------------------------------------------------------- §6.11 KPI
class KPI(_Sourced):
    kpi_id: str
    name: str
    description: Optional[str] = None
    workstream: Optional[str] = None
    current_value: Optional[float] = None
    target_value: Optional[float] = None
    previous_value: Optional[float] = None
    unit: Optional[str] = None
    status: Status = Status.UNKNOWN
    trend: Trend = Trend.UNKNOWN
    reporting_date: Optional[date] = None


# ------------------------------------------------------- §6.12 Governance Meeting
class GovernanceMeeting(_Sourced):
    meeting_id: str
    meeting_type: MeetingType = MeetingType.UNKNOWN
    meeting_date: Optional[date] = None
    participants: list[str] = Field(default_factory=list)
    agenda: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_meeting_date: Optional[date] = None


# ------------------------------------------------------------ §6.13 Status Update
class StatusUpdate(_Sourced):
    status_update_id: str
    reporting_period: Optional[str] = None
    workstream: Optional[str] = None
    overall_status: Status = Status.UNKNOWN
    progress_percentage: Optional[float] = Field(default=None, ge=0, le=100)
    achievements: list[str] = Field(default_factory=list)
    planned_activities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    decisions_required: list[str] = Field(default_factory=list)
    comments: Optional[str] = None


# ---------------------------------------------------------------- §6.1 PMI Project
class PMIProject(BaseModel):
    """Project header (§6.1).

    Most of this cannot be extracted — a masterplan does not state its own signing
    date. It comes from the user at upload time (§4 step 1). If a file contradicts
    what the user told us, that is a conflict, not a correction: we never let the
    model overwrite a user-stated closing date with one it thinks it read.
    """

    project_id: str
    project_name: str = "PMI Project"
    deal_name: Optional[str] = None
    acquirer_name: Optional[str] = None
    target_name: Optional[str] = None

    reporting_date: Optional[date] = None
    reporting_period: Optional[str] = None
    signing_date: Optional[date] = None
    closing_date: Optional[date] = None
    day_1_date: Optional[date] = None
    integration_start_date: Optional[date] = None
    integration_end_date: Optional[date] = None

    integration_phase: IntegrationPhase = IntegrationPhase.UNKNOWN
    integration_type: IntegrationType = IntegrationType.UNKNOWN
    overall_status: Status = Status.UNKNOWN
    overall_progress_percentage: Optional[float] = Field(default=None, ge=0, le=100)
    target_audience: Optional[str] = None
    source_files: list[str] = Field(default_factory=list)
