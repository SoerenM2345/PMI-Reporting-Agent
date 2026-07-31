"""§8.4 — PMI completeness checks.

What is *missing*. This family exists because of §7's rule that the agent must never
invent missing information: having refused to invent it, the agent owes the user a
clear statement of what is absent.

That is a deliberately different posture from most reporting tools, which quietly
render a blank cell and let the reader assume zero. A critical risk with no mitigation
owner is not a formatting problem — it is the single most useful thing an IMO could
learn from this report, and it belongs on the slide.
"""
from __future__ import annotations

from app.agent.consistency.registry import CheckContext, issue_check
from app.models.pmi import Severity, Status, ValidationIssue

COMP = "completeness"


def _issue(check_id: str, severity: Severity, entity_type: str, entity_id: str,
           label: str, field: str, message: str, refs) -> ValidationIssue:
    return ValidationIssue(
        check_id=check_id, family=COMP, severity=severity,
        entity_type=entity_type, entity_id=entity_id, entity_label=label,
        field=field, message=message, source_references=refs,
    )


@issue_check("COMP-001", COMP, "Critical task with no owner", Severity.HIGH)
def critical_task_no_owner(ctx: CheckContext) -> list[ValidationIssue]:
    """A task nobody owns is a task nobody will do."""
    return [
        _issue("COMP-001", Severity.HIGH, "task", t.task_id, t.title, "owner",
               f"Task '{t.title}' is Day-1 critical or overdue but has no owner.",
               t.source_references)
        for t in ctx.model.tasks
        if not t.owner and (t.is_day_1_critical or t.is_overdue)
    ]


@issue_check("COMP-002", COMP, "Critical risk with no mitigation", Severity.CRITICAL)
def critical_risk_no_mitigation(ctx: CheckContext) -> list[ValidationIssue]:
    """§9 puts critical risks on the critical list. An unmitigated one is the report."""
    return [
        _issue("COMP-002", Severity.CRITICAL, "risk", r.risk_id, r.title,
               "mitigation_action",
               f"Risk '{r.title}' is rated {r.rating.value} but has no mitigation action.",
               r.source_references)
        for r in ctx.model.risks
        if r.status.is_open
        and r.rating in (Severity.HIGH, Severity.CRITICAL)
        and not r.mitigation_action
    ]


@issue_check("COMP-003", COMP, "Mitigation with no owner", Severity.HIGH)
def mitigation_no_owner(ctx: CheckContext) -> list[ValidationIssue]:
    return [
        _issue("COMP-003", Severity.HIGH, "risk", r.risk_id, r.title,
               "mitigation_owner",
               f"Risk '{r.title}' has a mitigation action but nobody is assigned to it.",
               r.source_references)
        for r in ctx.model.risks
        if r.status.is_open and r.mitigation_action and not r.mitigation_owner
    ]


@issue_check("COMP-004", COMP, "Decision with no deadline", Severity.HIGH)
def decision_no_deadline(ctx: CheckContext) -> list[ValidationIssue]:
    """A Steering Committee decision with no date is a decision that will not be made."""
    return [
        _issue("COMP-004", Severity.HIGH, "decision", d.decision_id, d.title,
               "decision_deadline",
               f"Decision '{d.title}' is open but has no deadline, so it cannot be "
               f"scheduled onto a governance agenda.",
               d.source_references)
        for d in ctx.model.decisions
        if d.status.is_open and not d.decision_deadline
    ]


@issue_check("COMP-005", COMP, "Workstream with no progress update", Severity.MEDIUM)
def workstream_no_update(ctx: CheckContext) -> list[ValidationIssue]:
    """§12.2 asks the IMO deck for "missing updates" — a workstream that reported
    nothing this period is itself the finding."""
    return [
        _issue("COMP-005", Severity.MEDIUM, "workstream", w.workstream_id, w.name,
               "progress_percentage",
               f"Workstream '{w.name}' did not report progress this period.",
               w.source_references)
        for w in ctx.model.workstreams
        if w.progress_percentage is None and w.status is Status.UNKNOWN
    ]


@issue_check("COMP-006", COMP, "Budget item with no forecast", Severity.MEDIUM)
def budget_no_forecast(ctx: CheckContext) -> list[ValidationIssue]:
    """Without a forecast there is no variance, and without a variance there is no
    early warning — only a surprise at year end."""
    return [
        _issue("COMP-006", Severity.MEDIUM, "budget", b.budget_item_id, b.category,
               "forecast",
               f"Budget line '{b.category}' has no forecast, so its variance cannot "
               f"be computed.",
               b.source_references)
        for b in ctx.model.budget
        if b.forecast is None and b.budget is not None
    ]


