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

import logging
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
    EntityFieldRef,
    EntityQuery,
    ProseBlock,
    ReportContent,
    Section,
    TableBlock,
    Tile,
    TilesBlock,
)
from app.report.facts import build_facts

log = logging.getLogger("pmi.report.planner")

ROW_LIMIT = 12

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
    audience_label: str = "",
    structure=None,
) -> ReportContent:
    """The report, as content. Pure: no disk, no network, no LLM.

    `structure` is a `report.structure.StructureSpec` the user asked for. When
    present it replaces `DECKS` as the order — for every format, because every
    format plans from this one object. `DECKS` remains the default.
    """
    facts = build_facts(model, quality)
    when = model.project.reporting_date or date.today()

    sections: list[Section] = []

    # Slide 2 / the opening of every format. Always first, always present —
    # including when the user gave a structure that did not mention it, because
    # a report with no opening is not a shape anybody wants.
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

    warnings: list[str] = []
    order = 2

    if structure and structure.sections:
        order = _planned_from_structure(structure, model, available, sections,
                                        warnings, order)
    else:
        for section_id in DECKS.get(audience, DECKS[Audience.PMO]):
            section = _safe_section(section_id, model, available, warnings)
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

    # §13's ten sheets, planned rather than re-derived. They carry
    # `narrative_order=None`, so `ReportContent.narrative()` skips them and no
    # deck, document or preview ever shows them — one structure, two
    # projections. The workbook used to walk `PMIDataModel` itself, which is why
    # it was the one format that could disagree with the preview the user had
    # already approved.
    sections.extend(_workbook_sections(model, quality, bullets or []))

    return ReportContent(
        warnings=warnings,
        session_id=session_id,
        audience=audience,
        topic=topic,
        title=model.project.project_name,
        audience_label=audience_label,
        # The user's own words when they gave any. Titling a deck "IMO / PMO"
        # for someone who asked for "the Integration Director pack" tells them
        # it was written for somebody else.
        subtitle=(f"{audience_label or AUDIENCE_LABEL.get(audience, 'Report')} "
                  f"— {when:%d-%m-%Y}"),
        meta_line=[f"Reporting date: {when:%d-%m-%Y}",
                   f"Sources: {len(model.source_files)} file(s)"],
        # No footer by default. The prototype disclaimer used to be stamped on
        # every slide of every deck regardless of what was planned, which made a
        # finished report look provisional to the people it was written for.
        footer="",
        facts=facts,
        sections=sections,
        analysis_fingerprint=fingerprint,
        provenance=ContentProvenance(created_by="planner"),
    )


def _safe_section(section_id, model, available, warnings) -> Optional[Section]:
    """One section builder, fault-isolated — the same discipline as
    `charts.generate`.

    A builder that raises used to take the entire report with it: the exception
    propagated out of `plan()`, out of `respond()`, and reached the user as a
    bare 500 on the chat turn. One section that cannot be built is a gap in a
    report; it is not a reason to have no report. The failure is recorded on
    `ReportContent.warnings` rather than swallowed — never return empty on
    failure, and never lose the reason.
    """
    try:
        if section_id.startswith("chart."):
            return _chart_section(section_id, model)
        builder = available.get(section_id)
        if builder is None:
            warnings.append(f"Section '{section_id}' is not a known section.")
            return None
        return builder()
    except Exception as exc:                                  # noqa: BLE001
        log.exception("section %s could not be planned", section_id)
        warnings.append(
            f"Section '{section_id}' could not be built and is missing from this "
            f"report ({type(exc).__name__}: {exc})."
        )
        return None


