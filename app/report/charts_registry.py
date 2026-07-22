"""The chart builders a `ChartBlock` is allowed to name.

An explicit dictionary rather than `getattr(charts, block.builder)`. Once a
report's content can be revised through the model — and a revision op can add a
section — `builder` stops being a string the code chose and becomes a string
that arrived from outside. `getattr` on that is an arbitrary-call primitive
against everything importable in `charts`, including `_save`, and would only
need one prompt injection in an uploaded file to reach.

A dict cannot be walked out of. An unknown name resolves to `None`, the caller
records a warning, and the report renders without that chart — which is the
§21.17 rule: surface the gap, never fail silently and never guess.
"""
from __future__ import annotations

from typing import Callable, Optional

from app.generators import charts

#: Stable name -> builder. The names are part of the stored content format, so
#: renaming one is a schema change: old versions on disk still reference it.
CHART_BUILDERS: dict[str, Callable] = {
    "risk_heatmap": charts.risk_heatmap,
    "workstream_progress": charts.workstream_progress,
    "overdue_by_workstream": charts.overdue_by_workstream,
    "risks_by_workstream": charts.risks_by_workstream,
    "tasks_by_status": charts.tasks_by_status,
    "milestone_timeline": charts.milestone_timeline,
    "day_1_readiness": charts.day_1_readiness,
    "budget_vs_actual": charts.budget_vs_actual,
    "budget_variance": charts.budget_variance,
    "synergy_target_vs_realized": charts.synergy_target_vs_realized,
}


def resolve(name: str) -> Optional[Callable]:
    """The builder, or `None` if the name is not one we publish."""
    return CHART_BUILDERS.get(name)


def is_known(name: str) -> bool:
    return name in CHART_BUILDERS
