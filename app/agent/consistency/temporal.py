"""§8.3 — temporal checks.

Dates that cannot be true. These are cheap to detect and embarrassing to publish: a
Steering Committee that spots a task completed before it started stops trusting every
other number on the slide.

This is also why dates are stored as `date` and only *formatted* DD-MM-YYYY at the
edges (§7). Every check here is arithmetic on real dates; storing them as strings
would make all of it impossible.
"""
from __future__ import annotations

from app.agent.consistency.registry import CheckContext, issue_check
from app.models.pmi import Severity, Status, ValidationIssue

TIME = "temporal"


@issue_check("TIME-001", TIME, "Task due date before its start date", Severity.MEDIUM)
def due_before_start(ctx: CheckContext) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            check_id="TIME-001", family=TIME, severity=Severity.MEDIUM,
            entity_type="task", entity_id=t.task_id, entity_label=t.title,
            field="due_date", reported_value=t.due_date.isoformat(),
            message=(
                f"Task '{t.title}' is due {t.due_date:%d-%m-%Y}, before it starts "
                f"({t.start_date:%d-%m-%Y})."
            ),
            source_references=t.source_references,
        )
        for t in ctx.model.tasks
        if t.start_date and t.due_date and t.due_date < t.start_date
    ]


@issue_check("TIME-002", TIME, "Task completed before it started", Severity.HIGH)
def completed_before_start(ctx: CheckContext) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            check_id="TIME-002", family=TIME, severity=Severity.HIGH,
            entity_type="task", entity_id=t.task_id, entity_label=t.title,
            field="completion_date", reported_value=t.completion_date.isoformat(),
            message=(
                f"Task '{t.title}' records completion on {t.completion_date:%d-%m-%Y}, "
                f"before its start date ({t.start_date:%d-%m-%Y})."
            ),
            source_references=t.source_references,
        )
        for t in ctx.model.tasks
        if t.start_date and t.completion_date and t.completion_date < t.start_date
    ]


@issue_check("TIME-003", TIME, "Open task forecast to finish in the past", Severity.MEDIUM)
def forecast_in_the_past(ctx: CheckContext) -> list[ValidationIssue]:
    """An open task whose forecast completion is before the reporting date. The
    forecast is stale, and the plan it feeds is fiction."""
    today = ctx.reporting_date
    return [
        ValidationIssue(
            check_id="TIME-003", family=TIME, severity=Severity.MEDIUM,
            entity_type="milestone", entity_id=m.milestone_id, entity_label=m.name,
            field="forecast_date", reported_value=m.forecast_date.isoformat(),
            message=(
                f"Milestone '{m.name}' is still open but forecast to complete "
                f"{m.forecast_date:%d-%m-%Y}, before the reporting date "
                f"({today:%d-%m-%Y}). The forecast has not been refreshed."
            ),
            source_references=m.source_references,
        )
        for m in ctx.model.milestones
        if m.forecast_date and m.status.is_open and m.forecast_date < today
    ]


