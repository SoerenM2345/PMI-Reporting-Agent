"""Ask the model which visual to build, then build it in Python.

The model returns a `ChartRequest` — a type, the evidence to plot, which field
of each record becomes each series. `builder.build_chart` reads the values,
`validator.validate_chart` checks them, and only then is anything drawn.

The important behaviour is the **fallback path**, and not the keyless one: when a
chart cannot be validated, this does not emit a placeholder. It returns a table
of the same evidence instead, and records why. A caption over empty space is the
single most visible failure the old renderers had, and it was reachable in three
different ways — an unset caption, an unrenderable builder key, and a docx/pdf
path that never embedded an image at all.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from app.context.schemas import GenerationContext
from app.deliverable.model import ChartElement, DiagramElement, PageDesign, TableElement
from app.evidence.model import EvidenceIndex, EvidenceItem
from app.llm import prompts, reasoning_model, tasks
from app.visualizations import builder, tables, validator
from app.visualizations.specs import (
    ChartRequest,
    ChartRequests,
    ChartSpec,
    DiagramRequest,
    DiagramRequests,
    DiagramSpec,
    SeriesRequest,
    TableSpec,
)

log = logging.getLogger("pmi.generation.charts")


class VisualOutcome:
    """What a page ended up with, and what it gave up to get there."""

    def __init__(self) -> None:
        self.charts: dict[str, ChartSpec] = {}
        self.diagrams: dict[str, DiagramSpec] = {}
        self.tables: dict[str, TableSpec] = {}
        self.downgraded: list[str] = []
        self.warnings: list[str] = []


def build_visuals(page: PageDesign, context: GenerationContext, *,
                  use_model: bool = True) -> VisualOutcome:
    """Resolve every chart, diagram and table element on one page."""
    outcome = VisualOutcome()
    evidence = context.evidence

    for element in list(page.elements):
        if isinstance(element, ChartElement):
            _resolve_chart(element, page, evidence, outcome, use_model)
        elif isinstance(element, DiagramElement):
            _resolve_diagram(element, page, evidence, outcome, use_model)
        elif isinstance(element, TableElement):
            _resolve_table(element, page, evidence, outcome)
    return outcome


# ------------------------------------------------------------------- charts
def _resolve_chart(element: ChartElement, page: PageDesign,
                   evidence: EvidenceIndex, outcome: VisualOutcome,
                   use_model: bool) -> None:
    items = evidence.resolve(element.evidence_ids)
    request = (plan_chart(element, page, items, use_model=use_model)
               if items else None)
    if request is None:
        _downgrade(element, page, evidence, outcome,
                   "no chart could be specified from the evidence on this page")
        return

    spec = builder.build_chart(request, evidence)
    result = validator.validate_chart(spec, evidence)
    if not result.ok:
        _downgrade(element, page, evidence, outcome, result.summary)
        return

    spec.warnings.extend(result.warnings)
    outcome.charts[element.spec_id] = spec
    element.caption = spec.caption
    page.evidence_ids = _merge(page.evidence_ids, spec.evidence_ids)


def plan_chart(element: ChartElement, page: PageDesign,
               items: Sequence[EvidenceItem], *,
               use_model: bool = True) -> Optional[ChartRequest]:
    """The model's chart, or a deterministic one derived from the evidence."""
    if not use_model:
        return fallback_chart(element, page, items)

    requests = tasks.run_task(
        "plan.charts",
        system=prompts.compose("_grounding_rules", "plan_charts"),
        user=_chart_payload(element, page, items),
        output_model=ChartRequests,
        model=reasoning_model(),
        max_tokens=3072,
        fallback=lambda: ChartRequests(
            charts=[c for c in [fallback_chart(element, page, items)] if c]),
    )
    if not requests.charts:
        return fallback_chart(element, page, items)
    request = requests.charts[0]
    request.spec_id = element.spec_id
    # The model may narrow the evidence but not widen it: a chart may only plot
    # what the page was planned to be about.
    allowed = set(element.evidence_ids)
    narrowed = [i for i in request.evidence_ids if i in allowed]
    request.evidence_ids = narrowed or list(element.evidence_ids)
    return request


def _chart_payload(element: ChartElement, page: PageDesign,
                   items: Sequence[EvidenceItem]) -> str:
    fields = sorted({field for item in items
                     for field, value in item.payload.items()
                     if isinstance(value, (int, float))
                     and not isinstance(value, bool)})
    return "\n\n".join([
        f"## The page\n{page.title}\n{page.subtitle}",
        f"## What this chart must show\n{element.caption or 'not stated'}",
        "## Evidence available to this chart\n"
        + "\n".join(item.one_line() for item in items[:40]),
        "## Numeric fields present on these records\n"
        + (", ".join(fields) or "(only each record's own value)"),
    ])


