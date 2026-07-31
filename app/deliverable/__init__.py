"""The planned artifact, and the engine that plans it.

`engine.build(context)` runs the whole pipeline and returns a `Deliverable` —
the four renderers' single input. `store` versions it append-only;
`fingerprint` says when it has gone stale and, usefully, exactly which pages.
"""
from __future__ import annotations

from app.deliverable.engine import PlanningError, build, regenerate_pages
from app.deliverable.fingerprint import (
    ContextFingerprint,
    compute,
    is_stale,
    stale_pages,
    stale_reason,
)
from app.deliverable.model import (
    BulletsElement,
    ChartElement,
    Deliverable,
    DesignElement,
    DiagramElement,
    ImageElement,
    KpiRowElement,
    KpiTile,
    PageDesign,
    TableElement,
    TextElement,
)

__all__ = [
    "BulletsElement",
    "ChartElement",
    "ContextFingerprint",
    "Deliverable",
    "DesignElement",
    "DiagramElement",
    "ImageElement",
    "KpiRowElement",
    "KpiTile",
    "PageDesign",
    "PlanningError",
    "TableElement",
    "TextElement",
    "build",
    "compute",
    "is_stale",
    "regenerate_pages",
    "stale_pages",
    "stale_reason",
]
