"""Render a `Deliverable` into a file. Four formats, one design language.

    registry.render(deliverable, context, out_dir, "pptx") -> RenderResult

Each renderer decides nothing: every string was written, every figure resolved
and every visual validated before it ran. All four read the same `BrandSystem`,
which was measured from the PowerPoint master — so the deck, the document, the
PDF and the dashboard are one design language rather than four approximations.
"""
from __future__ import annotations

from app.renderers.common import MeasuredBox, RenderResult
from app.renderers.registry import normalize, render, render_all, renderer, supported

__all__ = ["MeasuredBox", "RenderResult", "normalize", "render", "render_all",
           "renderer", "supported"]
