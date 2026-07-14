"""Deterministic derived values (spec §11).

§11 is explicit about what the LLM must *not* be the final authority for:
mathematical calculations, date calculations, budget variances, synergy
calculations, risk scores. Every one of them is computed here, in plain Python,
from values the extractors read out of the files.

Where a source *reported* a derived value that disagrees with the computed one, we
raise a `ValidationIssue` and **use the computed value**. A tracker that says
"variance: 300k" when budget minus forecast is 250k is wrong about its own
arithmetic; propagating its number into a Steering Committee deck would launder
the error.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.models.enums import Severity, Status
from app.models.pmi import PMIDataModel
from app.models.quality import ValidationIssue

#: Money is compared with a tolerance — sources round, and a EUR 0.004 delta is not
#: a reporting error worth escalating to a Steering Committee.
_MONEY_TOLERANCE = 0.01


def recompute_derived(
    model: PMIDataModel, reporting_date: Optional[date] = None
) -> tuple[PMIDataModel, list[ValidationIssue]]:
    """Fill in every derived field and report every disagreement.

    Returns the model (mutated in place) and the issues found. Safe to run twice.
    """
    today = reporting_date or model.project.reporting_date or date.today()
    issues: list[ValidationIssue] = []

    issues += _risk_scores(model)
    issues += _budget_variances(model)
    issues += _synergy_remaining(model)
    issues += _milestone_delays(model)
    issues += _task_overdue(model, today)

    return model, issues


# ------------------------------------------------------------------ risk (§6.5)
def _risk_scores(model: PMIDataModel) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for risk in model.risks:
        if risk.probability is None or risk.impact is None:
            # Cannot compute a product from a missing factor. We do NOT invent the
            # other half (§7) — we null the score and say so.
            if risk.risk_score is not None:
                issues.append(ValidationIssue(
                    check_id="MATH-007",
                    family="mathematical",
                    severity=Severity.MEDIUM,
                    entity_type="risk",
                    entity_id=risk.risk_id,
                    entity_label=risk.title,
                    field="risk_score",
                    reported_value=str(risk.risk_score),
                    message=(
                        f"Risk '{risk.title}' reports a score of {risk.risk_score} but "
                        f"does not state both probability and impact; the score cannot "
                        f"be verified and has been cleared."
                    ),
                    source_references=risk.source_references,
                ))
                risk.risk_score = None
            continue

        computed = risk.probability * risk.impact
        if risk.risk_score is not None and risk.risk_score != computed:
            issues.append(ValidationIssue(
                check_id="MATH-007",
                family="mathematical",
                severity=Severity.MEDIUM,
                entity_type="risk",
                entity_id=risk.risk_id,
                entity_label=risk.title,
                field="risk_score",
                reported_value=str(risk.risk_score),
                corrected_value=str(computed),
                message=(
                    f"Risk '{risk.title}' reports a score of {risk.risk_score}, but "
                    f"probability x impact = {risk.probability} x {risk.impact} = "
                    f"{computed}. Using the computed value."
                ),
                source_references=risk.source_references,
            ))
        risk.risk_score = computed

    return issues


# ---------------------------------------------------------------- budget (§6.9)
def _budget_variances(model: PMIDataModel) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for item in model.budget:
        # §8.2: "Budget variance does not match budget minus forecast".
        # Forecast is the spec's basis; fall back to actual when a tracker only
        # records spend to date.
        basis = item.forecast if item.forecast is not None else item.actual
        if item.budget is None or basis is None:
            continue

        computed = round(item.budget - basis, 2)
        if item.variance is not None and abs(item.variance - computed) > _MONEY_TOLERANCE:
            issues.append(ValidationIssue(
                check_id="MATH-003",
                family="mathematical",
                severity=Severity.HIGH,
                entity_type="budget",
                entity_id=item.budget_item_id,
                entity_label=item.category,
                field="variance",
                reported_value=f"{item.variance:,.2f}",
                corrected_value=f"{computed:,.2f}",
                message=(
                    f"Budget line '{item.category}' reports a variance of "
                    f"{item.variance:,.0f} {item.currency}, but budget minus forecast "
                    f"= {item.budget:,.0f} - {basis:,.0f} = {computed:,.0f}. "
                    f"Using the computed value."
                ),
                source_references=item.source_references,
            ))

        item.variance = computed
        item.variance_percentage = (
            round(computed / item.budget * 100, 1) if item.budget else None
        )

    return issues


# --------------------------------------------------------------- synergy (§6.10)
def _synergy_remaining(model: PMIDataModel) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for syn in model.synergies:
        if syn.target_value is None or syn.realized_value is None:
            continue

        computed = round(syn.target_value - syn.realized_value, 2)
        syn.remaining_value = computed

        # §8.2: "Realized synergy exceeds target without explanation".
        if syn.realized_value > syn.target_value:
            issues.append(ValidationIssue(
                check_id="MATH-008",
                family="mathematical",
                severity=Severity.MEDIUM,
                entity_type="synergy",
                entity_id=syn.synergy_id,
                entity_label=syn.title,
                field="realized_value",
                reported_value=f"{syn.realized_value:,.0f}",
                message=(
                    f"Synergy '{syn.title}' reports {syn.realized_value:,.0f} "
                    f"{syn.currency} realized against a target of "
                    f"{syn.target_value:,.0f} — over-delivery is plausible but "
                    f"unexplained; confirm before reporting it to the Steering Committee."
                ),
                source_references=syn.source_references,
            ))

        # §8.2: "Negative realized synergy without explanation".
        if syn.realized_value < 0:
            issues.append(ValidationIssue(
                check_id="MATH-002",
                family="mathematical",
                severity=Severity.HIGH,
                entity_type="synergy",
                entity_id=syn.synergy_id,
                entity_label=syn.title,
                field="realized_value",
                reported_value=f"{syn.realized_value:,.0f}",
                message=(
                    f"Synergy '{syn.title}' reports a negative realized value "
                    f"({syn.realized_value:,.0f} {syn.currency})."
                ),
                source_references=syn.source_references,
            ))

    return issues


# ------------------------------------------------------------- milestone (§6.4)
def _milestone_delays(model: PMIDataModel) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for ms in model.milestones:
        if ms.planned_date is None:
            continue

        # Actual beats forecast: what happened outranks what was expected.
        against = ms.actual_date or ms.forecast_date
        if against is None:
            continue

        ms.delay_days = (against - ms.planned_date).days

        # §8.2: "Completed milestone with future actual date".
        if ms.actual_date and ms.actual_date > date.today():
            issues.append(ValidationIssue(
                check_id="MATH-005",
                family="mathematical",
                severity=Severity.HIGH,
                entity_type="milestone",
                entity_id=ms.milestone_id,
                entity_label=ms.name,
                field="actual_date",
                reported_value=ms.actual_date.isoformat(),
                message=(
                    f"Milestone '{ms.name}' records an actual completion date in the "
                    f"future ({ms.actual_date:%d-%m-%Y})."
                ),
                source_references=ms.source_references,
            ))

    return issues


# ------------------------------------------------------------------ task (§6.3)
def _task_overdue(model: PMIDataModel, today: date) -> list[ValidationIssue]:
    """`is_overdue` is derived, never trusted from a source.

    §8.2 calls out "Overdue task marked Green" as a check — which only works if we
    compute overdue ourselves rather than believing the RAG column.
    """
    issues: list[ValidationIssue] = []

    for task in model.tasks:
        task.is_overdue = bool(
            task.due_date
            and task.due_date < today
            and task.status.is_open
        )

        if task.is_overdue and task.status is Status.IN_PROGRESS:
            issues.append(ValidationIssue(
                check_id="MATH-006",
                family="mathematical",
                severity=Severity.MEDIUM,
                entity_type="task",
                entity_id=task.task_id,
                entity_label=task.title,
                field="status",
                reported_value=task.status.value,
                message=(
                    f"Task '{task.title}' was due {task.due_date:%d-%m-%Y} and is still "
                    f"open, but is reported as on track."
                ),
                source_references=task.source_references,
            ))

        # §8.2: "Completed tasks without completion dates".
        if task.status is Status.COMPLETED and task.completion_date is None:
            issues.append(ValidationIssue(
                check_id="MATH-004",
                family="mathematical",
                severity=Severity.LOW,
                entity_type="task",
                entity_id=task.task_id,
                entity_label=task.title,
                field="completion_date",
                message=f"Task '{task.title}' is marked complete but has no completion date.",
                source_references=task.source_references,
            ))

    return issues
