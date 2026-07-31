"""What every renderer returns, and the helpers all four share.

`element_boxes` is the part that matters beyond rendering: each renderer reports
the geometry and text it actually laid out, and `app/quality/overflow.py` checks
those boxes rather than re-opening the file and guessing. A renderer knows what
it drew; a critic reading the file afterwards has to infer it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class MeasuredBox(BaseModel):
    """One laid-out element, as the renderer placed it."""

    page_id: str = ""
    name: str = ""
    left_in: float = 0.0
    top_in: float = 0.0
    width_in: float = 0.0
    height_in: float = 0.0
    text: str = ""
    font_pt: Optional[float] = None
    is_placeholder: bool = False

    @property
    def right_in(self) -> float:
        return self.left_in + self.width_in

    @property
    def bottom_in(self) -> float:
        return self.top_in + self.height_in

    @property
    def area_in2(self) -> float:
        return self.width_in * self.height_in

    def overlaps(self, other: "MeasuredBox") -> float:
        """Overlapping area in square inches. Zero when they do not intersect."""
        dx = min(self.right_in, other.right_in) - max(self.left_in, other.left_in)
        dy = min(self.bottom_in, other.bottom_in) - max(self.top_in, other.top_in)
        return dx * dy if dx > 0 and dy > 0 else 0.0


class RenderResult(BaseModel):
    path: Path
    page_count: int = 0
    element_boxes: list[MeasuredBox] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def suffix(self) -> str:
        return self.path.suffix.lstrip(".")


def truncation_suffix(spec) -> str:
    """The "showing N of M" note, or nothing. Shared so all four formats agree."""
    return getattr(spec, "truncation_note", lambda: "")()
