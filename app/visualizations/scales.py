"""Axis arithmetic, separate from anything that draws.

Both chart backends need the same answers — where does the axis start, what are
the tick values, where does a value sit in pixels — and a chart whose PNG and
SVG disagree about its own scale is worse than either alone. Keeping this pure
also makes it testable without rendering anything.

The "nice numbers" algorithm is the standard 1-2-5 progression. It matters more
than it sounds: an axis topping out at 1,237,000 tells a reader the maximum is
precise, and an axis topping out at 1,500,000 tells them it is a round bound.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class Scale:
    minimum: float
    maximum: float
    ticks: tuple[float, ...]

    @property
    def span(self) -> float:
        return (self.maximum - self.minimum) or 1.0

    def position(self, value: float) -> float:
        """`value` as a 0.0-1.0 fraction of the axis."""
        return (value - self.minimum) / self.span

    def clamp(self, value: float) -> float:
        return max(self.minimum, min(self.maximum, value))


def nice_scale(values: Sequence[Optional[float]], *, target_ticks: int = 5,
               include_zero: bool = True,
               is_percentage: bool = False) -> Scale:
    """A rounded axis covering `values`.

    Missing values are skipped rather than treated as zero — a series with one
    unreported figure must not gain a phantom zero that drags the axis down and
    makes every other bar look bigger.
    """
    present = [v for v in values if v is not None]
    if not present:
        return Scale(0.0, 1.0, (0.0, 1.0))

    low, high = min(present), max(present)
    if is_percentage:
        # A percentage axis reads wrong when it does not start at zero, and a
        # 0-100 axis is what a reader assumes unless the data exceeds it.
        return Scale(0.0, max(100.0, _ceil_nice(high)),
                     tuple(float(t) for t in (0, 25, 50, 75, 100))
                     if high <= 100 else _ticks(0.0, _ceil_nice(high),
                                                target_ticks))

    if include_zero:
        low, high = min(0.0, low), max(0.0, high)
    if low == high:
        # A single distinct value still needs an axis with extent.
        magnitude = abs(low) or 1.0
        low, high = low - magnitude * 0.5, high + magnitude * 0.5

    step = _step(low, high, target_ticks)
    minimum = math.floor(low / step) * step
    maximum = math.ceil(high / step) * step
    return Scale(minimum, maximum, _ticks(minimum, maximum, target_ticks, step))


def _step(low: float, high: float, target_ticks: int) -> float:
    raw = (high - low) / max(target_ticks, 1)
    if raw <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 2.5, 5, 10):
        if raw <= magnitude * multiple:
            return magnitude * multiple
    return magnitude * 10


def _ticks(minimum: float, maximum: float, target_ticks: int,
           step: Optional[float] = None) -> tuple[float, ...]:
    step = step or _step(minimum, maximum, target_ticks)
    out: list[float] = []
    value = minimum
    # Guard against a pathological step producing an unbounded loop.
    for _ in range(200):
        if value > maximum + step * 1e-9:
            break
        out.append(round(value, 10))
        value += step
    return tuple(out)


def _ceil_nice(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    for multiple in (1, 1.5, 2, 2.5, 5, 10):
        if value <= magnitude * multiple:
            return magnitude * multiple
    return magnitude * 10


def tick_label(value: float, *, is_percentage: bool = False,
               currency: Optional[str] = None) -> str:
    """Abbreviate long axis labels; a full euro figure per gridline is noise."""
    if is_percentage:
        return f"{value:g}%"

    magnitude = abs(value)
    if magnitude >= 1_000_000_000:
        text = f"{value / 1_000_000_000:g}bn"
    elif magnitude >= 1_000_000:
        text = f"{value / 1_000_000:g}m"
    elif magnitude >= 10_000:
        text = f"{value / 1_000:g}k"
    else:
        text = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"
    return f"{currency} {text}" if currency else text


def stacked_totals(series_values: Sequence[Sequence[Optional[float]]]
                   ) -> list[Optional[float]]:
    """Column totals for a stacked chart.

    A column containing a missing value has no honest total, so it is `None`
    rather than the sum of the parts that happen to be known — which would
    understate it while looking authoritative.
    """
    if not series_values:
        return []
    totals: list[Optional[float]] = []
    for index in range(len(series_values[0])):
        column = [values[index] for values in series_values]
        totals.append(None if any(v is None for v in column)
                      else float(sum(v or 0.0 for v in column)))
    return totals