@issue_check("COMP-007", COMP, "Synergy with no realization date", Severity.MEDIUM)
def synergy_no_date(ctx: CheckContext) -> list[ValidationIssue]:
    """A synergy with no date is a hope, not a plan — and it was in the deal model."""
    return [
        _issue("COMP-007", Severity.MEDIUM, "synergy", s.synergy_id, s.title,
               "planned_realization_date",
               f"Synergy '{s.title}' has a target of "
               f"{s.target_value:,.0f} {s.currency} but no realization date."
               if s.target_value is not None else
               f"Synergy '{s.title}' has no planned realization date.",
               s.source_references)
        for s in ctx.model.synergies
        if s.planned_realization_date is None
    ]


@issue_check("COMP-008", COMP, "Dependency with no owner", Severity.HIGH)
def dependency_no_owner(ctx: CheckContext) -> list[ValidationIssue]:
    """A cross-workstream dependency nobody owns sits in the gap between two teams,
    each assuming the other has it."""
    return [
        _issue("COMP-008", Severity.HIGH, "dependency", d.dependency_id,
               d.description, "owner",
               f"Dependency '{d.description[:60]}' has no owner"
               + (f" (from {d.providing_workstream} to {d.receiving_workstream})."
                  if d.providing_workstream and d.receiving_workstream else "."),
               d.source_references)
        for d in ctx.model.dependencies
        if not d.owner and d.status.is_open
    ]


@issue_check("COMP-009", COMP, "Item with no source reference", Severity.HIGH)
def no_source_reference(ctx: CheckContext) -> list[ValidationIssue]:
    """Every value must be traceable (§5). An untraceable one cannot be defended when
    a Steering Committee member asks where it came from — so it should not be on the
    slide."""
    issues: list[ValidationIssue] = []

    collections = [
        ("task", ctx.model.tasks, "task_id", "title"),
        ("milestone", ctx.model.milestones, "milestone_id", "name"),
        ("risk", ctx.model.risks, "risk_id", "title"),
        ("budget", ctx.model.budget, "budget_item_id", "category"),
        ("synergy", ctx.model.synergies, "synergy_id", "title"),
        ("kpi", ctx.model.kpis, "kpi_id", "name"),
    ]
    for entity_type, items, id_attr, label_attr in collections:
        for item in items:
            if item.source_references:
                continue
            issues.append(_issue(
                "COMP-009", Severity.HIGH, entity_type,
                getattr(item, id_attr), getattr(item, label_attr), "source_references",
                f"{entity_type.title()} '{getattr(item, label_attr)}' has no source "
                f"reference and cannot be traced back to any uploaded file.",
                [],
            ))

    return issues


@issue_check("COMP-010", COMP, "Project header incomplete", Severity.MEDIUM)
def project_header(ctx: CheckContext) -> list[ValidationIssue]:
    """No reporting date, no Day 1 date, no workstream leads.

    These come from the user at upload (§4 step 1), not from the files — a masterplan
    does not state its own signing date. Without them, whole check families cannot run:
    no reporting date means no overdue calculation; no Day 1 date means TIME-004 is
    silently skipped. The user should know which checks their metadata disabled.
    """
    issues: list[ValidationIssue] = []
    project = ctx.model.project

    if project.reporting_date is None:
        issues.append(_issue(
            "COMP-010", Severity.MEDIUM, "project", project.project_id,
            project.project_name, "reporting_date",
            "No reporting date was given, so today's date was used to decide what is "
            "overdue. Set it on the project to date the report correctly.",
            [],
        ))

    if project.day_1_date is None and any(t.is_day_1_critical for t in ctx.model.tasks):
        issues.append(_issue(
            "COMP-010", Severity.MEDIUM, "project", project.project_id,
            project.project_name, "day_1_date",
            "Day-1-critical items were found, but no Day 1 date is set — so the check "
            "for Day-1 activities scheduled after Day 1 (TIME-004) could not run.",
            [],
        ))

    for workstream in ctx.model.workstreams:
        if not workstream.lead:
            issues.append(_issue(
                "COMP-010", Severity.MEDIUM, "workstream", workstream.workstream_id,
                workstream.name, "lead",
                f"Workstream '{workstream.name}' has no lead assigned.",
                workstream.source_references,
            ))

    return issues
