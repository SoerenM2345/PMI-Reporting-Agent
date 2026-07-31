"""Turning a plan into content: prose, titles, visuals and calculations.

    narrative_writer.write_page(page, context, plan)  -> guarded prose
    title_writer.write_titles(deliverable, context)   -> all titles, one call
    chart_planner.build_visuals(page, context)        -> validated specs
    calculator.execute(requests, evidence)            -> figures, or refusals

Everything authored here passes `app/report/guard.py` before it is kept: a figure
that is not in the evidence does not reach a page.
"""
from __future__ import annotations

from app.generation.calculator import (
    CalculationRequest,
    CalculationResult,
    as_evidence,
    execute,
)
from app.generation.chart_planner import VisualOutcome, build_visuals
from app.generation.narrative_writer import write_page
from app.generation.title_writer import write_titles

__all__ = [
    "CalculationRequest",
    "CalculationResult",
    "VisualOutcome",
    "as_evidence",
    "build_visuals",
    "execute",
    "write_page",
    "write_titles",
]