def _planned_from_structure(structure, model, available, sections, warnings,
                            order: int) -> int:
    """The user's order, section by section.

    An unmatched title is **not** dropped. A reader who asked for "TSA exit" and
    sees no such section concludes there is nothing to report; a section saying
    no source covers it tells them the truth, which is that nobody wrote it down
    (§21.17).
    """
    from app.report import structure as structure_mod

    # The summary and the limitations are always emitted by `plan` — first and
    # last — so a request that names them resolves to the real section and is
    # skipped here rather than producing a second, empty copy.
    matchable = set(available) | set(_CHART_SECTIONS) | {
        "summary.executive", "quality.limitations"}
    seen: set[str] = {"summary.executive"}
    for wanted in structure.sections:
        section_id = wanted.section_id or structure_mod.match(
            wanted.title, matchable
        )

        if section_id == "quality.limitations":
            # Always appended last by `plan`, never placed by the user.
            continue
        if section_id and section_id in seen:
            continue

        if section_id is None:
            section = _uncovered(wanted.title)
        else:
            section = _safe_section(section_id, model, available, warnings)
            seen.add(section_id)
            if section is None:
                # The builder had nothing to show. The user asked for it by
                # name, so say that rather than leaving a hole.
                section = _uncovered(wanted.title, matched=True)

        section.narrative_order = order
        sections.append(section)
        order += 1
    return order


#: Chart sections are built by id rather than from `available`, so structure
#: matching has to be told they exist.
_CHART_SECTIONS = (
    "chart.workstream_progress", "chart.tasks_by_status",
    "chart.budget_vs_actual", "chart.synergy_target_vs_realized",
)


