"""One place that knows which renderer serves which format.

Replaces `app/project/exporting.py::_BUILDERS`, which additionally re-parsed a
draft's Markdown back into a document model on the way — a lossy round trip that
discarded cell provenance, emphasis and column types before rendering.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from app.renderers.common import RenderResult

log = logging.getLogger("pmi.renderers.registry")

#: Aliases a user or an API caller might send.
ALIASES: dict[str, str] = {
    "pptx": "pptx", "powerpoint": "pptx", "ppt": "pptx", "deck": "pptx",
    "slides": "pptx", "presentation": "pptx",
    "docx": "docx", "word": "docx", "doc": "docx", "document": "docx",
    "pdf": "pdf",
    "html": "html", "dashboard": "html", "web": "html", "htm": "html",
    "chart": "chart", "charts": "chart", "graph": "chart", "png": "chart",
}


def normalize(fmt: Optional[str]) -> str:
    return ALIASES.get((fmt or "").strip().casefold(), "pptx")


def supported() -> list[str]:
    return ["pptx", "docx", "pdf", "html"]


def renderer(fmt: str) -> Callable[..., RenderResult]:
    """The render function for `fmt`. Imported lazily so a missing optional
    dependency only breaks the format that needs it."""
    name = normalize(fmt)
    if name == "chart":
        raise ValueError("standalone charts use the chart renderer, not the document registry")
    if name == "pptx":
        from app.renderers.pptx import render
    elif name == "docx":
        from app.renderers.docx import render
    elif name == "pdf":
        from app.renderers.pdf import render
    else:
        from app.renderers.html import render
    return render


def render(deliverable, context, out_dir: Path, fmt: str) -> RenderResult:
    return renderer(fmt)(deliverable, context, out_dir)


def render_all(deliverable, context, out_dir: Path,
               formats: list[str]) -> list[RenderResult]:
    """Render several formats from one plan, so they cannot disagree."""
    results: list[RenderResult] = []
    for fmt in formats:
        try:
            results.append(render(deliverable, context, out_dir, fmt))
        except Exception as exc:                               # noqa: BLE001
            # One format failing must not lose the others: a user who asked for
            # a deck and a PDF should get the deck.
            log.exception("could not render %s", fmt)
            results.append(RenderResult(
                path=Path(out_dir) / f"FAILED.{normalize(fmt)}", page_count=0,
                warnings=[f"The {normalize(fmt)} version could not be produced "
                          f"({type(exc).__name__}: {exc})."]))
    return results