def fallback_chart(element: ChartElement, page: PageDesign,
                   items: Sequence[EvidenceItem]) -> Optional[ChartRequest]:
    """Derive a chart from the shape of the evidence, with no model.

    Deliberately conservative: it produces a chart only where the evidence
    plainly supports one, and returns `None` otherwise so the caller falls back
    to a table. A weak chart is worse than an honest table.
    """
    usable = [i for i in items if not i.is_absence]
    if not usable:
        return None

    kinds = {i.kind for i in usable}
    if len(kinds) > 1:
        # A page commonly carries both entity rows and computed headline facts.
        # Plot the homogeneous entity rows; the computed fact remains available
        # to the commentary/KPI, but mixing it into the chart would create
        # incompatible fields.
        chartable = [kind for kind in kinds if kind in _FALLBACK_SERIES]
        if len(chartable) != 1:
            return None
        usable = [item for item in usable if item.kind == chartable[0]]
        kinds = {chartable[0]}
    kind = next(iter(kinds))

    series = _FALLBACK_SERIES.get(kind)
    if series is None:
        numeric = [i for i in usable if isinstance(i.value, (int, float))]
        if len(numeric) < 2:
            return None
        series = [SeriesRequest(name=_series_label(usable), value_field="value")]
        usable = numeric
    elif len(usable) < 2 and len(series) < 2:
        # One scalar rendered as one bar is decoration, not analysis. A single
        # budget or synergy record with several real series is still a valid
        # comparison (budget/actual/forecast or target/realised).
        return None

    return ChartRequest(
        spec_id=element.spec_id,
        chart_type="bar" if len(usable) > 6 else "column",
        title=page.title or element.caption,
        insight=element.caption,
        evidence_ids=[i.evidence_id for i in usable][:12],
        category_field="label",
        series=series,
        sort="value_desc" if len(series) == 1 else "none",
        caption=element.caption or page.title or "Chart",
        alt_text="",
    )


#: Which fields make a chart for each kind, when nobody chose.
_FALLBACK_SERIES: dict[str, list[SeriesRequest]] = {
    "budget": [SeriesRequest(name="Budget", value_field="budget"),
               SeriesRequest(name="Actual", value_field="actual"),
               SeriesRequest(name="Forecast", value_field="forecast")],
    "synergy": [SeriesRequest(name="Target", value_field="target_value"),
                SeriesRequest(name="Realised", value_field="realized_value")],
    "workstream": [SeriesRequest(name="Progress",
                                 value_field="progress_percentage")],
    "task": [SeriesRequest(name="Progress", value_field="progress_percentage")],
    "risk": [SeriesRequest(name="Score", value_field="risk_score")],
    "kpi": [SeriesRequest(name="Current", value_field="current_value"),
            SeriesRequest(name="Target", value_field="target_value")],
}


def _series_label(items: Sequence[EvidenceItem]) -> str:
    units = {i.unit for i in items if i.unit}
    return next(iter(units)) if len(units) == 1 else "Value"


# ----------------------------------------------------------------- diagrams
def _resolve_diagram(element: DiagramElement, page: PageDesign,
                     evidence: EvidenceIndex, outcome: VisualOutcome,
                     use_model: bool) -> None:
    items = evidence.resolve(element.evidence_ids)
    request = (plan_diagram(element, page, items, use_model=use_model)
               if items else None)
    if request is None:
        _downgrade(element, page, evidence, outcome,
                   "no diagram could be specified from the evidence on this page")
        return

    spec = builder.build_diagram(request, evidence)
    result = validator.validate_diagram(spec, evidence)
    if not result.ok:
        _downgrade(element, page, evidence, outcome, result.summary)
        return

    spec.warnings.extend(result.warnings)
    outcome.diagrams[element.spec_id] = spec
    element.caption = spec.caption
    page.evidence_ids = _merge(page.evidence_ids, spec.evidence_ids)


def plan_diagram(element: DiagramElement, page: PageDesign,
                 items: Sequence[EvidenceItem], *,
                 use_model: bool = True) -> Optional[DiagramRequest]:
    if not use_model:
        return fallback_diagram(element, page, items)

    requests = tasks.run_task(
        "plan.diagrams",
        system=prompts.compose("_grounding_rules", "plan_diagrams"),
        user=_diagram_payload(element, page, items),
        output_model=DiagramRequests,
        model=reasoning_model(),
        max_tokens=3072,
        fallback=lambda: DiagramRequests(
            diagrams=[d for d in [fallback_diagram(element, page, items)] if d]),
    )
    if not requests.diagrams:
        return fallback_diagram(element, page, items)
    request = requests.diagrams[0]
    request.spec_id = element.spec_id
    allowed = set(element.evidence_ids)
    request.evidence_ids = [i for i in request.evidence_ids if i in allowed] \
        or list(element.evidence_ids)
    for node in request.nodes:
        if node.evidence_id and node.evidence_id not in allowed:
            node.evidence_id = ""
    return request


