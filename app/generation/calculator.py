"""Calculations on demand, requested by the model and executed by Python.

The old pipeline computed every PMI figure it knew how to compute, whether or
not the report needed it. That is wasteful and, worse, it shaped the report:
having computed a Day 1 readiness ratio, the planner put it on a slide.

Here the model asks. It names an operation and the evidence to apply it to, and
gets back a validated figure as a new evidence item — which means the number
enters the numeric corpus and may then be quoted. A calculation it did not ask
for does not exist.

The refusals matter as much as the results. A comparison across two currencies,
a ratio with a zero denominator, a sum over a field that is missing on half the
records: each is refused with a reason that goes **on the page**, because
"EUR 1.2m against USD 900k is not a meaningful comparison" is information the
reader needs, and silently dropping the analysis leaves them wondering why the
page is thin.

`app/agent/calculations.py` remains the authority for the five domain
derivations (risk scores, budget variances, synergy remainders, milestone
delays, overdue flags) and runs before evidence is projected. This is only for
ad-hoc analytical asks.
"""
from __future__ import annotations

import logging
import statistics
from typing import Callable, Optional, Sequence

from pydantic import BaseModel, Field

from app.evidence.model import Derivation, EvidenceIndex, EvidenceItem
from app.report import format as fmt

log = logging.getLogger("pmi.generation.calculator")

#: A document that needs more than this many ad-hoc calculations is doing
#: analysis the data model should be doing.
MAX_REQUESTS = 24

CalcOp = str  # constrained by the Literal on CalculationRequest


class CalculationRequest(BaseModel):
    """What the model may ask for. Inputs are evidence ids — never literals."""

    calculation_id: str = ""
    op: str = Field(
        default="sum",
        description="One of: sum, difference, product, ratio, percent_of, "
                    "percent_change, share_of_total, mean, median, min, max, "
                    "count, count_where, variance, weighted_mean, "
                    "cumulative, days_between, run_rate.")
    input_evidence_ids: list[str] = Field(default_factory=list)
    value_field: str = Field(
        default="value",
        description="Which field of each input record to read.")
    label: str = Field(default="", description="What to call the result.")
    reason: str = Field(
        default="",
        description="Why the document needs this. Recorded in the audit trail.")
    unit_hint: Optional[str] = None


class CalculationRequests(BaseModel):
    calculations: list[CalculationRequest] = Field(default_factory=list)


class CalculationResult(BaseModel):
    calculation_id: str = ""
    label: str = ""
    value: Optional[float] = None
    display: str = ""
    unit: Optional[str] = None
    currency: Optional[str] = None
    period: Optional[str] = None
    derivation: Optional[Derivation] = None
    refused: bool = False
    refusal_reason: str = ""

    @property
    def evidence_id(self) -> str:
        return f"ev:calc:{self.calculation_id}"


# ------------------------------------------------------------------ the ops
def _sum(values: Sequence[float]) -> float:
    return float(sum(values))


def _difference(values: Sequence[float]) -> Optional[float]:
    return None if len(values) < 2 else float(values[0] - sum(values[1:]))


def _product(values: Sequence[float]) -> float:
    result = 1.0
    for value in values:
        result *= value
    return result


