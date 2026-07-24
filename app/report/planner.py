"""Turn a `PMIDataModel` into a `ReportContent`.

This is where the editorial judgement lives that used to be spread through
`pptx_report.py`: which sections a given audience gets, in what order, what each
one is titled, and which rows are worth showing. §12.1-12.4 are genuinely
different documents — a Steering Committee wants decisions, an IMO wants overdue
work — so the deck template *is* the plan.

Two rules shape everything below:

* **Sections are planned, not rendered.** Nothing here knows about slides,
  sheets, points or colours. A section that says "these twelve risks, worst
  first, titled with the finding" renders as a slide, a table in a document, or
  a block of markdown in the preview, without the plan changing.

* **Every figure comes from the fact table or from the model directly.** The
  planner does arithmetic in Python or not at all (§11). Nothing here asks a
  model for a number.

The workbook is planned too, but differently: §13 wants ten sheets regardless of
audience, so those sections carry `narrative_order=None` and are skipped by
`ReportContent.narrative()`. One structure, two projections.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.models.pmi import Audience, DataQualityReport, PMIDataModel, Status
from app.report import format as fmt
from app.report import messages
from app.report.content import (
    Bullet,
    BulletsBlock,
    Cell,
    ChartBlock,
    Column,
    ContentProvenance,
    EntityQuery,
    ProseBlock,
    ReportContent,
    Section,
    TableBlock,
    Tile,
    TilesBlock,
)
from app.report.facts import build_facts

ROW_LIMIT = 12

FOOTER = ("Prototype output — requires Senior Manager review before distribution "
          "to stakeholders.")

AUDIENCE_LABEL = {
    Audience.EXECUTIVE: "Steering Committee",
    Audience.PMO: "IMO / PMO",
    Audience.FINANCE: "Finance",
    Audience.WORKSTREAM: "Workstream",
}

#: §12.1-12.4. The order *is* the deck.
DECKS: dict[Audience, list[str]] = {
    Audience.EXECUTIVE: [
        "status.overall", "chart.workstream_progress", "milestones",
        "risks.critical", "finance.summary", "decisions", "next_steps",
    ],
    Audience.PMO: [
        "workstream.scorecard", "chart.tasks_by_status", "tasks.overdue",
        "risks.critical", "dependencies", "pmo.missing_updates", "actions",
    ],
    Audience.FINANCE: [
        "finance.summary", "chart.budget_vs_actual", "finance.budget_detail",
        "finance.synergies", "chart.synergy_target_vs_realized",
        "finance.risks", "decisions",
    ],
    Audience.WORKSTREAM: [
        "workstream.scorecard", "tasks.overdue", "milestones", "risks.critical",
        "dependencies", "decisions", "next_steps",
    ],
}


def plan(
    model: PMIDataModel,
    audience: Audience,
    *,
    session_id: str = "",
    topic: str = "status",
    bullets: Optional[list[str]] = None,
    quality: Optional[DataQualityReport] = None,
    fingerprint: str = "",
) -> ReportContent:
    """The report, as content. Pure: no disk, no network, no LLM."""
    facts = build_facts(model, quality)
    when = model.project.reporting_date or date.today()

    sections: list[Section] = []

    # Slide 2 / the opening of every format. Always first, always present.
    sections.append(_executive_summary(model, bullets or []))

    available = {
        "status.overall": lambda: _status_overall(model),
        "workstream.scorecard": lambda: _workstream_scorecard(model),
        "risks.critical": lambda: _critical_risks(model),
        "milestones": lambda: _milestones(model),
        "tasks.overdue": lambda: _overdue(model),
        "dependencies": lambda: _dependencies(model),
        "decisions": lambda: _decisions(model),
        "finance.summary": lambda: _finance_summary(model),
        "finance.budget_detail": lambda: _budget_detail(model),
        "finance.synergies": lambda: _synergies(model),
        "finance.risks": lambda: _financial_risks(model),
        "pmo.missing_updates": lambda: _missing_updates(model),
        "actions": lambda: _actions(model),
        "next_steps": lambda: _next_steps(model),
    }

    order = 2
    for section_id in DECKS.get(audience, DECKS[Audience.PMO]):
        if section_id.startswith("chart."):
            section = _chart_section(section_id, model)
        else:
            section = available[section_id]()
        if section is None:
            continue
        section.narrative_order = order
        sections.append(section)
        order += 1

    # §12.5: "Mark data-quality limitations." Always last, always present — the
    # alternative is a deck that looks equally confident whether or not it is.
    limitations = _limitations(model, quality)
    limitations.narrative_order = order
    sections.append(limitations)

    return ReportContent(
        session_id=session_id,
        audience=audience,
        topic=topic,
        title=model.project.project_name,
        subtitle=f"{AUDIENCE_LABEL.get(audience, 'Report')} — {when:%d-%m-%Y}",
        meta_line=[f"Reporting date: {when:%d-%m-%Y}",
                   f"Sources: {len(model.source_files)} file(s)"],
        footer=FOOTER,
        facts=facts,
        sections=sections,
        analysis_fingerprint=fingerprint,
        provenance=ContentProvenance(created_by="planner"),
    )


# ============================================================ section builders
def _executive_summary(model: PMIDataModel, bullets: list[str]) -> Section:
    return Section(
        section_id="summary.executive",
        label="Executive summary",
        headline=messages.status_message(model),
        narrative_order=1,
        blocks=[BulletsBlock(
            block_id="summary.bullets",
            items=[Bullet(text=b) for b in bullets],
        )],
        # Says what is true — that there is no summary — without diagnosing why.
        # It previously asserted "the semantic layer was unavailable", which was
        # a guess, and a wrong one: the usual cause was a caller that never
        # asked for bullets at all. A report that misreports its own limitations
        # sends the reader to debug the wrong thing, which is worse than a blank
        # section.
        empty_explanation=(
            None if bullets else
            "No executive summary was produced for this report."
        ),
    )


def _status_overall(model: PMIDataModel) -> Section:
    """§12.1's four questions, answered as figures."""
    return Section(
        section_id="status.overall",
        label="Overall integration status",
        headline=messages.status_at_a_glance(model),
        blocks=[TilesBlock(block_id="status.tiles", tiles=[
            Tile(label="Overall progress", fact_key="progress.overall",
                 emphasis=_progress_emphasis(model)),
            Tile(label="Open critical risks", fact_key="risk.open_critical",
                 emphasis="bad" if model.critical_risks() else "good"),
            Tile(label="Overdue tasks", fact_key="tasks.overdue",
                 emphasis="bad" if model.overdue_tasks() else "good"),
            Tile(label="Day 1 readiness", fact_key="day1.readiness",
                 emphasis=_day1_emphasis(model)),
            Tile(label="Decisions required", fact_key="decision.open",
                 emphasis="warn"),
            Tile(label="Unresolved conflicts", fact_key="conflict.unresolved",
                 emphasis="bad" if model.unresolved_conflicts() else "good"),
        ])],
    )