@issue_check("TIME-004", TIME, "Day 1 activity scheduled after Day 1", Severity.CRITICAL)
def day_1_after_day_1(ctx: CheckContext) -> list[ValidationIssue]:
    """A Day-1-critical task due after Day 1.

    Critical by definition: these are the things that must work the morning the deal
    closes — payroll, building access, the ability to invoice. A Day-1 task with a
    Day-2 date is a Day-1 failure that nobody has noticed yet.
    """
    day_1 = ctx.model.project.day_1_date
    if day_1 is None:
        return []

    issues: list[ValidationIssue] = []

    for task in ctx.model.tasks:
        if not task.is_day_1_critical or task.due_date is None:
            continue
        if task.due_date <= day_1:
            continue
        issues.append(ValidationIssue(
            check_id="TIME-004", family=TIME, severity=Severity.CRITICAL,
            entity_type="task", entity_id=task.task_id, entity_label=task.title,
            field="due_date", reported_value=task.due_date.isoformat(),
            message=(
                f"'{task.title}' is Day-1 critical but is due {task.due_date:%d-%m-%Y}, "
                f"after Day 1 ({day_1:%d-%m-%Y})."
            ),
            source_references=task.source_references,
        ))

    for milestone in ctx.model.milestones:
        if not milestone.is_day_1_critical or milestone.planned_date is None:
            continue
        if milestone.planned_date <= day_1:
            continue
        issues.append(ValidationIssue(
            check_id="TIME-004", family=TIME, severity=Severity.CRITICAL,
            entity_type="milestone", entity_id=milestone.milestone_id,
            entity_label=milestone.name, field="planned_date",
            reported_value=milestone.planned_date.isoformat(),
            message=(
                f"Milestone '{milestone.name}' is Day-1 critical but is planned for "
                f"{milestone.planned_date:%d-%m-%Y}, after Day 1 ({day_1:%d-%m-%Y})."
            ),
            source_references=milestone.source_references,
        ))

    return issues


@issue_check("TIME-005", TIME, "TSA exit before the integration starts", Severity.HIGH)
def tsa_exit_before_start(ctx: CheckContext) -> list[ValidationIssue]:
    """A Transitional Service Agreement cannot be exited before it begins."""
    start = ctx.model.project.integration_start_date or ctx.model.project.closing_date
    if start is None:
        return []

    return [
        ValidationIssue(
            check_id="TIME-005", family=TIME, severity=Severity.HIGH,
            entity_type="milestone", entity_id=m.milestone_id, entity_label=m.name,
            field="planned_date", reported_value=m.planned_date.isoformat(),
            message=(
                f"TSA milestone '{m.name}' is planned for {m.planned_date:%d-%m-%Y}, "
                f"before the TSA period begins ({start:%d-%m-%Y})."
            ),
            source_references=m.source_references,
        )
        for m in ctx.model.milestones
        if m.planned_date and "tsa" in m.name.casefold() and m.planned_date < start
    ]


@issue_check("TIME-006", TIME, "Milestone completed with a future actual date",
             Severity.HIGH)
def future_actual_date(ctx: CheckContext) -> list[ValidationIssue]:
    """Marked done, with a completion date that has not happened yet."""
    today = ctx.reporting_date
    return [
        ValidationIssue(
            check_id="TIME-006", family=TIME, severity=Severity.HIGH,
            entity_type="milestone", entity_id=m.milestone_id, entity_label=m.name,
            field="actual_date", reported_value=m.actual_date.isoformat(),
            message=(
                f"Milestone '{m.name}' is reported complete with an actual date of "
                f"{m.actual_date:%d-%m-%Y}, which is in the future."
            ),
            source_references=m.source_references,
        )
        for m in ctx.model.milestones
        if m.actual_date and m.actual_date > today
    ]


@issue_check("TIME-007", TIME, "Risk closed before its mitigation was done",
             Severity.MEDIUM)
def risk_closed_before_mitigation(ctx: CheckContext) -> list[ValidationIssue]:
    """A risk marked closed while its mitigation action is still outstanding.

    Usually means somebody closed the register entry rather than the risk.
    """
    today = ctx.reporting_date
    return [
        ValidationIssue(
            check_id="TIME-007", family=TIME, severity=Severity.MEDIUM,
            entity_type="risk", entity_id=r.risk_id, entity_label=r.title,
            field="status", reported_value=r.status.value,
            message=(
                f"Risk '{r.title}' is closed, but its mitigation "
                f"('{r.mitigation_action}') is not due until "
                f"{r.mitigation_due_date:%d-%m-%Y}."
            ),
            source_references=r.source_references,
        )
        for r in ctx.model.risks
        if (r.status is Status.COMPLETED
            and r.mitigation_action
            and r.mitigation_due_date
            and r.mitigation_due_date > today)
    ]
