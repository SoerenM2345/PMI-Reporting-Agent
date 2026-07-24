"""§8.1 — cross-source consistency checks.

"The agent compares overlapping information across all uploaded sources." Each check
here finds the same fact reported two different ways by two different files.

All of them are built on `_disagreement()`, which walks matched entity groups and
collects one claim per file. The interesting part is not the loop — it is that a
claim carries its full `SourceReference`, so a conflict card can tell the user the
82% is in `Integration_Masterplan.xlsx`, sheet 'Workplan', cell A7, and the 75% is on
slide 4 of the SteerCo deck. "Two files disagree" is not actionable; that is.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app.agent.consistency.registry import CheckContext, conflict_check
from app.agent.consistency.severity import critical_topic, escalate
from app.agent.matching import EntityGroup
from app.models.pmi import Conflict, ConflictEvidence, Severity

XS = "cross_source"


# ------------------------------------------------------------------- machinery
def _disagreement(
    group: EntityGroup,
    attribute: str,
    *,
    check_id: str,
    field_label: str,
    base: Severity,
    entity_type: Optional[str] = None,
    is_critical: bool = False,
) -> Optional[Conflict]:
    """One claim per file; a conflict only if at least two files claim *different* things."""
    claims: dict[str, ConflictEvidence] = {}

    for entity, value in group.values_of(attribute):
        ref = entity.primary_source
        if ref is None or ref.file_name in claims:
            continue
        claims[ref.file_name] = ConflictEvidence(
            source_reference=ref,
            value=_format(value),
            entity_id=_id_of(entity),
        )

    evidence = list(claims.values())
    if len(evidence) < 2 or len({e.value for e in evidence}) < 2:
        return None

    severity = escalate(group.label, evidence, base, is_critical_entity=is_critical)
    topic = critical_topic(group.label)
    reason = f" This is a {topic} conflict (§9)." if topic else ""

    claim_text = "; ".join(
        f"{e.source_reference.cite()} says {e.value}" for e in evidence
    )

    return Conflict(
        check_id=check_id,
        family=XS,
        entity_type=entity_type or group.entity_type,
        entity_key=group.label,
        field=attribute,
        evidence=evidence,
        severity=severity,
        message=(
            f"Sources disagree on the {field_label} of '{group.label}': "
            f"{claim_text}.{reason}"
        ),
    )


def _scan(
    groups,
    attribute: str,
    *,
    check_id: str,
    field_label: str,
    base: Severity,
    critical_when: Optional[Callable[[EntityGroup], bool]] = None,
) -> list[Conflict]:
    out: list[Conflict] = []
    for group in groups:
        if not group.is_cross_source:
            continue
        conflict = _disagreement(
            group, attribute,
            check_id=check_id, field_label=field_label, base=base,
            is_critical=bool(critical_when and critical_when(group)),
        )
        if conflict is not None:
            out.append(conflict)
    return out


def _format(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _id_of(entity: Any) -> Optional[str]:
    for attr in ("task_id", "milestone_id", "risk_id", "issue_id", "kpi_id",
                 "budget_item_id", "synergy_id", "dependency_id", "decision_id",
                 "workstream_id"):
        value = getattr(entity, attr, None)
        if value:
            return value
    return None


# ------------------------------------------------------------------ the checks
@conflict_check("PMI-001", XS, "Overall project status conflict", Severity.HIGH)
def overall_status(ctx: CheckContext) -> list[Conflict]:
    """Excel says Green, the SteerCo deck says Amber."""
    return _scan(ctx.groups.workstreams, "status",
                 check_id="PMI-001", field_label="overall status",
                 base=Severity.HIGH)


@conflict_check("PMI-002", XS, "Overall progress conflict", Severity.MEDIUM)
def overall_progress(ctx: CheckContext) -> list[Conflict]:
    """The spec's worked example: tracker 82%, SteerCo deck 75% (§8, §20).

    Severity is escalated to CRITICAL by the *topic* rule, not the magnitude — a 9%
    delta would otherwise auto-resolve and never reach the user.
    """
    return _scan(ctx.groups.kpis, "current_value",
                 check_id="PMI-002", field_label="value",
                 base=Severity.MEDIUM)


@conflict_check("PMI-003", XS, "Workstream status conflict", Severity.MEDIUM)
def workstream_status(ctx: CheckContext) -> list[Conflict]:
    """IT tracker says On Track, the IT status slide says At Risk."""
    return _scan(ctx.groups.tasks, "status",
                 check_id="PMI-003", field_label="status",
                 base=Severity.MEDIUM)


@conflict_check("PMI-004", XS, "Task progress conflict", Severity.MEDIUM)
def task_progress(ctx: CheckContext) -> list[Conflict]:
    """Masterplan 80%, workstream update 60%."""
    return _scan(ctx.groups.tasks, "progress_percentage",
                 check_id="PMI-004", field_label="progress",
                 base=Severity.MEDIUM)


@conflict_check("PMI-005", XS, "Task owner conflict", Severity.MEDIUM)
def task_owner(ctx: CheckContext) -> list[Conflict]:
    """Masterplan assigns the Finance Lead, the minutes assign the PMO Lead.

    Worth catching even though it is "only" an owner: a task with two claimed owners
    usually has none in practice.
    """
    return _scan(ctx.groups.tasks, "owner",
                 check_id="PMI-005", field_label="owner",
                 base=Severity.MEDIUM)


@conflict_check("PMI-006", XS, "Milestone date conflict", Severity.HIGH)
def milestone_date(ctx: CheckContext) -> list[Conflict]:
    """ERP go-live: 15 September in the masterplan, 30 September in the deck.

    Escalates to CRITICAL via the go-live topic rule when the milestone is one.
    """
    return _scan(
        ctx.groups.milestones, "planned_date",
        check_id="PMI-006", field_label="planned date",
        base=Severity.HIGH,
        critical_when=lambda g: any(
            getattr(m, "is_go_live", False) or getattr(m, "is_day_1_critical", False)
            for m in g.members
        ),
    )


@conflict_check("PMI-007", XS, "Risk rating conflict", Severity.MEDIUM)
def risk_rating(ctx: CheckContext) -> list[Conflict]:
    """Risk register says High impact, the status report says Medium."""
    conflicts = _scan(
        ctx.groups.risks, "impact",
        check_id="PMI-007", field_label="impact",
        base=Severity.MEDIUM,
        # §9: "Critical risks" are on the critical list.
        critical_when=lambda g: any(
            getattr(r, "rating", None) is Severity.CRITICAL for r in g.members
        ),
    )
    conflicts += _scan(
        ctx.groups.risks, "probability",
        check_id="PMI-007", field_label="probability",
        base=Severity.MEDIUM,
        critical_when=lambda g: any(
            getattr(r, "rating", None) is Severity.CRITICAL for r in g.members
        ),
    )
    return conflicts


@conflict_check("PMI-008", XS, "Synergy value conflict", Severity.HIGH)
def synergy_value(ctx: CheckContext) -> list[Conflict]:
    """Synergy tracker EUR 8m realized, the Finance deck EUR 6.5m.

    Always critical — §9 puts synergy realization on the critical list, and it is the
    number the deal was justified with.
    """
    conflicts: list[Conflict] = []
    for attribute, label in (("realized_value", "realized value"),
                             ("target_value", "target value"),
                             ("forecast_value", "forecast value")):
        conflicts += _scan(ctx.groups.synergies, attribute,
                           check_id="PMI-008", field_label=label,
                           base=Severity.HIGH)
    return conflicts


@conflict_check("PMI-009", XS, "Budget figure conflict", Severity.HIGH)
def budget_figure(ctx: CheckContext) -> list[Conflict]:
    """Finance tracker EUR 3m forecast, SteerCo deck EUR 2.7m."""
    conflicts: list[Conflict] = []
    for attribute, label in (("budget", "budget"), ("actual", "actual"),
                             ("forecast", "forecast")):
        conflicts += _scan(ctx.groups.budget, attribute,
                           check_id="PMI-009", field_label=label,
                           base=Severity.HIGH)
    return conflicts


@conflict_check("PMI-010", XS, "Day 1 readiness conflict", Severity.HIGH)
def day_1_readiness(ctx: CheckContext) -> list[Conflict]:
    """Day 1 checklist 92%, the executive summary 85%.

    The topic rule makes any Day-1 disagreement critical: on Day 1 the company either
    can pay its people or it cannot, and a Steering Committee cannot be shown two
    numbers for that.
    """
    conflicts: list[Conflict] = []
    for group in ctx.groups.kpis:
        if not group.is_cross_source:
            continue
        if critical_topic(group.label) != "Day 1 readiness":
            continue
        conflict = _disagreement(
            group, "current_value",
            check_id="PMI-010", field_label="Day 1 readiness",
            base=Severity.HIGH, entity_type="kpi",
        )
        if conflict is not None:
            conflicts.append(conflict)
    return conflicts


@conflict_check("PMI-011", XS, "Dependency status conflict", Severity.HIGH)
def dependency_status(ctx: CheckContext) -> list[Conflict]:
    """HR marks a dependency delivered; IT says it is still outstanding.

    Both workstreams then plan on their own belief, and the integration discovers the
    truth at the worst possible moment.
    """
    return _scan(ctx.groups.dependencies, "status",
                 check_id="PMI-011", field_label="status",
                 base=Severity.HIGH)


@conflict_check("PMI-012", XS, "Reporting period conflict", Severity.MEDIUM)
def reporting_period(ctx: CheckContext) -> list[Conflict]:
    """One file reports June; another is labelled July but carries June's figures.

    Detected structurally: two sources reporting the same KPI under different periods.
    A stale deck restated as current is one of the most common ways a Steering
    Committee is misled, and nobody does it on purpose.
    """
    periods: dict[str, ConflictEvidence] = {}

    for update in ctx.model.status_updates:
        if not update.reporting_period:
            continue
        ref = update.primary_source
        if ref is None or ref.file_name in periods:
            continue
        periods[ref.file_name] = ConflictEvidence(
            source_reference=ref,
            value=update.reporting_period,
            entity_id=update.status_update_id,
        )

    evidence = list(periods.values())
    if len(evidence) < 2 or len({e.value for e in evidence}) < 2:
        return []

    claims = "; ".join(f"{e.file_name} covers {e.value}" for e in evidence)
    return [Conflict(
        check_id="PMI-012",
        family=XS,
        entity_type="status_update",
        entity_key="Reporting period",
        field="reporting_period",
        evidence=evidence,
        severity=Severity.MEDIUM,
        message=(
            f"The uploaded files cover different reporting periods: {claims}. "
            f"Figures from different periods must not be presented as one snapshot."
        ),
    )]