def _workstream_scorecard(model: PMIDataModel) -> Optional[Section]:
    if not model.workstreams:
        return None
    rows = [
        _row(
            w.name,
            w.lead or fmt.DASH,
            w.status.value.replace("_", " ").title(),
            f"{w.progress_percentage:.0f}%"
            if w.progress_percentage is not None else fmt.NOT_REPORTED,
            str(len(w.open_risks)),
            str(len(w.upcoming_milestones)),
        )
        for w in model.workstreams
    ]
    return Section(
        section_id="workstream.scorecard",
        label="Workstream scorecard",
        headline=messages.workstream_message(model),
        blocks=[TableBlock(
            block_id="workstream.table",
            columns=_cols(["Workstream", "Lead", "Status", "Progress",
                           "Open risks", "Milestones"],
                          percent={3}, rag={2}),
            rows=rows,
        )],
    )


def _critical_risks(model: PMIDataModel) -> Optional[Section]:
    risks = sorted(
        [r for r in model.risks if r.status.is_open],
        key=lambda r: (r.risk_score or 0), reverse=True,
    )
    if not risks:
        return None

    rows = [
        _row(
            r.risk_id, r.title, r.rating.value.title(),
            str(r.risk_score) if r.risk_score is not None else "Not scored",
            # An unowned critical risk is the finding, not a blank cell.
            r.owner or "⚠ NO OWNER",
            (r.mitigation_action or "⚠ NO MITIGATION")[:60],
            fmt.cite(r, missing=fmt.DASH),
        )
        for r in risks[:ROW_LIMIT]
    ]
    return Section(
        section_id="risks.critical",
        label="Critical risks and issues",
        headline=messages.risk_message(model),
        blocks=[TableBlock(
            block_id="risks.table",
            columns=_cols(["ID", "Risk", "Rating", "Score", "Owner",
                           "Mitigation", "Source"], rag={2}),
            rows=rows,
            row_limit=ROW_LIMIT,
            note=_more(len(risks), ROW_LIMIT),
        )],
    )


