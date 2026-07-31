"""Charts, diagrams and tables: specified by the model, resolved by Python.

    builder.build_chart(request, evidence)   -> ChartSpec   (values read here)
    validator.validate_chart(spec, evidence) -> Validation  (values checked here)
    charts.to_pptx_native / to_svg / to_png  -> drawn, three ways

A chart either has validated data behind every point or it is not a chart, and
the caller falls back to a table. There is no path that produces a caption over
empty space.
"""
from __future__ import annotations

from app.visualizations.builder import build_chart, build_diagram
from app.visualizations.specs import (
    ChartRequest,
    ChartSpec,
    DataPoint,
    DiagramRequest,
    DiagramSpec,
    TableSpec,
)
from app.visualizations.tables import build_table
from app.visualizations.validator import (
    Validation,
    validate_chart,
    validate_diagram,
    validate_table,
)

__all__ = [
    "ChartRequest",
    "ChartSpec",
    "DataPoint",
    "DiagramRequest",
    "DiagramSpec",
    "TableSpec",
    "Validation",
    "build_chart",
    "build_diagram",
    "build_table",
    "validate_chart",
    "validate_diagram",
    "validate_table",
]
