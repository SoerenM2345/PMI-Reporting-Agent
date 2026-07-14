"""PowerPoint generation (spec §12). python-pptx; the output is an editable .pptx.

Four audience templates, because §12.1-12.4 are genuinely different documents:

* **Steering Committee** (§12.1) — decision-oriented. Is it on track, what changed,
  what needs you, what could hurt value. Concise.
* **IMO / PMO** (§12.2) — operational. Scorecard, overdue work, dependencies, and
  crucially "missing updates and data-quality gaps": who has not reported.
* **Finance** (§12.3) — budget vs actual vs forecast, synergy target vs realized.
* **Workstream** (§12.4) — one stream's objectives, blockers, and what it needs from
  the others.

§12.5's design rules are applied throughout, and two of them do real work:

**"Use clear management-message titles."** A slide titled "Risks" tells a reader
nothing. A slide titled "Two critical risks are unmitigated; both need an owner today"
tells them what to do. Titles are written from the data, not from the section name.

**"Mark data-quality limitations."** Every deck ends with a slide saying what this
report could not do — files that failed, figures read off a screenshot, conflicts
nobody resolved. That slide exists because the alternative is a deck that looks
equally confident whether or not it is.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from app.agent.data_quality import summarize
from app.generators import charts
from app.models.pmi import (
    Audience,
    DataQualityReport,
    PMIDataModel,
    Severity,
    Status,
)

log = logging.getLogger("pmi.pptx")

GREEN = RGBColor(0x2E, 0x7D, 0x32)
DARK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x75, 0x75, 0x75)
RED = RGBColor(0xC6, 0x28, 0x28)
AMBER = RGBColor(0xF9, 0xA8, 0x25)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

RAG = {
    Severity.LOW: GREEN, Severity.MEDIUM: AMBER,
    Severity.HIGH: RGBColor(0xEF, 0x6C, 0x00), Severity.CRITICAL: RED,
}

FOOTER = ("Prototype output — requires Senior Manager review before distribution "
          "to stakeholders.")

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
MARGIN = Inches(0.6)


def generate(
    model: PMIDataModel,
    audience: Audience,
    bullets: list[str],
    out_dir: Path,
    quality: Optional[DataQualityReport] = None,
) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H

    _title(prs, model, audience)
    _executive_summary(prs, model, bullets)

    builder = {
        Audience.EXECUTIVE: _steerco_deck,
        Audience.PMO: _pmo_deck,
        Audience.FINANCE: _finance_deck,
        Audience.WORKSTREAM: _workstream_deck,
    }.get(audience, _pmo_deck)
    builder(prs, model, out_dir)

    # §12.5: "Mark data-quality limitations." Always last, always present.
    _data_quality(prs, model, quality)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"PMI_Report_{audience.value}_{date.today().isoformat()}.pptx"
    prs.save(str(path))
    log.info("wrote %s (%d slides)", path.name, len(prs.slides))
    return path


# ============================================================ §12.1 SteerCo
def _steerco_deck(prs, model: PMIDataModel, out_dir: Path) -> None:
    _overall_status(prs, model)
    _chart_slide(prs, model, out_dir, charts.workstream_progress,
                 _workstream_message(model))
    _milestones(prs, model, out_dir)
    _critical_risks(prs, model)
    _financials(prs, model)
    _decisions(prs, model)
    _next_steps(prs, model)


# ============================================================== §12.2 IMO/PMO
def _pmo_deck(prs, model: PMIDataModel, out_dir: Path) -> None:
    _workstream_scorecard(prs, model)
    _chart_slide(prs, model, out_dir, charts.tasks_by_status,
                 _task_message(model))
    _overdue(prs, model)
    _critical_risks(prs, model)
    _dependencies(prs, model)
    _missing_updates(prs, model)   # §12.2 item 9 — the whole point of a PMO deck
    _actions(prs, model)


# ============================================================= §12.3 Finance
def _finance_deck(prs, model: PMIDataModel, out_dir: Path) -> None:
    _financials(prs, model)
    _chart_slide(prs, model, out_dir, charts.budget_vs_actual, _budget_message(model))
    _budget_detail(prs, model)
    _synergies(prs, model)
    _chart_slide(prs, model, out_dir, charts.synergy_target_vs_realized,
                 _synergy_message(model))
    _financial_risks(prs, model)
    _decisions(prs, model)


# ========================================================== §12.4 Workstream
def _workstream_deck(prs, model: PMIDataModel, out_dir: Path) -> None:
    _workstream_scorecard(prs, model)
    _overdue(prs, model)
    _milestones(prs, model, out_dir)
    _critical_risks(prs, model)
    _dependencies(prs, model)
    _decisions(prs, model)
    _next_steps(prs, model)


# ================================================== management-message titles
# §12.5: "Use clear management-message titles." A title states the finding; the body
# shows the evidence. This is the Minto Pyramid rule the spec asks for, and it is the
# difference between a deck that informs and one that merely reports.
def _status_message(model: PMIDataModel) -> str:
    progress = model.overall_progress()
    unresolved = len(model.unresolved_conflicts())
    critical = len([r for r in model.critical_risks() if r.status.is_open])
    overdue = len(model.overdue_tasks())

    if unresolved:
        return (f"Integration status cannot be stated with confidence — "
                f"{unresolved} source conflict(s) remain unresolved")
    if critical:
        return (f"{critical} critical risk(s) require management attention"
                + (f"; {overdue} task(s) are overdue" if overdue else ""))
    if progress is not None and overdue == 0:
        return f"Integration is on track at {progress:.0f}% overall progress"
    if overdue:
        return f"{overdue} task(s) are overdue and need re-planning"
    return "Integration status"


def _workstream_message(model: PMIDataModel) -> str:
    silent = [w for w in model.workstreams if w.progress_percentage is None]
    behind = [w for w in model.workstreams
              if w.progress_percentage is not None and w.progress_percentage < 50]
    if silent:
        return (f"{len(silent)} workstream(s) did not report this period — "
                f"progress cannot be confirmed")
    if behind:
        return (f"{len(behind)} workstream(s) are below 50%: "
                f"{', '.join(w.name for w in behind[:3])}")
    return "All workstreams are reporting progress"


def _task_message(model: PMIDataModel) -> str:
    overdue = len(model.overdue_tasks())
    blocked = sum(1 for t in model.tasks if t.status is Status.BLOCKED)
    if overdue:
        return f"{overdue} task(s) are overdue" + (f" and {blocked} blocked" if blocked else "")
    return f"{len(model.open_tasks())} of {len(model.tasks)} tasks remain open"


def _risk_message(model: PMIDataModel) -> str:
    open_critical = [r for r in model.critical_risks() if r.status.is_open]
    unmitigated = [r for r in open_critical if not r.mitigation_action]
    if unmitigated:
        return (f"{len(unmitigated)} critical risk(s) have NO mitigation action — "
                f"an owner is needed now")
    if open_critical:
        return f"{len(open_critical)} critical risk(s) are open and mitigated"
    return "No critical risks are open"


def _budget_message(model: PMIDataModel) -> str:
    over = [b for b in model.budget if b.variance is not None and b.variance < 0]
    if not over:
        return "Integration spend is within budget"
    total = sum(abs(b.variance) for b in over)
    currency = over[0].currency
    return (f"{len(over)} budget line(s) are over budget by {total:,.0f} {currency} "
            f"in total")


def _synergy_message(model: PMIDataModel) -> str:
    targeted = [s for s in model.synergies if s.target_value]
    if not targeted:
        return "No synergy targets were reported"
    target = sum(s.target_value or 0 for s in targeted)
    realized = sum(s.realized_value or 0 for s in targeted)
    percent = realized / target * 100 if target else 0
    return (f"{percent:.0f}% of the {target:,.0f} {targeted[0].currency} synergy "
            f"target is realized")


# ================================================================== slides
def _title(prs, model: PMIDataModel, audience: Audience) -> None:
    slide = _blank(prs)
    project = model.project

    _text(slide, project.project_name, MARGIN, Inches(2.4),
          size=40, bold=True, colour=DARK)
    _text(slide, f"{_audience_label(audience)} — Integration Status Report",
          MARGIN, Inches(3.4), size=20, colour=GREEN)

    when = project.reporting_date or date.today()
    meta = [f"Reporting date: {when:%d-%m-%Y}"]
    if project.reporting_period:
        meta.append(f"Period: {project.reporting_period}")
    if project.integration_phase.value != "Unknown":
        meta.append(f"Phase: {project.integration_phase.value}")
    meta.append(f"Sources: {len(model.source_files)} file(s)")

    _text(slide, "   ·   ".join(meta), MARGIN, Inches(4.1), size=13, colour=GREY)
    _footer(slide)


def _executive_summary(prs, model: PMIDataModel, bullets: list[str]) -> None:
    slide = _blank(prs)
    _header(slide, _status_message(model), "Executive summary")

    top = Inches(1.9)
    for bullet in bullets[:6]:
        box = slide.shapes.add_textbox(MARGIN, top, SLIDE_W - Inches(1.2), Inches(0.6))
        frame = box.text_frame
        frame.word_wrap = True
        run = frame.paragraphs[0].add_run()
        run.text = f"•  {bullet}"
        run.font.size = Pt(15)
        run.font.color.rgb = DARK
        top += Inches(0.72)

    _footer(slide)


def _overall_status(prs, model: PMIDataModel) -> None:
    """The SteerCo's four questions, answered as figures (§12.1)."""
    slide = _blank(prs)

    reporting = len([w for w in model.workstreams if w.progress_percentage is not None])
    headline = (
        f"Status at a glance — {reporting} of {len(model.workstreams)} workstream(s) "
        f"reporting"
        if model.workstreams else "Status at a glance"
    )
    _header(slide, headline, "Overall integration status")

    progress = model.overall_progress()
    day_1 = [t for t in model.tasks if t.is_day_1_critical]
    day_1_done = sum(1 for t in day_1 if t.status is Status.COMPLETED)

    tiles = [
        ("Overall progress",
         f"{progress:.0f}%" if progress is not None else "Not Reported",
         GREEN if (progress or 0) >= 70 else AMBER),
        ("Open critical risks",
         str(len([r for r in model.critical_risks() if r.status.is_open])),
         RED if model.critical_risks() else GREEN),
        ("Overdue tasks", str(len(model.overdue_tasks())),
         RED if model.overdue_tasks() else GREEN),
        ("Day 1 readiness",
         f"{day_1_done}/{len(day_1)}" if day_1 else "Not Reported",
         GREEN if day_1 and day_1_done == len(day_1) else AMBER),
        ("Decisions required",
         str(len([d for d in model.decisions if d.status.is_open])), AMBER),
        ("Unresolved conflicts", str(len(model.unresolved_conflicts())),
         RED if model.unresolved_conflicts() else GREEN),
    ]

    for index, (label, value, colour) in enumerate(tiles):
        left = MARGIN + Inches(2.1) * (index % 3)
        top = Inches(2.1) + Inches(1.9) * (index // 3)
        _tile(slide, label, value, colour, left, top)

    _footer(slide)


def _workstream_scorecard(prs, model: PMIDataModel) -> None:
    if not model.workstreams:
        return
    rows = [
        [
            w.name,
            w.lead or "—",
            w.status.value.replace("_", " ").title(),
            f"{w.progress_percentage:.0f}%"
            if w.progress_percentage is not None else "Not Reported",
            str(len(w.open_risks)),
            str(len(w.upcoming_milestones)),
        ]
        for w in model.workstreams
    ]
    _table(prs, _workstream_message(model), "Workstream scorecard",
           ["Workstream", "Lead", "Status", "Progress", "Open risks", "Milestones"],
           rows)


def _critical_risks(prs, model: PMIDataModel) -> None:
    risks = [r for r in model.risks if r.status.is_open]
    risks.sort(key=lambda r: (r.risk_score or 0), reverse=True)
    if not risks:
        return

    rows = [
        [
            r.risk_id,
            r.title,
            r.rating.value.title(),
            str(r.risk_score) if r.risk_score is not None else "Not scored",
            r.owner or "⚠ NO OWNER",
            (r.mitigation_action or "⚠ NO MITIGATION")[:60],
            _cite(r),
        ]
        for r in risks[:12]
    ]
    _table(prs, _risk_message(model), "Critical risks and issues",
           ["ID", "Risk", "Rating", "Score", "Owner", "Mitigation", "Source"],
           rows, note=_more(len(risks), 12))


def _milestones(prs, model: PMIDataModel, out_dir: Path) -> None:
    if not model.milestones:
        return

    late = [m for m in model.milestones if (m.delay_days or 0) > 0]
    title = (f"{len(late)} milestone(s) have slipped"
             if late else "All milestones are on plan")

    rows = [
        [
            m.name,
            _d(m.planned_date),
            _d(m.forecast_date or m.actual_date),
            f"+{m.delay_days}d" if (m.delay_days or 0) > 0 else "on plan",
            m.status.value.replace("_", " ").title(),
            m.owner or "—",
        ]
        for m in sorted(model.milestones,
                        key=lambda m: (m.delay_days or 0), reverse=True)[:12]
    ]
    _table(prs, title, "Key milestones",
           ["Milestone", "Planned", "Forecast/Actual", "Delay", "Status", "Owner"],
           rows)

    _chart_slide(prs, model, out_dir, charts.milestone_timeline,
                 "Milestone timeline — planned vs forecast")


def _overdue(prs, model: PMIDataModel) -> None:
    overdue = model.overdue_tasks()
    if not overdue:
        return

    rows = [
        [
            t.task_id, t.title, t.owner or "⚠ NO OWNER", _d(t.due_date),
            t.status.value.replace("_", " ").title(), t.workstream or "—",
        ]
        for t in sorted(overdue, key=lambda t: t.due_date or date.max)[:15]
    ]
    _table(prs, f"{len(overdue)} task(s) are overdue", "Overdue activities",
           ["ID", "Task", "Owner", "Was due", "Status", "Workstream"],
           rows, note=_more(len(overdue), 15))


def _dependencies(prs, model: PMIDataModel) -> None:
    if not model.dependencies:
        return
    rows = [
        [
            d.description[:60],
            d.providing_workstream or "—",
            d.receiving_workstream or "—",
            _d(d.required_date),
            d.status.value.replace("_", " ").title(),
            d.owner or "⚠ NO OWNER",
        ]
        for d in model.dependencies[:12]
    ]
    _table(prs, "Cross-workstream dependencies", "Dependencies",
           ["Dependency", "From", "To", "Required by", "Status", "Owner"], rows)


def _missing_updates(prs, model: PMIDataModel) -> None:
    """§12.2 item 9: 'Missing updates and data-quality gaps'.

    The most valuable slide in an IMO deck, and the one no tracker produces: who has
    NOT reported. A workstream that says nothing looks identical to one that is fine.
    """
    silent = [w for w in model.workstreams if w.progress_percentage is None]
    gaps = [i for i in model.validation_issues if i.family == "completeness"]
    if not silent and not gaps:
        return

    slide = _blank(prs)
    _header(slide,
            f"{len(silent)} workstream(s) did not report; {len(gaps)} data gap(s) found",
            "Missing updates and data-quality gaps")

    top = Inches(1.9)
    if silent:
        _text(slide, "No update received from:", MARGIN, top, size=14, bold=True)
        top += Inches(0.4)
        for workstream in silent[:6]:
            _text(slide, f"•  {workstream.name}", Inches(0.9), top, size=13, colour=RED)
            top += Inches(0.32)
        top += Inches(0.2)

    if gaps:
        _text(slide, "Data-quality gaps:", MARGIN, top, size=14, bold=True)
        top += Inches(0.4)
        for issue in gaps[:8]:
            _text(slide, f"•  {issue.message[:110]}", Inches(0.9), top,
                  size=12, colour=DARK)
            top += Inches(0.32)

    _footer(slide)


def _financials(prs, model: PMIDataModel) -> None:
    if not model.budget and not model.synergies:
        return

    slide = _blank(prs)
    _header(slide, _budget_message(model), "Synergy and financial status")

    budget = sum(b.budget or 0 for b in model.budget)
    actual = sum(b.actual or 0 for b in model.budget)
    forecast = sum(b.forecast or 0 for b in model.budget)
    target = sum(s.target_value or 0 for s in model.synergies)
    realized = sum(s.realized_value or 0 for s in model.synergies)
    currency = (model.budget[0].currency if model.budget
                else model.synergies[0].currency if model.synergies else "EUR")

    tiles = [
        ("Budget", f"{budget:,.0f}" if budget else "Not Reported", GREEN),
        ("Actual", f"{actual:,.0f}" if actual else "Not Reported", DARK),
        ("Forecast", f"{forecast:,.0f}" if forecast else "Not Reported",
         RED if forecast > budget else GREEN),
        ("Synergy target", f"{target:,.0f}" if target else "Not Reported", GREEN),
        ("Synergy realized", f"{realized:,.0f}" if realized else "Not Reported",
         GREEN if realized else AMBER),
        ("Currency", currency, GREY),
    ]
    for index, (label, value, colour) in enumerate(tiles):
        left = MARGIN + Inches(2.1) * (index % 3)
        top = Inches(2.1) + Inches(1.9) * (index // 3)
        _tile(slide, label, value, colour, left, top)

    _footer(slide)


def _budget_detail(prs, model: PMIDataModel) -> None:
    if not model.budget:
        return
    rows = [
        [
            b.category,
            _n(b.budget), _n(b.actual), _n(b.committed), _n(b.forecast),
            _n(b.variance),
            f"{b.variance_percentage:.1f}%" if b.variance_percentage is not None else "—",
        ]
        for b in model.budget
    ]
    _table(prs, _budget_message(model), "Budget vs actual and forecast",
           ["Category", "Budget", "Actual", "Committed", "Forecast", "Variance", "%"],
           rows)


def _synergies(prs, model: PMIDataModel) -> None:
    if not model.synergies:
        return
    rows = [
        [
            s.title, s.synergy_type.value,
            _n(s.target_value), _n(s.realized_value), _n(s.forecast_value),
            _n(s.remaining_value),
            _d(s.planned_realization_date),
            s.confidence_level or "—",
        ]
        for s in model.synergies
    ]
    _table(prs, _synergy_message(model), "Synergy target vs realized",
           ["Synergy", "Type", "Target", "Realized", "Forecast", "Remaining",
            "Realization", "Confidence"],
           rows)


def _financial_risks(prs, model: PMIDataModel) -> None:
    from app.models.pmi import RiskCategory

    risks = [
        r for r in model.risks
        if r.status.is_open
        and (r.category in (RiskCategory.FINANCIAL, RiskCategory.SYNERGY)
             or "cost" in r.title.casefold() or "budget" in r.title.casefold())
    ]
    if not risks:
        return
    rows = [
        [r.risk_id, r.title, r.rating.value.title(), r.owner or "⚠ NO OWNER",
         (r.mitigation_action or "⚠ NO MITIGATION")[:60]]
        for r in risks[:10]
    ]
    _table(prs, f"{len(risks)} financial risk(s) are open", "Financial risks",
           ["ID", "Risk", "Rating", "Owner", "Mitigation"], rows)


def _decisions(prs, model: PMIDataModel) -> None:
    decisions = [d for d in model.decisions if d.status.is_open]

    if not decisions:
        # Render the slide anyway, empty and explicit. "No decisions are pending" is
        # information a Steering Committee needs; a *missing* slide is ambiguous —
        # the reader cannot tell whether there are none or whether we failed to look.
        _empty_slide(
            prs,
            "No decisions are currently pending Steering Committee approval",
            "Decisions required",
            "No open decisions were found in the uploaded files. If a decision is "
            "expected this period, it is not recorded in any source provided.",
        )
        return

    rows = [
        [
            d.title,
            d.decision_body.value,
            d.decision_owner or "⚠ NO OWNER",
            _d(d.decision_deadline) if d.decision_deadline else "⚠ NO DEADLINE",
            d.recommended_option or "—",
            (d.impact or "—")[:50],
        ]
        for d in decisions[:10]
    ]
    _table(prs, f"{len(decisions)} decision(s) are required", "Decisions required",
           ["Decision", "Body", "Owner", "Deadline", "Recommendation", "Impact"], rows)


def _actions(prs, model: PMIDataModel) -> None:
    upcoming = [t for t in model.tasks if t.status.is_open and t.due_date]
    upcoming.sort(key=lambda t: t.due_date)
    if not upcoming:
        return
    rows = [
        [t.title, t.owner or "⚠ NO OWNER", _d(t.due_date), t.workstream or "—"]
        for t in upcoming[:12]
    ]
    _table(prs, "Actions, owners and deadlines", "Next actions",
           ["Action", "Owner", "Due", "Workstream"], rows)


def _next_steps(prs, model: PMIDataModel) -> None:
    upcoming = [
        m for m in model.milestones
        if m.status.is_open and (m.forecast_date or m.planned_date)
    ]
    upcoming.sort(key=lambda m: m.forecast_date or m.planned_date)
    if not upcoming:
        return
    rows = [
        [m.name, _d(m.forecast_date or m.planned_date), m.owner or "—",
         m.workstream or "—"]
        for m in upcoming[:10]
    ]
    _table(prs, "Upcoming milestones before the next Steering Committee",
           "Next steps", ["Milestone", "Due", "Owner", "Workstream"], rows)


def _data_quality(prs, model: PMIDataModel, report: Optional[DataQualityReport]) -> None:
    """§12.5: 'Mark data-quality limitations.'

    The slide that keeps the rest of the deck honest. Without it, a report built from
    one clean tracker and a report built from three contradictory files and a blurry
    photo look exactly the same.
    """
    slide = _blank(prs)

    unresolved = model.unresolved_conflicts()
    title = (
        f"⚠ {len(unresolved)} unresolved source conflict(s) — figures are not agreed"
        if unresolved else
        "Data quality and limitations"
    )
    _header(slide, title, "How this report was produced")

    lines: list[str] = summarize(report) if report else []
    low = model.low_confidence_items()
    if low:
        lines.append(
            "Read from images/scans at low confidence: "
            + "; ".join(f"{label} ({confidence:.0%})" for _k, label, confidence in low[:4])
        )

    top = Inches(1.9)
    for line in lines[:9]:
        colour = RED if ("UNRESOLVED" in line or "could NOT" in line or "⚠" in line) else DARK
        box = slide.shapes.add_textbox(MARGIN, top, SLIDE_W - Inches(1.2), Inches(0.5))
        frame = box.text_frame
        frame.word_wrap = True
        run = frame.paragraphs[0].add_run()
        run.text = f"•  {line}"
        run.font.size = Pt(13)
        run.font.color.rgb = colour
        top += Inches(0.5)

    _footer(slide)


# =================================================================== plumbing
def _chart_slide(prs, model, out_dir: Path, builder, title: str) -> None:
    try:
        path = builder(model, out_dir)
    except Exception as exc:
        log.warning("chart %s failed: %s", builder.__name__, exc)
        return
    if path is None:
        return

    slide = _blank(prs)
    _header(slide, title, "")
    slide.shapes.add_picture(
        str(path), Inches(1.9), Inches(1.7), height=Inches(5.2)
    )
    _footer(slide)


def _table(prs, title: str, subtitle: str, headers: list[str],
           rows: list[list[str]], note: str = "") -> None:
    if not rows:
        return

    slide = _blank(prs)
    _header(slide, title, subtitle)

    shape = slide.shapes.add_table(
        len(rows) + 1, len(headers),
        MARGIN, Inches(1.85),
        SLIDE_W - Inches(1.2), Inches(0.32) * (len(rows) + 1),
    )
    table = shape.table

    for column, heading in enumerate(headers):
        cell = table.cell(0, column)
        cell.text = heading
        for paragraph in cell.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(11)
                run.font.bold = True
                run.font.color.rgb = WHITE
        cell.fill.solid()
        cell.fill.fore_color.rgb = GREEN

    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = str(value)
            warn = str(value).startswith("⚠")
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(10)
                    run.font.color.rgb = RED if warn else DARK
                    run.font.bold = warn

    if note:
        _text(slide, note, MARGIN, SLIDE_H - Inches(0.95), size=10, colour=GREY)

    _footer(slide)


def _empty_slide(prs, title: str, subtitle: str, explanation: str) -> None:
    """A section with nothing in it, stated rather than skipped."""
    slide = _blank(prs)
    _header(slide, title, subtitle)

    box = slide.shapes.add_textbox(MARGIN, Inches(2.2), SLIDE_W - Inches(1.2), Inches(1))
    frame = box.text_frame
    frame.word_wrap = True
    run = frame.paragraphs[0].add_run()
    run.text = explanation
    run.font.size = Pt(14)
    run.font.color.rgb = GREY

    _footer(slide)


def _tile(slide, label: str, value: str, colour, left, top) -> None:
    box = slide.shapes.add_textbox(left, top, Inches(1.95), Inches(1.6))
    frame = box.text_frame
    frame.word_wrap = True

    run = frame.paragraphs[0].add_run()
    run.text = label
    run.font.size = Pt(11)
    run.font.color.rgb = GREY

    paragraph = frame.add_paragraph()
    run = paragraph.add_run()
    run.text = value
    run.font.size = Pt(28)
    run.font.bold = True
    run.font.color.rgb = colour


def _blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _header(slide, title: str, subtitle: str) -> None:
    _text(slide, title, MARGIN, Inches(0.45), size=22, bold=True, colour=DARK,
          width=SLIDE_W - Inches(1.2))
    if subtitle:
        _text(slide, subtitle, MARGIN, Inches(1.15), size=13, colour=GREEN)


def _footer(slide) -> None:
    _text(slide, FOOTER, MARGIN, SLIDE_H - Inches(0.5), size=9, colour=GREY,
          width=SLIDE_W - Inches(1.2))


def _text(slide, text: str, left, top, *, size: int, bold: bool = False,
          colour=DARK, width=None):
    box = slide.shapes.add_textbox(
        left, top, width or (SLIDE_W - Inches(1.2)), Inches(0.5)
    )
    frame = box.text_frame
    frame.word_wrap = True
    run = frame.paragraphs[0].add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = colour
    return box


def _audience_label(audience: Audience) -> str:
    return {
        Audience.EXECUTIVE: "Steering Committee",
        Audience.PMO: "IMO / PMO",
        Audience.FINANCE: "Finance",
        Audience.WORKSTREAM: "Workstream",
    }[audience]


def _n(value) -> str:
    if value is None:
        return "Not Reported"
    return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:g}"


def _d(value) -> str:
    """§7: presented DD-MM-YYYY; stored as a date."""
    return f"{value:%d-%m-%Y}" if value else "—"


def _cite(entity) -> str:
    ref = entity.primary_source
    if ref is None:
        return "—"
    if ref.is_low_confidence:
        return f"{ref.file_name} ⚠{ref.extraction_confidence:.0%}"
    return ref.file_name


def _more(total: int, shown: int) -> str:
    return (f"Showing {shown} of {total}. The full list is in the Excel dashboard."
            if total > shown else "")