def _milestones(model: PMIDataModel) -> Optional[Section]:
    if not model.milestones:
        return None
    rows = [
        _row(
            m.name, fmt.date_str(m.planned_date, missing=fmt.DASH),
            fmt.date_str(m.forecast_date or m.actual_date, missing=fmt.DASH),
            f"+{m.delay_days}d" if (m.delay_days or 0) > 0 else "on plan",
            m.status.value.replace("_", " ").title(),
            m.owner or fmt.DASH,
        )
        for m in sorted(model.milestones,
                        key=lambda m: (m.delay_days or 0), reverse=True)[:ROW_LIMIT]
    ]
    return Section(
        section_id="milestones",
        label="Key milestones",
        headline=messages.milestone_message(model),
        blocks=[TableBlock(
            block_id="milestones.table",
            columns=_cols(["Milestone", "Planned", "Forecast/Actual", "Delay",
                           "Status", "Owner"], date={1, 2}),
            rows=rows,
            row_limit=ROW_LIMIT,
        )],
    )


def _overdue(model: PMIDataModel) -> Optional[Section]:
    overdue = model.overdue_tasks()
    if not overdue:
        return None
    rows = [
        _row(t.task_id, t.title, t.workstream or fmt.DASH,
             t.owner or "⚠ UNASSIGNED",
             fmt.date_str(t.due_date, missing=fmt.DASH),
             f"{t.days_overdue}d" if getattr(t, "days_overdue", None) else fmt.DASH,
             t.status.value.replace("_", " ").title())
        for t in overdue[:ROW_LIMIT]
    ]
    return Section(
        section_id="tasks.overdue",
        label="Overdue activities",
        headline=messages.task_message(model),
        blocks=[TableBlock(
            block_id="overdue.table",
            columns=_cols(["ID", "Task", "Workstream", "Owner", "Due",
                           "Overdue", "Status"], date={4}),
            rows=rows,
            row_limit=ROW_LIMIT,
            note=_more(len(overdue), ROW_LIMIT),
        )],
    )


def _dependencies(model: PMIDataModel) -> Optional[Section]:
    if not model.dependencies:
        return None
    rows = [
        _row(d.description[:70], d.from_workstream or fmt.DASH,
             d.to_workstream or fmt.DASH, d.owner or fmt.DASH,
             fmt.date_str(d.required_date, missing=fmt.DASH),
             d.status.value.replace("_", " ").title())
        for d in model.dependencies[:ROW_LIMIT]
    ]
    return Section(
        section_id="dependencies",
        label="Cross-workstream dependencies",
        headline=f"{len(model.dependencies)} dependency(ies) are being tracked",
        blocks=[TableBlock(
            block_id="dependencies.table",
            columns=_cols(["Dependency", "From", "To", "Owner", "Needed by",
                           "Status"], date={4}),
            rows=rows,
            row_limit=ROW_LIMIT,
            note=_more(len(model.dependencies), ROW_LIMIT),
        )],
    )