def _diagram_payload(element: DiagramElement, page: PageDesign,
                     items: Sequence[EvidenceItem]) -> str:
    return "\n\n".join([
        f"## The page\n{page.title}\n{page.subtitle}",
        f"## What this diagram must show\n{element.caption or 'not stated'}",
        "## Evidence available to it\n"
        + "\n".join(item.one_line() for item in items[:40]),
    ])


_TIMELINE_WORDS = re.compile(r"\b(timeline|roadmap|schedule|sequence|phase|"
                             r"milestone|when|date)\b", re.I)
_MATRIX_WORDS = re.compile(r"\b(matrix|heat ?map|grid|probability|impact|"
                           r"likelihood)\b", re.I)
_FLOW_WORDS = re.compile(r"\b(process|flow|steps?|stages?|hand-?over|"
                         r"governance|operating model)\b", re.I)


def fallback_diagram(element: DiagramElement, page: PageDesign,
                     items: Sequence[EvidenceItem]) -> Optional[DiagramRequest]:
    """Choose a diagram from the evidence's own shape, with no model."""
    usable = [i for i in items if not i.is_absence]
    if not usable:
        return None
    hint = f"{page.title} {element.caption}"

    dated = [i for i in usable if i.due]
    scored = [i for i in usable
              if i.payload.get("probability") and i.payload.get("impact")]

    if _MATRIX_WORDS.search(hint) and len(scored) >= 2:
        kind = "risk_matrix"
        chosen = scored
    elif (_TIMELINE_WORDS.search(hint) or len(dated) >= 2) and len(dated) >= 2:
        kind = "timeline"
        chosen = sorted(dated, key=lambda i: i.due)
    elif _FLOW_WORDS.search(hint) and len(usable) >= 2:
        kind = "process_flow"
        chosen = usable
    elif len(scored) >= 2:
        kind = "risk_matrix"
        chosen = scored
    else:
        return None

    return DiagramRequest(
        spec_id=element.spec_id,
        diagram_type=kind,                                     # type: ignore[arg-type]
        title=page.title or element.caption,
        insight=element.caption,
        evidence_ids=[i.evidence_id for i in chosen][:14],
        caption=element.caption or page.title or "Diagram",
        x_axis_label="Probability" if kind == "risk_matrix" else "",
        y_axis_label="Impact" if kind == "risk_matrix" else "",
    )


# ------------------------------------------------------------------- tables
def _resolve_table(element: TableElement, page: PageDesign,
                   evidence: EvidenceIndex, outcome: VisualOutcome) -> None:
    items = evidence.resolve(element.evidence_ids)
    spec = tables.build_table(element.spec_id, items,
                              title=page.title, caption=element.caption)
    result = validator.validate_table(spec, evidence)
    if not result.ok:
        page.warnings.append(f"A table on this page could not be built: "
                             f"{result.summary}")
        page.elements = [e for e in page.elements
                         if e.element_id != element.element_id]
        outcome.warnings.append(result.summary)
        return
    spec.warnings.extend(result.warnings)
    outcome.tables[element.spec_id] = spec
    element.caption = spec.caption or element.caption


# ---------------------------------------------------------------- downgrade
def _downgrade(element, page: PageDesign, evidence: EvidenceIndex,
               outcome: VisualOutcome, reason: str) -> None:
    """Replace an unbuildable visual with a table of the same evidence.

    Never a placeholder. A caption with nothing under it is the failure this
    whole layer exists to make impossible.
    """
    items = evidence.resolve(element.evidence_ids)
    kind = "chart" if isinstance(element, ChartElement) else "diagram"
    outcome.downgraded.append(element.spec_id)
    outcome.warnings.append(f"{element.spec_id}: {reason}")

    if not items:
        page.elements = [e for e in page.elements
                         if e.element_id != element.element_id]
        page.warnings.append(
            f"A {kind} was planned here but {reason}; the page shows the "
            f"narrative instead.")
        log.info("dropped %s on %s: %s", kind, page.page_id, reason)
        return

    spec = tables.build_table(
        element.spec_id, items, title=page.title,
        caption=element.caption or page.title)
    outcome.tables[spec.spec_id] = spec

    replacement = TableElement(
        element_id=element.element_id, slot=element.slot,
        evidence_ids=element.evidence_ids, authored_by=element.authored_by,
        prominence=element.prominence, spec_id=element.spec_id,
        caption=spec.caption)
    page.elements = [replacement if e.element_id == element.element_id else e
                     for e in page.elements]
    page.warnings.append(
        f"A {kind} was planned here but {reason}; the same evidence is shown as "
        f"a table.")
    log.info("downgraded %s to a table on %s: %s", kind, page.page_id, reason)


def _merge(existing: Sequence[str], extra: Sequence[str]) -> list[str]:
    out = list(existing)
    for item in extra:
        if item not in out:
            out.append(item)
    return out
