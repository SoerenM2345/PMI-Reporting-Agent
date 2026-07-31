"""The template system: read a `.pptx` master, derive a cross-format brand.

`template_registry.load()` is the public entry point. It returns a
`TemplateReference` carrying a `LayoutCatalog` (which native layout to use for
a given composition) and a `BrandSystem` (the colours, type scale, spacing and
chart tokens that Word, PDF and HTML share with the deck).

Nothing in here renders. Nothing in here hard-codes a brand value that the
template itself states — swap the master and the whole design language moves.
"""
from __future__ import annotations

from app.templates.brand_system import BrandSystem
from app.templates.extract_layouts import LayoutSlot, TemplateLayout
from app.templates.layout_catalog import LayoutCatalog
from app.templates.template_registry import TemplateReference, default, load

__all__ = [
    "BrandSystem",
    "LayoutCatalog",
    "LayoutSlot",
    "TemplateLayout",
    "TemplateReference",
    "default",
    "load",
]