def _ratio(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2 or values[1] == 0:
        return None
    return float(values[0] / values[1])


def _percent_of(values: Sequence[float]) -> Optional[float]:
    ratio = _ratio(values)
    return None if ratio is None else ratio * 100.0


def _percent_change(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2 or values[0] == 0:
        return None
    return float((values[1] - values[0]) / abs(values[0]) * 100.0)


def _share_of_total(values: Sequence[float]) -> Optional[float]:
    total = sum(values)
    if not total:
        return None
    return float(values[0] / total * 100.0)


def _cumulative(values: Sequence[float]) -> float:
    return float(sum(values))


#: A closed dict, deliberately. `getattr` over a model-supplied operation name
#: is how an LLM output becomes arbitrary code execution.
OPS: dict[str, Callable[[Sequence[float]], Optional[float]]] = {
    "sum": _sum,
    "difference": _difference,
    "product": _product,
    "ratio": _ratio,
    "percent_of": _percent_of,
    "percent_change": _percent_change,
    "share_of_total": _share_of_total,
    "mean": lambda v: float(statistics.fmean(v)) if v else None,
    "median": lambda v: float(statistics.median(v)) if v else None,
    "min": lambda v: float(min(v)) if v else None,
    "max": lambda v: float(max(v)) if v else None,
    "count": lambda v: float(len(v)),
    "count_where": lambda v: float(len(v)),
    "variance": lambda v: float(statistics.pvariance(v)) if len(v) > 1 else None,
    "weighted_mean": lambda v: float(statistics.fmean(v)) if v else None,
    "cumulative": _cumulative,
}

#: Operations whose result is a percentage regardless of the inputs' unit.
_PERCENT_OPS = frozenset({"percent_of", "percent_change", "share_of_total"})
#: Operations that produce a dimensionless number.
_UNITLESS_OPS = frozenset({"ratio", "count", "count_where"})


def execute(requests: Sequence[CalculationRequest], evidence: EvidenceIndex
            ) -> tuple[list[CalculationResult], list[str]]:
    """Run the supported requests. Returns results and warnings; never raises."""
    results: list[CalculationResult] = []
    warnings: list[str] = []

    if len(requests) > MAX_REQUESTS:
        warnings.append(f"{len(requests)} calculations were requested; only the "
                        f"first {MAX_REQUESTS} were run.")
        requests = requests[:MAX_REQUESTS]

    for order, request in enumerate(requests, start=1):
        result = _run(request, evidence, order)
        results.append(result)
        if result.refused:
            warnings.append(f"{result.label or result.calculation_id}: "
                            f"{result.refusal_reason}")
    return results, warnings


def _run(request: CalculationRequest, evidence: EvidenceIndex,
         order: int) -> CalculationResult:
    calculation_id = request.calculation_id or f"c{order:02d}"
    label = request.label or f"{request.op.replace('_', ' ')} result"
    result = CalculationResult(calculation_id=calculation_id, label=label)

    operation = OPS.get(request.op)
    if operation is None:
        return _refuse(result, f"{request.op!r} is not a supported operation.")

    items = evidence.resolve(request.input_evidence_ids)
    unknown = evidence.unknown(request.input_evidence_ids)
    if unknown:
        return _refuse(result, f"{len(unknown)} of the inputs do not exist "
                               f"({', '.join(unknown[:3])}).")
    if not items:
        return _refuse(result, "no inputs were given.")

    currencies = {i.currency for i in items if i.currency}
    if len(currencies) > 1 and request.op not in _UNITLESS_OPS:
        return _refuse(
            result,
            f"the inputs are in different currencies "
            f"({', '.join(sorted(currencies))}), so this comparison would not "
            f"be meaningful. Convert them to one currency first.")

    units = {i.unit for i in items if i.unit}
    if len(units) > 1 and request.op not in _UNITLESS_OPS | _PERCENT_OPS:
        return _refuse(result, f"the inputs are in different units "
                               f"({', '.join(sorted(str(u) for u in units))}).")

    values: list[float] = []
    missing: list[str] = []
    for item in items:
        raw = _read(item, request.value_field)
        if raw is None:
            missing.append(item.label or item.evidence_id)
            continue
        values.append(raw)

    if not values:
        return _refuse(result, f"none of the {len(items)} input record(s) report "
                               f"a figure for {request.value_field!r}.")
    if missing and request.op in ("sum", "cumulative", "share_of_total"):
        # A sum over a partly-reported set is not a total, and presenting it as
        # one is the single most common way an integration report understates a
        # number.
        return _refuse(
            result,
            f"{len(missing)} of {len(items)} input record(s) report no figure "
            f"({', '.join(missing[:3])}), so this total would be incomplete "
            f"while looking complete.")

    try:
        value = operation(values)
    except (ArithmeticError, statistics.StatisticsError, TypeError) as exc:
        return _refuse(result, f"the calculation could not be performed ({exc}).")
    if value is None:
        return _refuse(result, "the inputs do not support this calculation "
                               "(a divisor may be zero, or too few values).")

    unit, currency = _result_unit(request, items)
    periods = {i.period for i in items if i.period}
    result.value = float(value)
    result.unit = unit
    result.currency = currency
    result.period = next(iter(periods)) if len(periods) == 1 else None
    result.display = _display(result)
    result.derivation = Derivation(
        operation=request.op,
        input_evidence_ids=[i.evidence_id for i in items],
        formula=_formula(request, len(values)),
        calculation_id=calculation_id,
    )
    if missing:
        result.label = f"{result.label} (of {len(values)} reported)"
    return result


def _result_unit(request: CalculationRequest,
                 items: Sequence[EvidenceItem]) -> tuple[Optional[str], Optional[str]]:
    if request.op in _PERCENT_OPS:
        return "%", None
    if request.op in _UNITLESS_OPS:
        return request.unit_hint, None
    units = {i.unit for i in items if i.unit}
    currencies = {i.currency for i in items if i.currency}
    return (next(iter(units)) if len(units) == 1 else request.unit_hint,
            next(iter(currencies)) if len(currencies) == 1 else None)


def _read(item: EvidenceItem, field: str) -> Optional[float]:
    raw = item.value if field in ("", "value") else item.payload.get(field)
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _display(result: CalculationResult) -> str:
    if result.value is None:
        return fmt.NOT_REPORTED
    text = fmt.num(result.value)
    if result.unit == "%":
        return f"{text}%"
    if result.currency:
        return f"{result.currency} {text}"
    return f"{result.unit} {text}".strip() if result.unit else text


def _formula(request: CalculationRequest, count: int) -> str:
    field = request.value_field or "value"
    return {
        "sum": f"sum of {field} over {count} records",
        "difference": f"first {field} minus the rest",
        "ratio": f"{field}[1] ÷ {field}[2]",
        "percent_of": f"{field}[1] ÷ {field}[2] × 100",
        "percent_change": f"({field}[2] − {field}[1]) ÷ |{field}[1]| × 100",
        "share_of_total": f"{field}[1] ÷ sum({field}) × 100",
        "mean": f"mean of {field} over {count} records",
        "median": f"median of {field} over {count} records",
    }.get(request.op, f"{request.op} of {field} over {count} records")


def _refuse(result: CalculationResult, reason: str) -> CalculationResult:
    result.refused = True
    result.refusal_reason = reason
    result.display = fmt.NOT_REPORTED
    log.info("refused calculation %s: %s", result.calculation_id, reason)
    return result


def as_evidence(results: Sequence[CalculationResult],
                evidence: EvidenceIndex) -> list[EvidenceItem]:
    """Add the successful results to the index so their figures may be quoted."""
    added: list[EvidenceItem] = []
    for result in results:
        if result.refused or result.value is None:
            continue
        item = EvidenceItem(
            evidence_id=result.evidence_id,
            kind="calculation",
            origin="computed_value",
            label=result.label,
            statement=f"{result.label}: {result.display}.",
            value=result.value,
            display=result.display,
            unit=result.unit,
            currency=result.currency,
            period=result.period,
            derivation=result.derivation,
            sources=_inherited_sources(result, evidence),
        )
        item.search_text = f"{result.label} {result.display}"
        added.append(evidence.add(item))
    return added


def _inherited_sources(result: CalculationResult,
                       evidence: EvidenceIndex) -> list:
    """A computed figure cites what it was computed from — not one file."""
    seen: list = []
    identities: set[int] = set()
    for evidence_id in (result.derivation.input_evidence_ids
                        if result.derivation else []):
        item = evidence.get(evidence_id)
        if item is None:
            continue
        for reference in item.sources:
            if id(reference) not in identities:
                identities.add(id(reference))
                seen.append(reference)
    return seen
