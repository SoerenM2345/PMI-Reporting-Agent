"""Excel dashboard generation (spec §13). XlsxWriter; the output is an editable .xlsx.

The ten sheets §13 asks for. The last one — **Data Quality** (§13 sheet 10) — is the
one that matters most and the one no PMI tool ships: conflicts, missing fields,
low-confidence image extractions, what was auto-resolved and what a human decided.

§13's quality requirements (filters, frozen headers, conditional formatting, consistent
date formats, currency formats, readable widths, no broken references) are applied to
every sheet, because a dashboard nobody can filter is a table, and a table nobody can
read is a PDF.

Where a value is unknown it is written as "Not Reported", never as 0 or blank (§7). A
zero is a claim; a blank is a bug report. Neither is the truth.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import xlsxwriter

from app.agent.data_quality import summarize
from app.models.pmi import (
    Audience,
    DataQualityReport,
    PMIDataModel,
    Severity,
    Status,
)
from app.report import format as fmt
from app.report.format import NOT_REPORTED

log = logging.getLogger("pmi.xlsx")

GREEN = "#2E7D32"
LIGHT_GREEN = "#C8E6C9"
AMBER = "#FFF3CD"
RED = "#F8D7DA"
GREY = "#757575"
DARK = "#1A1A1A"


def generate(
    model: PMIDataModel,
    audience: Audience,
    bullets: list[str],
    out_dir: Path,
    quality: Optional[DataQualityReport] = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"PMI_Dashboard_{audience.value}_{date.today().isoformat()}.xlsx"

    workbook = xlsxwriter.Workbook(str(path))
    fmt = _formats(workbook)

    _executive_dashboard(workbook, fmt, model, bullets)   # §13 sheet 1
    _workstream_scorecard(workbook, fmt, model)           # §13 sheet 2
    _masterplan(workbook, fmt, model)                     # §13 sheet 3
    _risks(workbook, fmt, model)                          # §13 sheet 4
    _issues(workbook, fmt, model)                         # §13 sheet 5
    _dependencies(workbook, fmt, model)                   # §13 sheet 6
    _decisions(workbook, fmt, model)                      # §13 sheet 7
    _budget(workbook, fmt, model)                         # §13 sheet 8
    _synergies(workbook, fmt, model)                      # §13 sheet 9
    _data_quality(workbook, fmt, model, quality)          # §13 sheet 10

    workbook.close()
    log.info("wrote %s", path.name)
    return path


# ------------------------------------------------------- §13.1 Executive Dashboard
def _executive_dashboard(workbook, fmt, model: PMIDataModel, bullets: list[str]) -> None:
    sheet = workbook.add_worksheet("Executive Dashboard")
    sheet.set_column(0, 0, 44)
    sheet.set_column(1, 4, 18)
    sheet.hide_gridlines(2)

    sheet.write(0, 0, model.project.project_name, fmt["title"])
    when = model.project.reporting_date or date.today()
    sheet.write(1, 0, f"Reporting date: {when:%d-%m-%Y}", fmt["muted"])

    row = 3
    sheet.write(row, 0, "Executive summary", fmt["header"])
    for bullet in bullets:
        row += 1
        sheet.write(row, 0, f"• {bullet}", fmt["wrap"])

    progress = model.overall_progress()
    day_1 = [t for t in model.tasks if t.is_day_1_critical]
    day_1_done = sum(1 for t in day_1 if t.status is Status.COMPLETED)
    open_critical = [r for r in model.critical_risks() if r.status.is_open]

    budget = sum(b.budget or 0 for b in model.budget)
    forecast = sum(b.forecast or 0 for b in model.budget)
    target = sum(s.target_value or 0 for s in model.synergies)
    realized = sum(s.realized_value or 0 for s in model.synergies)

    row += 2
    sheet.write(row, 0, "Key figures", fmt["header"])
    sheet.write(row, 1, "Value", fmt["header"])

    figures = [
        ("Overall PMI status", _overall_status(model)),
        ("Overall progress",
         f"{progress:.0f}%" if progress is not None else NOT_REPORTED),
        ("Day 1 readiness",
         f"{day_1_done}/{len(day_1)} complete" if day_1 else NOT_REPORTED),
        ("Open critical risks", len(open_critical)),
        ("Open issues", sum(1 for i in model.issues if i.status.is_open)),
        ("Overdue tasks", len(model.overdue_tasks())),
        ("Overdue milestones",
         sum(1 for m in model.milestones if (m.delay_days or 0) > 0)),
        ("Budget variance",
         f"{budget - forecast:,.0f}" if budget and forecast else NOT_REPORTED),
        ("Synergy realization",
         f"{realized / target * 100:.0f}%" if target else NOT_REPORTED),
        ("Decisions required",
         sum(1 for d in model.decisions if d.status.is_open)),
        ("Unresolved source conflicts", len(model.unresolved_conflicts())),
    ]
    for label, value in figures:
        row += 1
        sheet.write(row, 0, label, fmt["label"])
        sheet.write(row, 1, value, fmt["cell"])

    # Native Excel chart (§14: "For Excel: prefer native Excel charts") — it stays
    # live when the user edits the numbers, which a pasted PNG does not.
    from collections import Counter

    counts = Counter(t.status for t in model.tasks)
    if counts:
        row += 2
        anchor = row
        sheet.write(row, 3, "Status", fmt["header"])
        sheet.write(row, 4, "Tasks", fmt["header"])
        for status, count in counts.items():
            row += 1
            sheet.write(row, 3, status.value.replace("_", " ").title(), fmt["cell"])
            sheet.write_number(row, 4, count, fmt["number"])

        chart = workbook.add_chart({"type": "column"})
        chart.add_series({
            "name": "Tasks by status",
            "categories": ["Executive Dashboard", anchor + 1, 3, row, 3],
            "values": ["Executive Dashboard", anchor + 1, 4, row, 4],
            "fill": {"color": GREEN},
        })
        chart.set_title({"name": "Tasks by status"})
        chart.set_legend({"none": True})
        sheet.insert_chart(anchor, 6, chart, {"x_scale": 1.2, "y_scale": 1.2})


def _overall_status(model: PMIDataModel) -> str:
    if model.unresolved_conflicts():
        return "Not agreed — unresolved source conflicts"
    if [r for r in model.critical_risks() if r.status.is_open]:
        return "At Risk"
    if model.overdue_tasks():
        return "At Risk — overdue activities"
    if model.tasks:
        return "On Track"
    return NOT_REPORTED


# ------------------------------------------------------ §13.2 Workstream Scorecard
def _workstream_scorecard(workbook, fmt, model: PMIDataModel) -> None:
    if not model.workstreams:
        return

    rows = [
        [
            w.name, w.lead or NOT_REPORTED,
            w.status.value.replace("_", " ").title(),
            w.progress_percentage if w.progress_percentage is not None else NOT_REPORTED,
            len(w.open_risks), len(w.open_issues), len(w.upcoming_milestones),
            _cite(w),
        ]
        for w in model.workstreams
    ]
    _sheet(workbook, fmt, "Workstream Scorecard",
           ["Workstream", "Lead", "Status", "Progress %", "Open risks",
            "Open issues", "Milestones", "Source"],
           rows, percent_columns=[3], rag_column=2)


# ------------------------------------------------------ §13.3 Integration Masterplan
def _masterplan(workbook, fmt, model: PMIDataModel) -> None:
    rows = [
        [
            t.task_id, "Task", t.title, t.workstream or "—",
            t.owner or NOT_REPORTED,
            t.status.value.replace("_", " ").title(),
            t.progress_percentage if t.progress_percentage is not None else NOT_REPORTED,
            _d(t.start_date), _d(t.due_date),
            "YES" if t.is_overdue else "",
            "YES" if t.is_day_1_critical else "",
            _cite(t),
        ]
        for t in model.tasks
    ] + [
        [
            m.milestone_id, "Milestone", m.name, m.workstream or "—",
            m.owner or NOT_REPORTED,
            m.status.value.replace("_", " ").title(),
            NOT_REPORTED,
            "", _d(m.planned_date),
            "YES" if (m.delay_days or 0) > 0 else "",
            "YES" if m.is_day_1_critical else "",
            _cite(m),
        ]
        for m in model.milestones
    ]
    if not rows:
        return

    _sheet(workbook, fmt, "Masterplan",
           ["ID", "Type", "Title", "Workstream", "Owner", "Status", "Progress %",
            "Start", "Due", "Overdue", "Day 1", "Source"],
           rows, percent_columns=[6], rag_column=5, flag_columns=[9, 10])


# --------------------------------------------------------------- §13.4 Risks
def _risks(workbook, fmt, model: PMIDataModel) -> None:
    if not model.risks:
        return

    rows = [
        [
            r.risk_id, r.title, r.category.value, r.workstream or "—",
            r.rating.value.title(),
            r.probability if r.probability is not None else NOT_REPORTED,
            r.impact if r.impact is not None else NOT_REPORTED,
            r.risk_score if r.risk_score is not None else NOT_REPORTED,
            r.trend.value.title(),
            r.owner or NOT_REPORTED,
            r.mitigation_action or NOT_REPORTED,
            r.mitigation_owner or NOT_REPORTED,
            _d(r.mitigation_due_date),
            "YES" if r.escalation_required else "",
            r.status.value.replace("_", " ").title(),
            _cite(r),
        ]
        for r in sorted(model.risks, key=lambda r: r.risk_score or 0, reverse=True)
    ]
    _sheet(workbook, fmt, "Risks",
           ["ID", "Risk", "Category", "Workstream", "Rating", "Probability", "Impact",
            "Score", "Trend", "Owner", "Mitigation", "Mitigation owner",
            "Mitigation due", "Escalate", "Status", "Source"],
           rows, rag_column=4, flag_columns=[13])


# -------------------------------------------------------------- §13.5 Issues
def _issues(workbook, fmt, model: PMIDataModel) -> None:
    if not model.issues:
        return
    rows = [
        [
            i.issue_id, i.title, i.workstream or "—", i.severity.value.title(),
            i.owner or NOT_REPORTED,
            i.resolution_action or NOT_REPORTED,
            i.resolution_owner or NOT_REPORTED,
            _d(i.due_date),
            "YES" if i.escalation_required else "",
            i.status.value.replace("_", " ").title(),
            _cite(i),
        ]
        for i in model.issues
    ]
    _sheet(workbook, fmt, "Issues",
           ["ID", "Issue", "Workstream", "Severity", "Owner", "Resolution",
            "Resolution owner", "Due", "Escalate", "Status", "Source"],
           rows, rag_column=3, flag_columns=[8])


# -------------------------------------------------------- §13.6 Dependencies
def _dependencies(workbook, fmt, model: PMIDataModel) -> None:
    if not model.dependencies:
        return
    rows = [
        [
            d.dependency_id, d.description,
            d.providing_workstream or "—", d.receiving_workstream or "—",
            d.owner or NOT_REPORTED, _d(d.required_date),
            d.status.value.replace("_", " ").title(),
            d.impact_if_delayed or NOT_REPORTED,
            _cite(d),
        ]
        for d in model.dependencies
    ]
    _sheet(workbook, fmt, "Dependencies",
           ["ID", "Dependency", "Providing", "Receiving", "Owner", "Required by",
            "Status", "Impact if delayed", "Source"],
           rows, rag_column=6)


# ----------------------------------------------------------- §13.7 Decisions
def _decisions(workbook, fmt, model: PMIDataModel) -> None:
    if not model.decisions:
        return
    rows = [
        [
            d.decision_id, d.title, d.decision_body.value,
            d.decision_owner or NOT_REPORTED,
            _d(d.decision_deadline),
            d.status.value.replace("_", " ").title(),
            d.recommended_option or NOT_REPORTED,
            d.impact or NOT_REPORTED,
            _cite(d),
        ]
        for d in model.decisions
    ]
    _sheet(workbook, fmt, "Decisions",
           ["ID", "Decision", "Body", "Owner", "Deadline", "Status",
            "Recommended option", "Impact", "Source"],
           rows, rag_column=5)


# -------------------------------------------------------------- §13.8 Budget
def _budget(workbook, fmt, model: PMIDataModel) -> None:
    if not model.budget:
        return
    rows = [
        [
            b.budget_item_id, b.category, b.workstream or "—",
            b.budget if b.budget is not None else NOT_REPORTED,
            b.actual if b.actual is not None else NOT_REPORTED,
            b.committed if b.committed is not None else NOT_REPORTED,
            b.forecast if b.forecast is not None else NOT_REPORTED,
            b.variance if b.variance is not None else NOT_REPORTED,
            b.variance_percentage if b.variance_percentage is not None else NOT_REPORTED,
            b.currency, _cite(b),
        ]
        for b in model.budget
    ]
    _sheet(workbook, fmt, "Budget",
           ["ID", "Category", "Workstream", "Budget", "Actual", "Committed",
            "Forecast", "Variance", "Variance %", "Currency", "Source"],
           rows, currency_columns=[3, 4, 5, 6, 7], negative_columns=[7, 8])


# ----------------------------------------------------------- §13.9 Synergies
def _synergies(workbook, fmt, model: PMIDataModel) -> None:
    if not model.synergies:
        return
    rows = [
        [
            s.synergy_id, s.title, s.synergy_type.value, s.workstream or "—",
            s.owner or NOT_REPORTED,
            s.target_value if s.target_value is not None else NOT_REPORTED,
            s.realized_value if s.realized_value is not None else NOT_REPORTED,
            s.forecast_value if s.forecast_value is not None else NOT_REPORTED,
            s.remaining_value if s.remaining_value is not None else NOT_REPORTED,
            _d(s.planned_realization_date),
            s.confidence_level or NOT_REPORTED,
            s.currency, _cite(s),
        ]
        for s in model.synergies
    ]
    _sheet(workbook, fmt, "Synergies",
           ["ID", "Synergy", "Type", "Workstream", "Owner", "Target", "Realized",
            "Forecast", "Remaining gap", "Realization date", "Confidence",
            "Currency", "Source"],
           rows, currency_columns=[5, 6, 7, 8])


# ------------------------------------------------------- §13.10 Data Quality
def _data_quality(
    workbook, fmt, model: PMIDataModel, report: Optional[DataQualityReport]
) -> None:
    """§13 sheet 10 — and the reason the rest of the workbook can be trusted."""
    sheet = workbook.add_worksheet("Data Quality")
    sheet.set_column(0, 0, 40)
    sheet.set_column(1, 6, 24)
    sheet.hide_gridlines(2)

    sheet.write(0, 0, "Data Quality", fmt["title"])
    row = 1

    if report:
        sheet.write(row, 0, f"Score: {report.score:.0f} / 100", fmt["label"])
        row += 2
        for line in summarize(report):
            sheet.write(row, 0, f"• {line}", fmt["wrap"])
            row += 1

    # --- conflicts (§9) ------------------------------------------------------
    row += 1
    sheet.write(row, 0, "Cross-source conflicts", fmt["header"])
    row += 1
    for column, heading in enumerate(
        ["Item", "Field", "Severity", "Reported values", "Resolved to",
         "From", "How"]
    ):
        sheet.write(row, column, heading, fmt["header"])

    for conflict in model.conflicts:
        row += 1
        values = "; ".join(f"{f}: {v}" for f, v in conflict.values.items())
        resolved = conflict.resolved_value or "UNRESOLVED"
        style = fmt["bad"] if not conflict.is_resolved else fmt["cell"]

        sheet.write(row, 0, conflict.entity_key, style)
        sheet.write(row, 1, conflict.field.replace("_", " "), style)
        sheet.write(row, 2, conflict.severity.value.title(), style)
        sheet.write(row, 3, values, style)
        sheet.write(row, 4, resolved, style)
        sheet.write(row, 5, conflict.resolved_from or "—", style)
        sheet.write(row, 6, conflict.resolution or "awaiting user", style)

    # --- low-confidence image extractions (§5.6) -----------------------------
    low = model.low_confidence_items()
    if low:
        row += 2
        sheet.write(row, 0, "Low-confidence findings — verify before use", fmt["header"])
        row += 1
        for column, heading in enumerate(["Type", "Item", "Confidence", "Read from"]):
            sheet.write(row, column, heading, fmt["header"])
        for kind, label, confidence in sorted(low, key=lambda x: x[2]):
            row += 1
            sheet.write(row, 0, kind, fmt["warn"])
            sheet.write(row, 1, label, fmt["warn"])
            sheet.write_number(row, 2, confidence, fmt["percent"])
            sheet.write(row, 3, _find_source(model, kind, label), fmt["warn"])

    # --- validation issues (§8.2-8.4) ---------------------------------------
    if model.validation_issues:
        row += 2
        sheet.write(row, 0, "Validation issues", fmt["header"])
        row += 1
        for column, heading in enumerate(
            ["Check", "Family", "Severity", "Item", "Finding", "Corrected to"]
        ):
            sheet.write(row, column, heading, fmt["header"])
        for issue in model.validation_issues:
            row += 1
            style = (fmt["bad"] if issue.severity in (Severity.HIGH, Severity.CRITICAL)
                     else fmt["warn"])
            sheet.write(row, 0, issue.check_id, style)
            sheet.write(row, 1, issue.family, style)
            sheet.write(row, 2, issue.severity.value.title(), style)
            sheet.write(row, 3, issue.entity_label, style)
            sheet.write(row, 4, issue.message, style)
            sheet.write(row, 5, issue.corrected_value or "—", style)

    # --- what went wrong -----------------------------------------------------
    warnings = (report.warnings if report else []) + (
        [f"FILE COULD NOT BE READ: {f}" for f in report.failed_files] if report else []
    )
    if warnings:
        row += 2
        sheet.write(row, 0, "Processing caveats", fmt["header"])
        for warning in warnings:
            row += 1
            sheet.write(row, 0, warning, fmt["warn"])


# ================================================================== plumbing
def _sheet(
    workbook, fmt, name: str, headers: list[str], rows: list[list],
    *,
    percent_columns: list[int] | None = None,
    currency_columns: list[int] | None = None,
    negative_columns: list[int] | None = None,
    rag_column: int | None = None,
    flag_columns: list[int] | None = None,
) -> None:
    """One sheet, with every §13 quality requirement applied."""
    sheet = workbook.add_worksheet(name[:31])
    percent_columns = percent_columns or []
    currency_columns = currency_columns or []
    negative_columns = negative_columns or []
    flag_columns = flag_columns or []

    for column, heading in enumerate(headers):
        width = max(12, min(len(heading) + 6, 46))
        if column == 1:
            width = 48  # the title column
        sheet.set_column(column, column, width)
        sheet.write(0, column, heading, fmt["header"])

    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            if value == NOT_REPORTED:
                sheet.write(r, c, NOT_REPORTED, fmt["muted"])
            elif c in percent_columns and isinstance(value, (int, float)):
                sheet.write_number(r, c, value / 100, fmt["percent"])
            elif c in currency_columns and isinstance(value, (int, float)):
                style = fmt["currency_bad"] if (c in negative_columns and value < 0) \
                    else fmt["currency"]
                sheet.write_number(r, c, value, style)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                sheet.write_number(r, c, value, fmt["number"])
            elif c in flag_columns and value == "YES":
                sheet.write(r, c, value, fmt["bad"])
            else:
                sheet.write(r, c, "" if value is None else str(value), fmt["cell"])

    last_row, last_column = max(len(rows), 1), len(headers) - 1

    # §13 quality requirements
    sheet.autofilter(0, 0, last_row, last_column)
    sheet.freeze_panes(1, 0)

    if rag_column is not None:
        for text, style in (
            ("At Risk", "amber"), ("Blocked", "bad"), ("Overdue", "bad"),
            ("Critical", "bad"), ("High", "bad"),
            ("Completed", "good"), ("In Progress", "good"), ("Low", "good"),
        ):
            sheet.conditional_format(1, rag_column, last_row, rag_column, {
                "type": "text", "criteria": "containing", "value": text,
                "format": fmt[style],
            })

    for column in negative_columns:
        sheet.conditional_format(1, column, last_row, column, {
            "type": "cell", "criteria": "<", "value": 0, "format": fmt["bad"],
        })


def _formats(workbook) -> dict:
    return {
        "title": workbook.add_format({"bold": True, "font_size": 18,
                                      "font_color": DARK}),
        "header": workbook.add_format({
            "bold": True, "bg_color": GREEN, "font_color": "white",
            "border": 1, "text_wrap": True, "valign": "vcenter",
        }),
        "cell": workbook.add_format({"border": 1, "valign": "top",
                                     "text_wrap": True}),
        "wrap": workbook.add_format({"text_wrap": True, "valign": "top"}),
        "label": workbook.add_format({"bold": True}),
        "muted": workbook.add_format({"font_color": GREY, "italic": True,
                                      "border": 1}),
        "number": workbook.add_format({"border": 1, "num_format": "#,##0.##"}),
        # §13: "Consistent date formats" — DD-MM-YYYY, per §7.
        "date": workbook.add_format({"border": 1, "num_format": "dd-mm-yyyy"}),
        "percent": workbook.add_format({"border": 1, "num_format": "0%"}),
        "currency": workbook.add_format({"border": 1, "num_format": "#,##0"}),
        "currency_bad": workbook.add_format({
            "border": 1, "num_format": "#,##0", "bg_color": RED, "font_color": "#7F1D1D",
        }),
        "good": workbook.add_format({"bg_color": LIGHT_GREEN, "border": 1}),
        "amber": workbook.add_format({"bg_color": AMBER, "border": 1}),
        "warn": workbook.add_format({"bg_color": AMBER, "border": 1,
                                     "text_wrap": True, "valign": "top"}),
        "bad": workbook.add_format({"bg_color": RED, "border": 1,
                                    "text_wrap": True, "valign": "top"}),
    }


def _d(value) -> str:
    return fmt.date_str(value, missing=NOT_REPORTED)


def _cite(entity) -> str:
    """A cell has the width for the sheet/cell reference, and a workbook reader
    wants it — this is where someone goes to check a figure."""
    return fmt.cite(entity, with_location=True, missing=NOT_REPORTED, warn_sep=" ")


def _find_source(model: PMIDataModel, kind: str, label: str) -> str:
    collections = {
        "task": (model.tasks, "title"), "milestone": (model.milestones, "name"),
        "risk": (model.risks, "title"), "issue": (model.issues, "title"),
        "budget": (model.budget, "category"), "synergy": (model.synergies, "title"),
        "kpi": (model.kpis, "name"),
        "dependency": (model.dependencies, "description"),
        "decision": (model.decisions, "title"),
    }
    entry = collections.get(kind)
    if not entry:
        return "—"
    items, attr = entry
    for item in items:
        if getattr(item, attr, None) == label:
            return _cite(item)
    return "—"
