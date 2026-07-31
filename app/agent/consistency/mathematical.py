"""§8.2 — mathematical checks.

The arithmetic that *can* be corrected (risk scores, budget variances, synergy
remainders, overdue flags) is done in `app/agent/calculations.py`, which emits
MATH-002 through MATH-008 as it goes. This module holds the checks that detect
impossible or internally inconsistent values rather than recomputing them.

Everything here is deterministic Python. §11 is explicit that the LLM must not be
the final authority for mathematical calculations, and none of this asks it.
"""
from __future__ import annotations

from app.agent.consistency.registry import CheckContext, issue_check
from app.models.pmi import Severity, ValidationIssue

MATH = "mathematical"
_TOLERANCE = 0.01
#: Workstream progress that disagrees with its own tasks by more than this is a
#: reporting error, not rounding.
_PROGRESS_TOLERANCE_PP = 10.0


@issue_check("MATH-001", MATH, "Progress above 100% or below 0%", Severity.HIGH)
def impossible_progress(ctx: CheckContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for task in ctx.model.tasks:
        value = task.progress_percentage
        if value is None or 0 <= value <= 100:
            continue
        issues.append(ValidationIssue(
            check_id="MATH-001", family=MATH, severity=Severity.HIGH,
            entity_type="task", entity_id=task.task_id, entity_label=task.title,
            field="progress_percentage", reported_value=f"{value:g}",
            message=f"Task '{task.title}' reports {value:g}% progress, which is impossible.",
            source_references=task.source_references,
        ))

    return issues


@issue_check("MATH-009", MATH, "Workstream progress inconsistent with its tasks",
             Severity.MEDIUM)
def workstream_vs_tasks(ctx: CheckContext) -> list[ValidationIssue]:
    """A workstream reporting 80% while its own tasks average 45% is telling two
    different stories to two different audiences."""
    issues: list[ValidationIssue] = []

    for workstream in ctx.model.workstreams:
        reported = workstream.progress_percentage
        if reported is None:
            continue

        values = [
            t.progress_percentage for t in ctx.model.tasks
            if t.workstream == workstream.name and t.progress_percentage is not None
        ]
        if not values:
            continue

        computed = sum(values) / len(values)
        if abs(reported - computed) <= _PROGRESS_TOLERANCE_PP:
            continue

        issues.append(ValidationIssue(
            check_id="MATH-009", family=MATH, severity=Severity.MEDIUM,
            entity_type="workstream", entity_id=workstream.workstream_id,
            entity_label=workstream.name, field="progress_percentage",
            reported_value=f"{reported:.0f}%", corrected_value=f"{computed:.0f}%",
            message=(
                f"Workstream '{workstream.name}' reports {reported:.0f}% progress, but "
                f"its {len(values)} tracked tasks average {computed:.0f}%."
            ),
            source_references=workstream.source_references,
        ))

    return issues


@issue_check("MATH-010", MATH, "Total budget does not equal the sum of its categories",
             Severity.HIGH)
def budget_rollup(ctx: CheckContext) -> list[ValidationIssue]:
    """A line explicitly labelled "Total" that does not match the lines above it.

    §9 puts budget totals on the critical list — this is the number the CFO reads.
    """
    issues: list[ValidationIssue] = []

    totals = [b for b in ctx.model.budget
              if "total" in b.category.casefold() or "gesamt" in b.category.casefold()]
    parts = [b for b in ctx.model.budget if b not in totals]
    if not totals or not parts:
        return issues

    for field_name, label in (("budget", "budget"), ("actual", "actual"),
                              ("forecast", "forecast")):
        part_values = [getattr(b, field_name) for b in parts
                       if getattr(b, field_name) is not None]
        if not part_values:
            continue
        expected = sum(part_values)

        for total in totals:
            reported = getattr(total, field_name)
            if reported is None or abs(reported - expected) <= _TOLERANCE:
                continue
            issues.append(ValidationIssue(
                check_id="MATH-010", family=MATH, severity=Severity.HIGH,
                entity_type="budget", entity_id=total.budget_item_id,
                entity_label=total.category, field=field_name,
                reported_value=f"{reported:,.0f}", corrected_value=f"{expected:,.0f}",
                message=(
                    f"'{total.category}' reports a {label} of {reported:,.0f} "
                    f"{total.currency}, but the {len(part_values)} category lines sum "
                    f"to {expected:,.0f}."
                ),
                source_references=total.source_references,
            ))

    return issues