def _decisions(model: PMIDataModel) -> Section:
    """Note this section is emitted even when there is nothing to say.

    "No decisions are pending" is information a Steering Committee needs. A
    *missing* section is ambiguous — the reader cannot tell whether there were
    none or whether we failed to look — so the empty case is stated outright.
    """
    decisions = [d for d in model.decisions if d.status.is_open]

    if not decisions:
        return Section(
            section_id="decisions",
            label="Decisions required",
            headline="No decisions are currently pending Steering Committee approval",
            blocks=[],
            empty_explanation=(
                "No open decisions were found in the uploaded files. If a "
                "decision is expected this period, it is not recorded in any "
                "source provided."
            ),
        )

    rows = [
        _row(
            d.title,
            d.decision_body.value,
            d.decision_owner or "⚠ NO OWNER",
            fmt.date_str(d.decision_deadline, missing=fmt.DASH)
            if d.decision_deadline else "⚠ NO DEADLINE",
            d.recommended_option or fmt.DASH,
            (d.impact or fmt.DASH)[:50],
        )
        for d in decisions[:10]
    ]
    return Section(
        section_id="decisions",
        label="Decisions required",
        headline=f"{len(decisions)} decision(s) are required",
        blocks=[TableBlock(
            block_id="decisions.table",
            columns=_cols(["Decision", "Body", "Owner", "Deadline",
                           "Recommendation", "Impact"], date={3}),
            rows=rows,
            row_limit=10,
        )],
    )


def _finance_summary(model: PMIDataModel) -> Optional[Section]:
    if not model.budget and not model.synergies:
        return None

    budget = sum(b.budget or 0 for b in model.budget)
    forecast = sum(b.forecast or 0 for b in model.budget)
    realized = sum(s.realized_value or 0 for s in model.synergies)
    currency = (model.budget[0].currency if model.budget
                else model.synergies[0].currency if model.synergies else "EUR")

    return Section(
        section_id="finance.summary",
        # §20.12.6 expects a "financial" section; this wording is what the
        # acceptance scenario looks for, so it stays exactly as it was.
        label="Synergy and financial status",
        headline=messages.budget_message(model),
        blocks=[TilesBlock(block_id="finance.tiles", tiles=[
            Tile(label="Budget", fact_key="budget.total", emphasis="good"),
            Tile(label="Actual", fact_key="budget.actual"),
            Tile(label="Forecast", fact_key="budget.forecast",
                 emphasis="bad" if forecast > budget else "good"),
            Tile(label="Synergy target", fact_key="synergy.target",
                 emphasis="good"),
            Tile(label="Synergy realized", fact_key="synergy.realized",
                 emphasis="good" if realized else "warn"),
            # A literal rather than a fact: the currency is a unit, not a figure.
            Tile(label="Currency", value=currency, emphasis="muted"),
        ])],
    )


def _budget_detail(model: PMIDataModel) -> Optional[Section]:
    if not model.budget:
        return None
    rows = [
        _row(b.category, fmt.num(b.budget), fmt.num(b.actual),
             fmt.num(b.forecast), fmt.num(b.variance),
             f"{b.variance_percentage:.0f}%"
             if b.variance_percentage is not None else fmt.NOT_REPORTED,
             fmt.cite(b, missing=fmt.DASH))
        for b in model.budget[:ROW_LIMIT]
    ]
    return Section(
        section_id="finance.budget_detail",
        label="Budget detail",
        headline=messages.budget_message(model),
        blocks=[TableBlock(
            block_id="budget.table",
            columns=_cols(["Category", "Budget", "Actual", "Forecast",
                           "Variance", "Variance %", "Source"],
                          currency={1, 2, 3, 4}, percent={5}, negative={4, 5}),
            rows=rows,
            row_limit=ROW_LIMIT,
            note=_more(len(model.budget), ROW_LIMIT),
        )],
    )


def _synergies(model: PMIDataModel) -> Optional[Section]:
    if not model.synergies:
        return None
    rows = [
        _row(s.title[:60], s.synergy_type.value.title()
             if getattr(s, "synergy_type", None) else fmt.DASH,
             fmt.num(s.target_value), fmt.num(s.realized_value),
             fmt.num(s.forecast_value), fmt.num(s.remaining_value),
             s.confidence_level or fmt.NOT_REPORTED)
        for s in model.synergies[:ROW_LIMIT]
    ]
    return Section(
        section_id="finance.synergies",
        label="Synergy realization",
        headline=messages.synergy_message(model),
        blocks=[TableBlock(
            block_id="synergies.table",
            columns=_cols(["Synergy", "Type", "Target", "Realized", "Forecast",
                           "Remaining", "Confidence"], currency={2, 3, 4, 5}),
            rows=rows,
            row_limit=ROW_LIMIT,
            note=_more(len(model.synergies), ROW_LIMIT),
        )],
    )


