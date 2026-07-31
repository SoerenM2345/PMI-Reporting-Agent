"""The factual gate. Nothing is drawn until it passes.

Every rule below is an **error**: the spec is rejected and the caller falls back
to a table or a sentence. That is deliberate. A chart is the most authoritative
thing on a page — a reader who would question a sentence will accept a bar — so
a chart that cannot prove its data has no business being drawn, and a caption
over empty space is worse than a paragraph.

The rules that matter most, and why:

* **Every point matches its evidence.** Not "is plausible" — matches. If a point
  and the record it cites disagree, one of them is wrong and neither belongs in
  front of a board.
* **Units and currencies must agree within a chart.** EUR and USD on one axis is
  a chart that lies by construction, and nobody reading a bar checks.
* **A missing value never becomes zero, and a stacked chart or pie containing one
  is rejected outright.** You cannot honestly stack an unknown: the reader takes
  the visible segments as the whole.
* **A waterfall must reconcile.** Start plus deltas equals end, computed here
  from the evidence rather than asserted by whoever built the spec.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from app.evidence.model import EvidenceIndex
from app.visualizations.specs import (
    ChartSpec,
    DiagramSpec,
    TableSpec,
    WHOLE_OF_TYPES,
)

log = logging.getLogger("pmi.visualizations.validator")

#: Floats that came from the same source and the same arithmetic should be
#: identical; this absorbs only representation noise.
TOLERANCE = 1e-6
#: More than this many slices and a pie is unreadable; use a bar chart.
MAX_PIE_SLICES = 7


class Validation(BaseModel):
    ok: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def fail(self, message: str) -> "Validation":
        self.ok = False
        self.errors.append(message)
        return self

    def warn(self, message: str) -> "Validation":
        self.warnings.append(message)
        return self

    @property
    def summary(self) -> str:
        return "; ".join(self.errors) if self.errors else "ok"


def validate_chart(spec: ChartSpec, evidence: EvidenceIndex) -> Validation:
    result = Validation()

    if not spec.series or not spec.point_count:
        return result.fail(f"Chart {spec.spec_id!r} has no data points.")
    if not spec.caption:
        result.fail(f"Chart {spec.spec_id!r} has no caption.")
    if not spec.alt_text:
        result.warn(f"Chart {spec.spec_id!r} has no alternative text.")

    _check_traceability(spec, evidence, result)
    _check_units(spec, result)
    _check_periods(spec, result)
    _check_missing(spec, result)
    _check_type_fit(spec, result)
    _check_percentages(spec, result)
    if spec.chart_type == "waterfall":
        _check_waterfall(spec, result)

    _disclose(spec, evidence, result)
    if not result.ok:
        log.info("chart %s rejected: %s", spec.spec_id, result.summary)
    return result


def _check_traceability(spec: ChartSpec, evidence: EvidenceIndex,
                        result: Validation) -> None:
    """Every value must equal the value in the record it cites."""
    for series in spec.series:
        for point in series.points:
            if not point.evidence_id:
                result.fail(f"A point labelled {point.label!r} in "
                            f"{spec.spec_id!r} cites no evidence.")
                continue
            item = evidence.get(point.evidence_id)
            if item is None:
                result.fail(f"Point {point.label!r} cites "
                            f"{point.evidence_id!r}, which does not exist.")
                continue
            if point.value is None:
                continue
            if not _matches(point.value, item, spec, series.name):
                result.fail(
                    f"Point {point.label!r} in series {series.name!r} shows a "
                    f"value that is not in {point.evidence_id!r}.")


def _matches(value: float, item, spec: ChartSpec, series_name: str) -> bool:
    """Whether `value` appears anywhere in the record it claims to come from.

    A series reads one named field, and which field is not recorded on the point
    — so the check is that the figure is *somewhere* in that record rather than
    in a specific slot. That still catches the failure that matters: a number
    that was not read from this evidence at all.
    """
    candidates: list[float] = []
    if isinstance(item.value, (int, float)):
        candidates.append(float(item.value))
    for raw in item.payload.values():
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            candidates.append(float(raw))
    return any(abs(value - candidate) <= TOLERANCE for candidate in candidates)


def _check_units(spec: ChartSpec, result: Validation) -> None:
    units = {s.unit for s in spec.series}
    if len(units) > 1:
        named = ", ".join(sorted(str(u or "unitless") for u in units))
        result.fail(f"Chart {spec.spec_id!r} mixes units on one axis ({named}). "
                    f"Split it into separate charts.")

    currencies = {s.currency for s in spec.series if s.currency}
    if len(currencies) > 1:
        result.fail(f"Chart {spec.spec_id!r} mixes currencies "
                    f"({', '.join(sorted(currencies))}) on one axis; the "
                    f"figures are not comparable as drawn.")


def _check_periods(spec: ChartSpec, result: Validation) -> None:
    """Points in one series must share a period, unless time *is* the axis."""
    if spec.category_axis.title.casefold() == "period":
        return
    for series in spec.series:
        if series.period is None:
            continue                       # mixed or absent; nothing to enforce
    periods = {s.period for s in spec.series if s.period}
    if len(periods) > 1:
        result.fail(f"Chart {spec.spec_id!r} compares different reporting "
                    f"periods ({', '.join(sorted(periods))}) without saying so.")


def _check_missing(spec: ChartSpec, result: Validation) -> None:
    missing = [p for p in spec.all_points() if p.is_missing]
    if not missing:
        return

    if spec.chart_type in WHOLE_OF_TYPES:
        labels = ", ".join(sorted({p.label for p in missing})[:3])
        result.fail(
            f"Chart {spec.spec_id!r} is a {spec.chart_type.replace('_', ' ')}, "
            f"which presents its parts as a whole, and {len(missing)} value(s) "
            f"are not reported ({labels}). Drawing it would tell the reader the "
            f"visible segments are everything.")
        return

    for point in missing:
        if point.value is not None:
            continue
        if point.display not in ("Not Reported", "", "—"):
            result.fail(f"A missing value in {spec.spec_id!r} is displayed as "
                        f"{point.display!r} rather than as not reported.")
    result.warn(f"{len(missing)} value(s) in {spec.spec_id!r} are not reported "
                f"and are shown as gaps.")


def _check_type_fit(spec: ChartSpec, result: Validation) -> None:
    if spec.chart_type in ("pie", "donut"):
        if len(spec.series) > 1:
            result.fail(f"Chart {spec.spec_id!r} is a pie with "
                        f"{len(spec.series)} series; a pie shows one.")
        slices = len(spec.series[0].points) if spec.series else 0
        if slices > MAX_PIE_SLICES:
            result.fail(f"Chart {spec.spec_id!r} is a pie with {slices} slices; "
                        f"above {MAX_PIE_SLICES} it is unreadable. Use a bar "
                        f"chart.")
        negatives = [p for p in spec.all_points()
                     if p.value is not None and p.value < 0]
        if negatives:
            result.fail(f"Chart {spec.spec_id!r} is a pie containing negative "
                        f"values, which cannot be part of a whole.")

    if spec.chart_type in ("line", "area") and len(spec.categories) < 2:
        result.fail(f"Chart {spec.spec_id!r} is a {spec.chart_type} with "
                    f"{len(spec.categories)} category; a line needs a sequence.")


def _check_percentages(spec: ChartSpec, result: Validation) -> None:
    if not spec.value_axis.is_percentage or spec.value_axis.allow_overflow:
        return
    for point in spec.all_points():
        if point.value is None:
            continue
        if point.value < 0 or point.value > 100:
            result.fail(f"Chart {spec.spec_id!r} plots {point.display} on a "
                        f"percentage axis. Either the axis is wrong or the "
                        f"figure is.")
            return


def _check_waterfall(spec: ChartSpec, result: Validation) -> None:
    """Start plus the deltas must equal the end — computed here, not asserted."""
    points = [p for p in spec.all_points()]
    if len(points) < 3:
        result.fail(f"Waterfall {spec.spec_id!r} needs a start, at least one "
                    f"movement and an end.")
        return
    if any(p.is_missing for p in points):
        result.fail(f"Waterfall {spec.spec_id!r} contains a value that is not "
                    f"reported, so the bridge cannot be shown to reconcile.")
        return

    start, end = points[0].value or 0.0, points[-1].value or 0.0
    movements = sum(p.value or 0.0 for p in points[1:-1])
    if abs(start + movements - end) > max(TOLERANCE, abs(end) * 1e-6):
        result.fail(
            f"Waterfall {spec.spec_id!r} does not reconcile: the opening "
            f"balance and the movements shown do not sum to the closing "
            f"balance. A bridge that does not add up is worse than no bridge.")


def _disclose(spec: ChartSpec, evidence: EvidenceIndex,
              result: Validation) -> None:
    items = evidence.resolve(spec.evidence_ids)
    if any(i.needs_review for i in items):
        result.warn(f"Chart {spec.spec_id!r} includes figures read from an "
                    f"image; the caption discloses it.")
    contested = [i for i in items if i.is_contested]
    if contested:
        result.warn(f"Chart {spec.spec_id!r} plots {len(contested)} disputed "
                    f"value(s); the caption discloses it.")
    assumptions = [i for i in items if i.origin == "user_assumption"]
    if assumptions:
        result.warn(f"Chart {spec.spec_id!r} rests on {len(assumptions)} stated "
                    f"assumption(s).")


# ============================================================== diagrams
def validate_diagram(spec: DiagramSpec, evidence: EvidenceIndex) -> Validation:
    result = Validation()

    if not spec.nodes:
        return result.fail(f"Diagram {spec.spec_id!r} has no elements.")
    if not spec.caption:
        result.fail(f"Diagram {spec.spec_id!r} has no caption.")

    ids = {n.node_id for n in spec.nodes}
    for node in spec.nodes:
        if node.evidence_id and evidence.get(node.evidence_id) is None:
            result.fail(f"Node {node.node_id!r} cites {node.evidence_id!r}, "
                        f"which does not exist.")
        if node.parent_id and node.parent_id not in ids:
            result.fail(f"Node {node.node_id!r} names a parent "
                        f"{node.parent_id!r} that is not in the diagram.")
        if not node.label:
            result.fail(f"Node {node.node_id!r} has no label.")

    for edge in spec.edges:
        for end in (edge.from_id, edge.to_id):
            if end not in ids:
                result.fail(f"An edge names {end!r}, which is not a node in "
                            f"this diagram.")

    if spec.diagram_type in ("timeline", "milestone_track"):
        dated = [n for n in spec.nodes if n.at]
        if len(dated) < 2:
            result.fail(f"Timeline {spec.spec_id!r} has {len(dated)} dated "
                        f"element(s); a timeline needs at least two.")
        undated = [n for n in spec.nodes if not n.at]
        if undated:
            result.warn(f"{len(undated)} element(s) on {spec.spec_id!r} have no "
                        f"date and are listed rather than placed.")

    if spec.diagram_type in ("risk_matrix", "two_by_two"):
        unplaced = [n for n in spec.nodes if n.row is None or n.column is None]
        if len(unplaced) == len(spec.nodes):
            result.fail(f"Matrix {spec.spec_id!r} has no element with both "
                        f"coordinates, so nothing can be placed.")
        elif unplaced:
            result.warn(f"{len(unplaced)} element(s) on {spec.spec_id!r} are "
                        f"unscored and are listed beside the matrix.")

    if spec.diagram_type == "value_driver_tree":
        roots = [n for n in spec.nodes if not n.parent_id]
        if len(roots) != 1:
            result.fail(f"A value-driver tree needs exactly one root; "
                        f"{spec.spec_id!r} has {len(roots)}.")

    if not result.ok:
        log.info("diagram %s rejected: %s", spec.spec_id, result.summary)
    return result


# ================================================================ tables
def validate_table(spec: TableSpec, evidence: EvidenceIndex) -> Validation:
    result = Validation()

    if not spec.columns:
        return result.fail(f"Table {spec.spec_id!r} has no columns.")
    if not spec.rows:
        return result.fail(f"Table {spec.spec_id!r} has no rows.")

    width = len(spec.columns)
    for index, row in enumerate(spec.rows):
        if len(row) != width:
            result.fail(f"Row {index + 1} of {spec.spec_id!r} has {len(row)} "
                        f"cells for {width} columns.")

    if spec.row_evidence_ids:
        if len(spec.row_evidence_ids) != len(spec.rows):
            result.fail(f"Table {spec.spec_id!r} has "
                        f"{len(spec.row_evidence_ids)} row provenance entries "
                        f"for {len(spec.rows)} rows.")
        unknown = evidence.unknown(spec.row_evidence_ids)
        if unknown:
            result.fail(f"Table {spec.spec_id!r} cites {len(unknown)} evidence "
                        f"id(s) that do not exist.")

    if spec.is_truncated and not spec.truncation_note():
        result.fail(f"Table {spec.spec_id!r} shows a subset without saying so.")
    if spec.is_truncated:
        result.warn(spec.truncation_note())

    return result


def first_failure(*validations: Validation) -> Optional[str]:
    for validation in validations:
        if not validation.ok:
            return validation.summary
    return None


def collect(validations: Sequence[Validation]) -> Validation:
    combined = Validation()
    for validation in validations:
        combined.errors.extend(validation.errors)
        combined.warnings.extend(validation.warnings)
    combined.ok = not combined.errors
    return combined
