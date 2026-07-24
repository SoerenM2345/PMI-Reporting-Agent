"""Every figure the report is entitled to state, computed once.

§11: the model is never the authority for a calculation. Everything here is
plain Python over `PMIDataModel` and `app/agent/calculations.py`, and the result
is the *only* source a renderer or a preview may quote a number from. Model-
authored prose is checked against `FactTable.numeric_corpus()` before it is
accepted (`guard.py`), so an invented figure has nowhere to hide.

§7 is enforced at the same point: a figure we do not have is `value=None` and
displays as "Not Reported". It is never zero. Note the sums below deliberately
treat a total of 0 as missing — they are sums over optional fields, so a zero
means "nobody reported a budget", not "the budget is nil".
"""
from __future__ import annotations

from typing import Optional

from app.models.pmi import DataQualityReport, PMIDataModel, Status
from app.report import format as fmt
from app.report.content import Fact, FactRef, FactTable


def build_facts(
    model: PMIDataModel,
    quality: Optional[DataQualityReport] = None,
) -> FactTable:
    """The report's numeric backbone. Pure — no I/O, no LLM, no side effects."""
    table = FactTable()

    _status_facts(table, model)
    _progress_facts(table, model)
    _risk_and_issue_facts(table, model)
    _finance_facts(table, model)
    _governance_facts(table, model)
    _quality_facts(table, model, quality)

    return table


# --------------------------------------------------------------------- status
def _status_facts(table: FactTable, model: PMIDataModel) -> None:
    """The single line a Steering Committee reads first.

    Unresolved conflicts outrank everything: if two of our own sources disagree
    about the status, we do not have a status to report, and saying "On Track"
    would launder a disagreement into a fact.
    """
    unresolved = model.unresolved_conflicts()
    open_critical = [r for r in model.critical_risks() if r.status.is_open]

    if unresolved:
        status = "Not agreed — unresolved source conflicts"
    elif open_critical:
        status = "At Risk"
    elif model.overdue_tasks():
        status = "At Risk — overdue activities"
    elif model.tasks:
        status = "On Track"
    else:
        status = fmt.NOT_REPORTED

    table.add(Fact(
        key="status.overall",
        label="Overall PMI status",
        value=None if status == fmt.NOT_REPORTED else status,
        display=status,
        refs=[FactRef(entity_type="derived", is_derived=True)],
    ))


# ------------------------------------------------------------------- progress
def _progress_facts(table: FactTable, model: PMIDataModel) -> None:
    progress = model.overall_progress()
    table.add(Fact(
        key="progress.overall",
        label="Overall progress",
        value=progress,
        # A project with no progress data is not a project at 0% (§7).
        display=f"{progress:.0f}%" if progress is not None else fmt.NOT_REPORTED,
        refs=[FactRef(entity_type="derived", field="progress_percentage",
                      is_derived=True)],
    ))

    day_1 = [t for t in model.tasks if t.is_day_1_critical]
    done = sum(1 for t in day_1 if t.status is Status.COMPLETED)
    table.add(Fact(
        key="day1.readiness",
        label="Day 1 readiness",
        value=done if day_1 else None,
        display=f"{done}/{len(day_1)}" if day_1 else fmt.NOT_REPORTED,
        refs=[FactRef(entity_type="task", field="is_day_1_critical",
                      is_derived=True)],
    ))
    table.add(Fact(
        key="day1.total",
        label="Day 1 critical tasks",
        value=len(day_1) if day_1 else None,
        display=str(len(day_1)) if day_1 else fmt.NOT_REPORTED,
    ))

    _count(table, "tasks.overdue", "Overdue tasks", len(model.overdue_tasks()), "task")
    _count(table, "tasks.open", "Open tasks", len(model.open_tasks()), "task")
    _count(table, "tasks.total", "Tasks", len(model.tasks), "task")
    _count(table, "tasks.blocked", "Blocked tasks",
           sum(1 for t in model.tasks if t.status is Status.BLOCKED), "task")
    _count(table, "milestones.overdue", "Overdue milestones",
           sum(1 for m in model.milestones if (m.delay_days or 0) > 0), "milestone")


# ------------------------------------------------------------ risks & issues
def _risk_and_issue_facts(table: FactTable, model: PMIDataModel) -> None:
    open_critical = [r for r in model.critical_risks() if r.status.is_open]
    unmitigated = [r for r in open_critical if not r.mitigation_action]

    _count(table, "risk.open_critical", "Open critical risks",
           len(open_critical), "risk", refs=_refs_for(open_critical, "risk"))
    _count(table, "risk.unmitigated_critical",
           "Critical risks with no mitigation", len(unmitigated), "risk",
           refs=_refs_for(unmitigated, "risk"))
    _count(table, "issue.open", "Open issues",
           sum(1 for i in model.issues if i.status.is_open), "issue")