def _financial_risks(model: PMIDataModel) -> Optional[Section]:
    """Risks with a euro sign on them — what Finance is actually asking about."""
    financial = [
        r for r in model.risks
        if r.status.is_open and (
            getattr(r, "financial_impact", None)
            or "cost" in (r.title or "").lower()
            or "budget" in (r.title or "").lower()
        )
    ]
    if not financial:
        return None
    rows = [
        _row(r.risk_id, r.title[:60], r.rating.value.title(),
             fmt.num(getattr(r, "financial_impact", None)),
             r.owner or "⚠ NO OWNER")
        for r in financial[:ROW_LIMIT]
    ]
    return Section(
        section_id="finance.risks",
        label="Risks with financial impact",
        headline=f"{len(financial)} open risk(s) carry a financial impact",
        blocks=[TableBlock(
            block_id="finance.risks.table",
            columns=_cols(["ID", "Risk", "Rating", "Impact", "Owner"],
                          currency={3}, rag={2}),
            rows=rows,
            row_limit=ROW_LIMIT,
        )],
    )


def _missing_updates(model: PMIDataModel) -> Section:
    """§12.2 item 9 — the whole point of a PMO deck: who has not reported."""
    silent = [w.name for w in model.workstreams if w.progress_percentage is None]
    unowned = [t.title for t in model.tasks if not t.owner]

    blocks = []
    if silent:
        blocks.append(BulletsBlock(
            block_id="missing.workstreams",
            title="Workstreams that did not report",
            items=[Bullet(text=name, emphasis="warn") for name in silent[:10]],
        ))
    if unowned:
        blocks.append(BulletsBlock(
            block_id="missing.owners",
            title="Activities with no owner",
            items=[Bullet(text=title, emphasis="warn") for title in unowned[:10]],
        ))

    return Section(
        section_id="pmo.missing_updates",
        label="Missing updates and data-quality gaps",
        headline=(f"{len(silent)} workstream(s) and {len(unowned)} activity(ies) "
                  f"are missing information"
                  if (silent or unowned) else "Every workstream reported"),
        blocks=blocks,
        empty_explanation=(None if blocks else
                           "Nothing is missing — every workstream reported and "
                           "every activity has an owner."),
    )


def _actions(model: PMIDataModel) -> Optional[Section]:
    open_tasks = [t for t in model.open_tasks() if t.due_date]
    if not open_tasks:
        return None
    upcoming = sorted(open_tasks, key=lambda t: t.due_date)[:ROW_LIMIT]
    return Section(
        section_id="actions",
        label="Actions and owners",
        headline=messages.task_message(model),
        blocks=[TableBlock(
            block_id="actions.table",
            columns=_cols(["Task", "Owner", "Due", "Status"], date={2}),
            rows=[
                _row(t.title[:70], t.owner or "⚠ UNASSIGNED",
                     fmt.date_str(t.due_date, missing=fmt.DASH),
                     t.status.value.replace("_", " ").title())
                for t in upcoming
            ],
            row_limit=ROW_LIMIT,
        )],
    )


def _next_steps(model: PMIDataModel) -> Section:
    items: list[Bullet] = []
    for risk in [r for r in model.critical_risks() if r.status.is_open][:3]:
        if not risk.mitigation_action:
            items.append(Bullet(
                text=f"Assign a mitigation owner for “{risk.title}”",
                emphasis="bad",
            ))
    for conflict in model.unresolved_conflicts()[:3]:
        items.append(Bullet(
            text=f"Agree the correct value for {conflict.entity_key} "
                 f"({conflict.field})",
            emphasis="warn",
        ))
    overdue = model.overdue_tasks()
    if overdue:
        items.append(Bullet(
            text=f"Re-plan {len(overdue)} overdue activity(ies)", emphasis="warn"
        ))

    return Section(
        section_id="next_steps",
        label="Next steps",
        headline=("Actions required before the next reporting cycle" if items
                  else "No escalations are outstanding"),
        blocks=[BulletsBlock(block_id="next_steps.bullets", items=items)],
        empty_explanation=(None if items else
                           "Nothing requires escalation this period."),
    )