def _uncovered(title: str, *, matched: bool = False) -> Section:
    """A section the user asked for that the sources do not answer."""
    return Section(
        section_id=f"requested.{title.lower().replace(' ', '_')[:40]}",
        label=title,
        headline=f"{title} — not covered by the uploaded files",
        blocks=[],
        origin="user",
        empty_explanation=(
            f"You asked for “{title}”. "
            + ("No source file recorded anything under it."
               if matched else
               "Nothing in the uploaded files maps to this section, so it is "
               "empty rather than omitted — treat it as unreported, not as "
               "nothing to report.")
        ),
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
        _erow(
            w, "workstream", "workstream_id",
            (w.name, "name"),
            (w.lead or fmt.DASH, "lead"),
            (w.status.value.replace("_", " ").title(), "status"),
            (f"{w.progress_percentage:.0f}%"
             if w.progress_percentage is not None else fmt.NOT_REPORTED,
             "progress_percentage"),
            (str(len(w.open_risks)), None),
            (str(len(w.upcoming_milestones)), None),
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
        _erow(
            r, "risk", "risk_id",
            (r.risk_id, None),
            (r.title, "title"),
            (r.rating.value.title(), None),
            # Derived by `calculations.py` from probability x impact — editing
            # the score itself would overwrite arithmetic the LLM never does.
            (str(r.risk_score) if r.risk_score is not None else "Not scored", None),
            # An unowned critical risk is the finding, not a blank cell.
            (r.owner or "⚠ NO OWNER", "owner"),
            ((r.mitigation_action or "⚠ NO MITIGATION")[:60], "mitigation_action"),
            (fmt.cite(r, missing=fmt.DASH), None),
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
        _erow(
            m, "milestone", "milestone_id",
            (m.name, "name"),
            (fmt.date_str(m.planned_date, missing=fmt.DASH), "planned_date"),
            (fmt.date_str(m.forecast_date or m.actual_date, missing=fmt.DASH),
             "forecast_date"),
            # Derived from the two dates above (§11).
            (f"+{m.delay_days}d" if (m.delay_days or 0) > 0 else "on plan", None),
            (m.status.value.replace("_", " ").title(), "status"),
            (m.owner or fmt.DASH, "owner"),
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
        _erow(t, "task", "task_id",
              (t.task_id, None),
              (t.title, "title"),
              (t.workstream or fmt.DASH, "workstream"),
              (t.owner or "⚠ UNASSIGNED", "owner"),
              (fmt.date_str(t.due_date, missing=fmt.DASH), "due_date"),
              (f"{t.days_overdue}d" if getattr(t, "days_overdue", None)
               else fmt.DASH, None),
              (t.status.value.replace("_", " ").title(), "status"))
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
        # `providing_` / `receiving_`, not `from_` / `to_`: `Dependency` never
        # declared the latter, so this section raised `AttributeError` for every
        # PMO/Workstream plan whose file set contained a dependency, killing the
        # whole report and 500-ing the chat turn that asked for it.
        _erow(d, "dependency", "dependency_id",
              (d.description[:70], "description"),
              (d.providing_workstream or fmt.DASH, "providing_workstream"),
              (d.receiving_workstream or fmt.DASH, "receiving_workstream"),
              (d.owner or fmt.DASH, "owner"),
              (fmt.date_str(d.required_date, missing=fmt.DASH), "required_date"),
              (d.status.value.replace("_", " ").title(), "status"))
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
        _erow(
            d, "decision", "decision_id",
            (d.title, "title"),
            (d.decision_body.value, None),
            (d.decision_owner or "⚠ NO OWNER", "decision_owner"),
            (fmt.date_str(d.decision_deadline, missing=fmt.DASH)
             if d.decision_deadline else "⚠ NO DEADLINE", "decision_deadline"),
            (d.recommended_option or fmt.DASH, "recommended_option"),
            ((d.impact or fmt.DASH)[:50], "impact"),
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
        _erow(b, "budget", "budget_item_id",
              (b.category, "category"),
              (fmt.num(b.budget), "budget"),
              (fmt.num(b.actual), "actual"),
              (fmt.num(b.forecast), "forecast"),
              # Variance and its percentage are ours, computed in Python (§11).
              (fmt.num(b.variance), None),
              (f"{b.variance_percentage:.0f}%"
               if b.variance_percentage is not None else fmt.NOT_REPORTED, None),
              (fmt.cite(b, missing=fmt.DASH), None))
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
        _erow(s, "synergy", "synergy_id",
              (s.title[:60], "title"),
              (s.synergy_type.value.title()
               if getattr(s, "synergy_type", None) else fmt.DASH, None),
              (fmt.num(s.target_value), "target_value"),
              (fmt.num(s.realized_value), "realized_value"),
              (fmt.num(s.forecast_value), "forecast_value"),
              (fmt.num(s.remaining_value), None),      # derived
              (s.confidence_level or fmt.NOT_REPORTED, "confidence_level"))
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
        _erow(r, "risk", "risk_id",
              (r.risk_id, None),
              (r.title[:60], "title"),
              (r.rating.value.title(), None),
              (fmt.num(getattr(r, "financial_impact", None)), "financial_impact"),
              (r.owner or "⚠ NO OWNER", "owner"))
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
                _erow(t, "task", "task_id",
                      (t.title[:70], "title"),
                      (t.owner or "⚠ UNASSIGNED", "owner"),
                      (fmt.date_str(t.due_date, missing=fmt.DASH), "due_date"),
                      (t.status.value.replace("_", " ").title(), "status"))
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


# ================================================== §13 the workbook's sheets
#: Sheet name -> section id. The names are what a reader navigates by and what
#: `tests/test_generators.py` asserts; they do not change.
WORKBOOK_SHEETS: list[tuple[str, str]] = [
    ("Executive Dashboard", "sheet.executive"),
    ("Workstream Scorecard", "sheet.workstreams"),
    ("Masterplan", "sheet.masterplan"),
    ("Risks", "sheet.risks"),
    ("Issues", "sheet.issues"),
    ("Dependencies", "sheet.dependencies"),
    ("Decisions", "sheet.decisions"),
    ("Budget", "sheet.budget"),
    ("Synergies", "sheet.synergies"),
    ("Data Quality", "sheet.data_quality"),
]


def _workbook_sections(model, quality, bullets: list[str]) -> list[Section]:
    """§13's ten sheets, as planned content.

    Deliberately *not* filtered by audience: §13 is a data dump and wants every
    sheet regardless of who the deck was written for. Forcing it through
    `narrative()` would either drop sheets the spec requires or hollow out the
    audience filter for everyone else, so these carry `narrative_order=None`
    and the projection skips them.
    """
    builders = {
        "sheet.executive": lambda: _sheet_executive(model, bullets),
        "sheet.workstreams": lambda: _sheet_workstreams(model),
        "sheet.masterplan": lambda: _sheet_masterplan(model),
        "sheet.risks": lambda: _sheet_risks(model),
        "sheet.issues": lambda: _sheet_issues(model),
        "sheet.dependencies": lambda: _sheet_dependencies(model),
        "sheet.decisions": lambda: _sheet_decisions(model),
        "sheet.budget": lambda: _sheet_budget(model),
        "sheet.synergies": lambda: _sheet_synergies(model),
        "sheet.data_quality": lambda: _sheet_data_quality(model, quality),
    }
    out: list[Section] = []
    for name, section_id in WORKBOOK_SHEETS:
        try:
            section = builders[section_id]()
        except Exception:                                     # noqa: BLE001
            log.exception("workbook sheet %s could not be planned", name)
            continue
        if section is not None:
            section.label = name          # the sheet's name, verbatim
            out.append(section)
    return out


def _sheet_executive(model, bullets: list[str]) -> Section:
    """§13.1. Tiles and prose rather than a table — the renderer lays it out."""
    day_1 = [t for t in model.tasks if t.is_day_1_critical]
    day_1_done = sum(1 for t in day_1 if t.status is Status.COMPLETED)
    progress = model.overall_progress()
    budget = sum(b.budget or 0 for b in model.budget)
    forecast = sum(b.forecast or 0 for b in model.budget)
    target = sum(s.target_value or 0 for s in model.synergies)
    realized = sum(s.realized_value or 0 for s in model.synergies)

    figures = [
        ("Overall PMI status", _overall_status(model)),
        ("Overall progress",
         f"{progress:.0f}%" if progress is not None else fmt.NOT_REPORTED),
        ("Day 1 readiness",
         f"{day_1_done}/{len(day_1)} complete" if day_1 else fmt.NOT_REPORTED),
        ("Open critical risks",
         str(len([r for r in model.critical_risks() if r.status.is_open]))),
        ("Open issues", str(sum(1 for i in model.issues if i.status.is_open))),
        ("Overdue tasks", str(len(model.overdue_tasks()))),
        ("Overdue milestones",
         str(sum(1 for m in model.milestones if (m.delay_days or 0) > 0))),
        ("Budget variance",
         f"{budget - forecast:,.0f}" if budget and forecast else fmt.NOT_REPORTED),
        ("Synergy realization",
         f"{realized / target * 100:.0f}%" if target else fmt.NOT_REPORTED),
        ("Decisions required",
         str(sum(1 for d in model.decisions if d.status.is_open))),
        ("Unresolved source conflicts", str(len(model.unresolved_conflicts()))),
    ]

    return Section(
        section_id="sheet.executive",
        label="Executive Dashboard",
        headline=messages.status_message(model),
        blocks=[
            BulletsBlock(block_id="sheet.executive.summary",
                         title="Executive summary",
                         items=[Bullet(text=b) for b in bullets]),
            TilesBlock(block_id="sheet.executive.figures", tiles=[
                Tile(label=label, value=value) for label, value in figures
            ]),
        ],
    )


def _overall_status(model) -> str:
    if model.unresolved_conflicts():
        return "Not agreed — unresolved source conflicts"
    if [r for r in model.critical_risks() if r.status.is_open]:
        return "At Risk"
    if model.overdue_tasks():
        return "At Risk — overdue activities"
    if model.tasks:
        return "On Track"
    return fmt.NOT_REPORTED


def _sheet_workstreams(model) -> Optional[Section]:
    if not model.workstreams:
        return None
    return _table_sheet(
        "sheet.workstreams", "Workstream Scorecard",
        messages.workstream_message(model),
        _cols(["Workstream", "Lead", "Status", "Progress %", "Open risks",
               "Open issues", "Milestones", "Source"],
              percent={3}, rag={2}),
        [
            _erow(w, "workstream", "workstream_id",
                  (w.name, "name"),
                  (w.lead or fmt.NOT_REPORTED, "lead"),
                  (w.status.value.replace("_", " ").title(), "status"),
                  (_number(w.progress_percentage), "progress_percentage"),
                  (str(len(w.open_risks)), None),
                  (str(len(w.open_issues)), None),
                  (str(len(w.upcoming_milestones)), None),
                  (_cite_full(w), None))
            for w in model.workstreams
        ],
    )


def _sheet_masterplan(model) -> Optional[Section]:
    """§13.3. Tasks and milestones in one plan, as a reader of a plan expects."""
    rows = [
        _erow(t, "task", "task_id",
              (t.task_id, None), ("Task", None), (t.title, "title"),
              (t.workstream or "—", "workstream"),
              (t.owner or fmt.NOT_REPORTED, "owner"),
              (t.status.value.replace("_", " ").title(), "status"),
              (_number(t.progress_percentage), "progress_percentage"),
              (_date(t.start_date), "start_date"),
              (_date(t.due_date), "due_date"),
              ("YES" if t.is_overdue else "", None),
              ("YES" if t.is_day_1_critical else "", None),
              (_cite_full(t), None))
        for t in model.tasks
    ] + [
        _erow(m, "milestone", "milestone_id",
              (m.milestone_id, None), ("Milestone", None), (m.name, "name"),
              (m.workstream or "—", "workstream"),
              (m.owner or fmt.NOT_REPORTED, "owner"),
              (m.status.value.replace("_", " ").title(), "status"),
              (fmt.NOT_REPORTED, None),
              ("", None),
              (_date(m.planned_date), "planned_date"),
              ("YES" if (m.delay_days or 0) > 0 else "", None),
              ("YES" if m.is_day_1_critical else "", None),
              (_cite_full(m), None))
        for m in model.milestones
    ]
    if not rows:
        return None
    return _table_sheet(
        "sheet.masterplan", "Masterplan", messages.milestone_message(model),
        _cols(["ID", "Type", "Title", "Workstream", "Owner", "Status",
               "Progress %", "Start", "Due", "Overdue", "Day 1", "Source"],
              percent={6}, date={7, 8}, rag={5}, flag={9, 10}),
        rows,
    )


def _sheet_risks(model) -> Optional[Section]:
    if not model.risks:
        return None
    return _table_sheet(
        "sheet.risks", "Risks", messages.risk_message(model),
        _cols(["ID", "Risk", "Category", "Workstream", "Rating", "Probability",
               "Impact", "Score", "Trend", "Owner", "Mitigation",
               "Mitigation owner", "Mitigation due", "Escalate", "Status",
               "Source"],
              date={12}, rag={4}, flag={13}),
        [
            _erow(r, "risk", "risk_id",
                  (r.risk_id, None), (r.title, "title"),
                  (r.category.value, None), (r.workstream or "—", "workstream"),
                  (r.rating.value.title(), None),
                  (_number(r.probability), "probability"),
                  (_number(r.impact), "impact"),
                  # Derived: probability x impact, computed in Python (§11).
                  (_number(r.risk_score), None),
                  (r.trend.value.title(), None),
                  (r.owner or fmt.NOT_REPORTED, "owner"),
                  (r.mitigation_action or fmt.NOT_REPORTED, "mitigation_action"),
                  (r.mitigation_owner or fmt.NOT_REPORTED, "mitigation_owner"),
                  (_date(r.mitigation_due_date), "mitigation_due_date"),
                  ("YES" if r.escalation_required else "", None),
                  (r.status.value.replace("_", " ").title(), "status"),
                  (_cite_full(r), None))
            for r in sorted(model.risks, key=lambda r: r.risk_score or 0,
                            reverse=True)
        ],
    )


def _sheet_issues(model) -> Optional[Section]:
    if not model.issues:
        return None
    return _table_sheet(
        "sheet.issues", "Issues",
        f"{sum(1 for i in model.issues if i.status.is_open)} open issue(s)",
        _cols(["ID", "Issue", "Workstream", "Severity", "Owner", "Resolution",
               "Resolution owner", "Due", "Escalate", "Status", "Source"],
              date={7}, rag={3}, flag={8}),
        [
            _erow(i, "issue", "issue_id",
                  (i.issue_id, None), (i.title, "title"),
                  (i.workstream or "—", "workstream"),
                  (i.severity.value.title(), None),
                  (i.owner or fmt.NOT_REPORTED, "owner"),
                  (i.resolution_action or fmt.NOT_REPORTED, "resolution_action"),
                  (i.resolution_owner or fmt.NOT_REPORTED, "resolution_owner"),
                  (_date(i.due_date), "due_date"),
                  ("YES" if i.escalation_required else "", None),
                  (i.status.value.replace("_", " ").title(), "status"),
                  (_cite_full(i), None))
            for i in model.issues
        ],
    )


def _sheet_dependencies(model) -> Optional[Section]:
    if not model.dependencies:
        return None
    return _table_sheet(
        "sheet.dependencies", "Dependencies",
        f"{len(model.dependencies)} dependency(ies) are being tracked",
        _cols(["ID", "Dependency", "Providing", "Receiving", "Owner",
               "Required by", "Status", "Impact if delayed", "Source"],
              date={5}, rag={6}),
        [
            _erow(d, "dependency", "dependency_id",
                  (d.dependency_id, None), (d.description, "description"),
                  (d.providing_workstream or "—", "providing_workstream"),
                  (d.receiving_workstream or "—", "receiving_workstream"),
                  (d.owner or fmt.NOT_REPORTED, "owner"),
                  (_date(d.required_date), "required_date"),
                  (d.status.value.replace("_", " ").title(), "status"),
                  (d.impact_if_delayed or fmt.NOT_REPORTED, "impact_if_delayed"),
                  (_cite_full(d), None))
            for d in model.dependencies
        ],
    )


def _sheet_decisions(model) -> Optional[Section]:
    if not model.decisions:
        return None
    return _table_sheet(
        "sheet.decisions", "Decisions",
        f"{sum(1 for d in model.decisions if d.status.is_open)} decision(s) "
        f"are required",
        _cols(["ID", "Decision", "Body", "Owner", "Deadline", "Status",
               "Recommended option", "Impact", "Source"],
              date={4}, rag={5}),
        [
            _erow(d, "decision", "decision_id",
                  (d.decision_id, None), (d.title, "title"),
                  (d.decision_body.value, None),
                  (d.decision_owner or fmt.NOT_REPORTED, "decision_owner"),
                  (_date(d.decision_deadline), "decision_deadline"),
                  (d.status.value.replace("_", " ").title(), "status"),
                  (d.recommended_option or fmt.NOT_REPORTED, "recommended_option"),
                  (d.impact or fmt.NOT_REPORTED, "impact"),
                  (_cite_full(d), None))
            for d in model.decisions
        ],
    )


def _sheet_budget(model) -> Optional[Section]:
    if not model.budget:
        return None
    return _table_sheet(
        "sheet.budget", "Budget", messages.budget_message(model),
        _cols(["ID", "Category", "Workstream", "Budget", "Actual", "Committed",
               "Forecast", "Variance", "Variance %", "Currency", "Source"],
              currency={3, 4, 5, 6, 7}, percent={8}, negative={7, 8}),
        [
            _erow(b, "budget", "budget_item_id",
                  (b.budget_item_id, None), (b.category, "category"),
                  (b.workstream or "—", "workstream"),
                  (_number(b.budget), "budget"),
                  (_number(b.actual), "actual"),
                  (_number(b.committed), "committed"),
                  (_number(b.forecast), "forecast"),
                  # Variance and its percentage are ours (§11).
                  (_number(b.variance), None),
                  (_number(b.variance_percentage), None),
                  (b.currency, "currency"),
                  (_cite_full(b), None))
            for b in model.budget
        ],
    )


def _sheet_synergies(model) -> Optional[Section]:
    if not model.synergies:
        return None
    return _table_sheet(
        "sheet.synergies", "Synergies", messages.synergy_message(model),
        _cols(["ID", "Synergy", "Type", "Workstream", "Owner", "Target",
               "Realized", "Forecast", "Remaining gap", "Realization date",
               "Confidence", "Currency", "Source"],
              currency={5, 6, 7, 8}, date={9}),
        [
            _erow(s, "synergy", "synergy_id",
                  (s.synergy_id, None), (s.title, "title"),
                  (s.synergy_type.value, None),
                  (s.workstream or "—", "workstream"),
                  (s.owner or fmt.NOT_REPORTED, "owner"),
                  (_number(s.target_value), "target_value"),
                  (_number(s.realized_value), "realized_value"),
                  (_number(s.forecast_value), "forecast_value"),
                  (_number(s.remaining_value), None),         # derived
                  (_date(s.planned_realization_date),
                   "planned_realization_date"),
                  (s.confidence_level or fmt.NOT_REPORTED, "confidence_level"),
                  (s.currency, "currency"),
                  (_cite_full(s), None))
            for s in model.synergies
        ],
    )


def _sheet_data_quality(model, quality) -> Section:
    """§13.10 — and the reason the rest of the workbook can be trusted."""
    from app.agent.data_quality import summarize

    blocks: list = [BulletsBlock(
        block_id="sheet.quality.summary",
        title=(f"Score: {quality.score:.0f} / 100" if quality
               else "No data-quality report was produced"),
        items=[Bullet(text=line) for line in (summarize(quality) if quality else [])],
    )]

    if model.conflicts:
        blocks.append(TableBlock(
            block_id="sheet.quality.conflicts",
            title="Cross-source conflicts",
            columns=_cols(["Item", "Field", "Severity", "Reported values",
                           "Resolved to", "From", "How"]),
            rows=[
                [Cell(text=c.entity_key,
                      emphasis="bad" if not c.is_resolved else "none"),
                 Cell(text=c.field.replace("_", " ")),
                 Cell(text=c.severity.value.title()),
                 Cell(text=("Resolved" if c.is_resolved else
                            "; ".join(f"{f}: {v}" for f, v in c.values.items()))),
                 Cell(text=c.resolved_value or "UNRESOLVED"),
                 Cell(text=c.resolved_from or "—"),
                 Cell(text=c.resolution or "awaiting user")]
                for c in model.conflicts
            ],
        ))

    low = model.low_confidence_items()
    if low:
        blocks.append(TableBlock(
            block_id="sheet.quality.low_confidence",
            title="Low-confidence findings — verify before use",
            columns=_cols(["Type", "Item", "Confidence", "Read from"],
                          percent={2}),
            rows=[
                [Cell(text=kind, emphasis="warn"),
                 Cell(text=label, emphasis="warn"),
                 Cell(text=f"{confidence:.0%}", value=confidence,
                      emphasis="warn"),
                 Cell(text=_source_of(model, kind, label), emphasis="warn")]
                for kind, label, confidence in sorted(low, key=lambda x: x[2])
            ],
        ))

    if model.validation_issues:
        blocks.append(TableBlock(
            block_id="sheet.quality.issues",
            title="Validation issues",
            columns=_cols(["Check", "Family", "Severity", "Item", "Finding",
                           "Corrected to"]),
            rows=[
                [Cell(text=i.check_id, emphasis=_issue_emphasis(i)),
                 Cell(text=i.family, emphasis=_issue_emphasis(i)),
                 Cell(text=i.severity.value.title(), emphasis=_issue_emphasis(i)),
                 Cell(text=i.entity_label or "", emphasis=_issue_emphasis(i)),
                 Cell(text=i.message, emphasis=_issue_emphasis(i)),
                 Cell(text=i.corrected_value or "—", emphasis=_issue_emphasis(i))]
                for i in model.validation_issues
            ],
        ))

    caveats = list(quality.warnings) if quality else []
    caveats += ([f"FILE COULD NOT BE READ: {f}" for f in quality.failed_files]
                if quality else [])
    if caveats:
        blocks.append(BulletsBlock(
            block_id="sheet.quality.caveats", title="Processing caveats",
            items=[Bullet(text=c, emphasis="warn") for c in caveats],
        ))

    return Section(
        section_id="sheet.data_quality", label="Data Quality",
        headline="Data Quality", blocks=blocks,
    )


def _issue_emphasis(issue) -> str:
    from app.models.pmi import Severity as _Severity

    return "bad" if issue.severity in (_Severity.HIGH, _Severity.CRITICAL) \
        else "warn"


def _table_sheet(section_id: str, label: str, headline: str,
                 columns: list[Column], rows: list[list[Cell]]) -> Section:
    return Section(
        section_id=section_id, label=label, headline=headline,
        blocks=[TableBlock(block_id=f"{section_id}.table",
                           columns=columns, rows=rows)],
    )


def _number(value) -> str:
    """A figure as text, or "Not Reported" — never `0` (§7).

    The raw value rides along on `Cell.value` so the workbook can still write a
    sortable number; missing stays missing in both.
    """
    return fmt.NOT_REPORTED if value is None else f"{value:g}"


def _date(value) -> str:
    return fmt.date_str(value, missing=fmt.NOT_REPORTED)


def _cite_full(entity) -> str:
    """A workbook cell has room for the sheet/cell reference, and a workbook
    reader wants it — this is where someone goes to check a figure."""
    return fmt.cite(entity, with_location=True, missing=fmt.NOT_REPORTED,
                    warn_sep=" ")


def _source_of(model, kind: str, label: str) -> str:
    collections = {
        "task": (model.tasks, "title"), "milestone": (model.milestones, "name"),
        "risk": (model.risks, "title"), "issue": (model.issues, "title"),
        "budget": (model.budget, "category"),
        "synergy": (model.synergies, "title"), "kpi": (model.kpis, "name"),
        "dependency": (model.dependencies, "description"),
        "decision": (model.decisions, "title"),
    }
    entry = collections.get(kind)
    if not entry:
        return "—"
    items, attr = entry
    for item in items:
        if getattr(item, attr, None) == label:
            return _cite_full(item)
    return "—"


# ------------------------------------------------------------------- helpers
def _row(*texts: str) -> list[Cell]:
    return [Cell(text=t) for t in texts]


def _erow(entity, entity_type: str, id_attr: str,
          *cells: tuple[str, Optional[str]]) -> list[Cell]:
    """A row whose cells know which field each came from.

    `(text, field)` pairs — `field=None` for a cell with no single source field
    (a computed delay, a citation, a composite). Only the ones that name a field
    are editable in the preview, and the edit is written into the data model
    rather than into the stored content, so every format picks it up.
    """
    entity_id = getattr(entity, id_attr, None)
    return [
        Cell(text=text,
             ref=(EntityFieldRef(entity_type=entity_type, entity_id=entity_id,
                                 field=field) if field else None))
        for text, field in cells
    ]


def _cols(
    headers: list[str],
    *,
    percent: Optional[set[int]] = None,
    currency: Optional[set[int]] = None,
    date: Optional[set[int]] = None,
    rag: Optional[set[int]] = None,
    negative: Optional[set[int]] = None,
    flag: Optional[set[int]] = None,
) -> list[Column]:
    """Column intent by index — the workbook turns this back into formats."""
    percent, currency, date = percent or set(), currency or set(), date or set()
    rag, negative, flag = rag or set(), negative or set(), flag or set()

    out = []
    for index, header in enumerate(headers):
        kind = ("percent" if index in percent else
                "currency" if index in currency else
                "date" if index in date else
                "flag" if index in flag else "text")
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