# ------------------------------------------------------------------- finance
def _finance_facts(table: FactTable, model: PMIDataModel) -> None:
    budget = sum(b.budget or 0 for b in model.budget)
    actual = sum(b.actual or 0 for b in model.budget)
    forecast = sum(b.forecast or 0 for b in model.budget)
    target = sum(s.target_value or 0 for s in model.synergies)
    realized = sum(s.realized_value or 0 for s in model.synergies)

    # These are sums over optional fields: 0 means nobody reported one.
    _money(table, "budget.total", "Budget", budget, model, "budget")
    _money(table, "budget.actual", "Actual", actual, model, "budget")
    _money(table, "budget.forecast", "Forecast", forecast, model, "budget")
    _money(table, "synergy.target", "Synergy target", target, model, "synergy")
    _money(table, "synergy.realized", "Synergy realized", realized, model, "synergy")

    variance = budget - forecast if budget and forecast else None
    table.add(Fact(
        key="budget.variance",
        label="Budget variance",
        value=variance,
        display=fmt.num(variance) if variance is not None else fmt.NOT_REPORTED,
        refs=[FactRef(entity_type="budget", field="variance", is_derived=True)],
    ))

    realization = (realized / target * 100) if target else None
    table.add(Fact(
        key="synergy.realization_pct",
        label="Synergy realization",
        value=realization,
        display=(f"{realization:.0f}%" if realization is not None
                 else fmt.NOT_REPORTED),
        refs=[FactRef(entity_type="synergy", field="realized_value",
                      is_derived=True)],
    ))


# ---------------------------------------------------------------- governance
def _governance_facts(table: FactTable, model: PMIDataModel) -> None:
    _count(table, "decision.open", "Decisions required",
           sum(1 for d in model.decisions if d.status.is_open), "decision")
    _count(table, "workstream.total", "Workstreams",
           len(model.workstreams), "workstream")
    _count(table, "workstream.silent", "Workstreams not reporting",
           sum(1 for w in model.workstreams if w.progress_percentage is None),
           "workstream")


# ------------------------------------------------------------- data quality
def _quality_facts(
    table: FactTable, model: PMIDataModel, quality: Optional[DataQualityReport]
) -> None:
    """The figures that say how much to trust every other figure."""
    unresolved = model.unresolved_conflicts()
    _count(table, "conflict.unresolved", "Unresolved source conflicts",
           len(unresolved), "conflict")
    _count(table, "conflict.critical_unresolved",
           "Unresolved critical conflicts",
           sum(1 for c in unresolved if c.critical), "conflict")
    _count(table, "quality.low_confidence_items",
           "Findings needing review", len(model.low_confidence_items()), "derived")

    score = getattr(quality, "score", None) if quality else None
    table.add(Fact(
        key="quality.score",
        label="Data quality score",
        value=score,
        display=f"{score:.0f}" if score is not None else fmt.NOT_REPORTED,
        refs=[FactRef(entity_type="derived", is_derived=True)],
    ))


# ------------------------------------------------------------------- helpers
def _count(
    table: FactTable,
    key: str,
    label: str,
    value: int,
    entity_type: str,
    refs: Optional[list[FactRef]] = None,
) -> None:
    """A count of zero is a real answer — "no open critical risks" is a finding,
    not an absence — so counts are never rendered as "Not Reported"."""
    table.add(Fact(
        key=key, label=label, value=value, display=str(value),
        refs=refs or [FactRef(entity_type=entity_type, is_derived=True)],
    ))


def _money(
    table: FactTable,
    key: str,
    label: str,
    total: float,
    model: PMIDataModel,
    entity_type: str,
) -> None:
    present = bool(total)
    table.add(Fact(
        key=key,
        label=label,
        value=total if present else None,
        display=fmt.num(total) if present else fmt.NOT_REPORTED,
        refs=_refs_for(
            model.budget if entity_type == "budget" else model.synergies,
            entity_type,
        ),
    ))


def _refs_for(items, entity_type: str, limit: int = 5) -> list[FactRef]:
    """Provenance for a figure aggregated over several entities.

    Capped: a variance summed over 40 budget lines does not need 40 citations,
    and a slide footnote cannot carry them.
    """
    refs: list[FactRef] = []
    for item in items[:limit]:
        source = getattr(item, "primary_source", None)
        if source is None:
            continue
        refs.append(FactRef(
            entity_type=entity_type,
            file_name=source.file_name,
            location=source.location,
            confidence=source.extraction_confidence,
        ))
    return refs