def _chart_section(section_id: str, model: PMIDataModel) -> Section:
    builder = section_id.split(".", 1)[1]
    headline = {
        "workstream_progress": messages.workstream_message,
        "tasks_by_status": messages.task_message,
        "budget_vs_actual": messages.budget_message,
        "synergy_target_vs_realized": messages.synergy_message,
    }.get(builder, lambda _m: builder.replace("_", " ").title())(model)

    return Section(
        section_id=section_id,
        label=builder.replace("_", " ").title(),
        headline=headline,
        blocks=[ChartBlock(block_id=f"{section_id}.chart", builder=builder)],
    )


def _limitations(
    model: PMIDataModel, quality: Optional[DataQualityReport]
) -> Section:
    """§12.5. The slide that says what this report could not do.

    It exists because the alternative is a document that looks equally confident
    whether or not it should — which is the single most damaging thing this
    system could produce.
    """
    from app.agent.data_quality import summarize

    # Lines and title are the deck's, verbatim. This section is asserted by the
    # existing generator tests, and rewording it would change what a board pack
    # says about its own reliability — not a refactor's business.
    lines = summarize(quality) if quality else []

    # Read independently of the quality report (§5.6, §21.14). A figure
    # interpreted from a screenshot belongs here whether or not a report was
    # built; the document must not look clean merely because the thing that
    # usually flags this did not run.
    low = model.low_confidence_items()
    if low:
        lines.append(
            "Read from images/scans at low confidence: "
            + "; ".join(f"{label} ({confidence:.0%})"
                        for _kind, label, confidence in low[:4])
        )

    unresolved = model.unresolved_conflicts()
    items = [
        Bullet(text=line,
               emphasis=("bad" if ("UNRESOLVED" in line or "could NOT" in line
                                   or "⚠" in line) else "warn"))
        for line in lines[:9]
    ]

    if unresolved:
        headline = (f"⚠ {len(unresolved)} unresolved source conflict(s) — "
                    f"figures are not agreed")
        explanation = None
    elif items:
        headline = "Data quality and limitations"
        explanation = None
    elif quality:
        headline = "Data quality and limitations"
        explanation = "Every source was readable and no conflicts remain."
    else:
        # Silence here would be a claim we have not earned.
        headline = "Data quality was not assessed for this report"
        explanation = ("No data-quality report was produced, so this document "
                       "cannot state what it could not do. Treat it as "
                       "unverified.")

    return Section(
        section_id="quality.limitations",
        label="How this report was produced",
        headline=headline,
        blocks=[BulletsBlock(block_id="quality.bullets", items=items)],
        empty_explanation=explanation,
    )


# ------------------------------------------------------------------- helpers
def _row(*texts: str) -> list[Cell]:
    return [Cell(text=t) for t in texts]


def _cols(
    headers: list[str],
    *,
    percent: Optional[set[int]] = None,
    currency: Optional[set[int]] = None,
    date: Optional[set[int]] = None,
    rag: Optional[set[int]] = None,
    negative: Optional[set[int]] = None,
) -> list[Column]:
    """Column intent by index — the workbook turns this back into formats."""
    percent, currency, date = percent or set(), currency or set(), date or set()
    rag, negative = rag or set(), negative or set()

    out = []
    for index, header in enumerate(headers):
        kind = ("percent" if index in percent else
                "currency" if index in currency else
                "date" if index in date else "text")
        out.append(Column(header=header, kind=kind, rag=index in rag,
                          negative_is_bad=index in negative))
    return out


def _more(total: int, shown: int) -> str:
    return (f"Showing {shown} of {total}. The full list is in the Excel dashboard."
            if total > shown else "")


def _progress_emphasis(model: PMIDataModel) -> str:
    progress = model.overall_progress()
    return "good" if (progress or 0) >= 70 else "warn"


def _day1_emphasis(model: PMIDataModel) -> str:
    day_1 = [t for t in model.tasks if t.is_day_1_critical]
    done = sum(1 for t in day_1 if t.status is Status.COMPLETED)
    return "good" if day_1 and done == len(day_1) else "warn"


def _variance_emphasis(model: PMIDataModel) -> str:
    over = [b for b in model.budget if b.variance is not None and b.variance < 0]
    return "bad" if over else "good"
