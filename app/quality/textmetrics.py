"""Measure how much room text actually needs.

python-pptx cannot answer this. A run in a freshly cloned placeholder reports
`font.size is None` and `font.name is None` — correctly, because it inherits —
so there is nothing to measure against without resolving the inheritance chain
first. `app/templates/extract_layouts.py` already did that resolution, so a
`LayoutSlot` carries the effective point size and this module only has to lay
text out at it.

**This is deliberately pessimistic.** A 6% width margin is added, and wrapping is
computed on whole words. Over-estimating means occasionally flagging text that
would have just fitted; under-estimating means shipping a deck with a title
running off the slide. Only one of those is discoverable by the person who
receives it.

The font used for measurement is not necessarily the font the reader sees: Aptos
is a Microsoft font and is usually absent from a build host, so measurement falls
back to matplotlib's bundled DejaVuSans, which is wider than Aptos at the same
size. That bias is in the safe direction and is stated here so nobody mistakes
these numbers for exact.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

log = logging.getLogger("pmi.quality.textmetrics")

#: Points per inch.
PT_PER_IN = 72.0
#: Added to every measured width. See the module docstring.
SAFETY_MARGIN = 1.06
#: Below this, text on a slide is not readable at the back of a room.
MIN_SLIDE_PT = 9.0
#: Below this, body text in a document is uncomfortable.
MIN_DOCUMENT_PT = 8.0


@dataclass(frozen=True)
class TextExtent:
    width_in: float
    height_in: float
    line_count: int
    #: The lines as they would wrap, for a developer diagnosing an overflow.
    lines: tuple[str, ...] = ()

    def overflows(self, box_width_in: float, box_height_in: float) -> bool:
        return self.height_in > box_height_in or self.width_in > box_width_in


@lru_cache(maxsize=8)
def _font(size_pt: float, bold: bool = False):
    """A PIL font at `size_pt`, from the best available real typeface."""
    from PIL import ImageFont

    for path in _font_paths(bold):
        try:
            # PIL sizes in pixels; at 72 dpi a pixel is a point.
            return ImageFont.truetype(str(path), int(round(size_pt)))
        except (OSError, ValueError):
            continue
    log.debug("no measurable font found; falling back to PIL's default")
    return ImageFont.load_default()


def _font_paths(bold: bool) -> list[Path]:
    candidates: list[Path] = []
    stem = "Aptos"
    for directory in (Path("/System/Library/Fonts"), Path("/Library/Fonts"),
                      Path.home() / "Library/Fonts", Path("/usr/share/fonts")):
        if directory.is_dir():
            pattern = f"{stem}*Bold*.ttf" if bold else f"{stem}*.ttf"
            candidates.extend(sorted(directory.rglob(pattern))[:1])
    try:
        import matplotlib

        bundled = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
        candidates.append(bundled / ("DejaVuSans-Bold.ttf" if bold
                                     else "DejaVuSans.ttf"))
    except Exception:                                          # noqa: BLE001
        pass
    return [path for path in candidates if path.is_file()]


def measured_font_name() -> str:
    """Which typeface the measurements were taken in. Never assume it is Aptos."""
    paths = _font_paths(False)
    return paths[0].stem if paths else "PIL default"


def text_width_in(text: str, *, size_pt: float, bold: bool = False) -> float:
    if not text:
        return 0.0
    font = _font(size_pt, bold)
    try:
        width = font.getlength(text)
    except AttributeError:                     # very old PIL
        width = font.getsize(text)[0]
    return (width / PT_PER_IN) * SAFETY_MARGIN


def measure(text: str, *, size_pt: float, max_width_in: float,
            bold: bool = False, line_spacing: float = 1.2) -> TextExtent:
    """Lay `text` out in a column `max_width_in` wide.

    Wrapping is on whole words, because that is what every renderer here does.
    A single word too long for the column is reported as overflowing rather than
    silently broken: a hyphenated split would hide the problem.
    """
    if not text.strip():
        return TextExtent(0.0, 0.0, 0, ())

    line_height = (size_pt * line_spacing) / PT_PER_IN
    lines: list[str] = []

    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if text_width_in(candidate, size_pt=size_pt, bold=bold) <= max_width_in:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)

    widest = max((text_width_in(line, size_pt=size_pt, bold=bold)
                  for line in lines), default=0.0)
    return TextExtent(width_in=widest,
                      height_in=line_height * len(lines),
                      line_count=len(lines),
                      lines=tuple(lines))


def fits(text: str, *, size_pt: float, box_width_in: float,
         box_height_in: float, bold: bool = False) -> bool:
    extent = measure(text, size_pt=size_pt, max_width_in=box_width_in, bold=bold)
    return not extent.overflows(box_width_in, box_height_in)


def largest_size_that_fits(text: str, *, box_width_in: float,
                           box_height_in: float, ceiling_pt: float,
                           floor_pt: float = MIN_SLIDE_PT) -> Optional[float]:
    """The biggest readable size `text` fits at, or `None` if it never does.

    Used by the repair loop: shrinking type is preferable to truncating a
    finding, but only down to the point where a reader can still read it.
    """
    size = ceiling_pt
    while size >= floor_pt:
        if fits(text, size_pt=size, box_width_in=box_width_in,
                box_height_in=box_height_in):
            return round(size, 1)
        size -= 0.5
    return None


def shorten_to_fit(text: str, *, size_pt: float, box_width_in: float,
                   box_height_in: float) -> str:
    """Trim `text` at a sentence boundary until it fits.

    Cutting mid-clause reads as a bug and undermines the rest of the page, so
    this prefers sentence boundaries and only falls back to an ellipsis.
    """
    if fits(text, size_pt=size_pt, box_width_in=box_width_in,
            box_height_in=box_height_in):
        return text

    sentences = _sentences(text)
    while len(sentences) > 1:
        sentences.pop()
        candidate = " ".join(sentences)
        if fits(candidate, size_pt=size_pt, box_width_in=box_width_in,
                box_height_in=box_height_in):
            return candidate

    words = text.split()
    while len(words) > 4:
        words.pop()
        candidate = " ".join(words) + "…"
        if fits(candidate, size_pt=size_pt, box_width_in=box_width_in,
                box_height_in=box_height_in):
            return candidate
    return text


def _sentences(text: str) -> list[str]:
    import re

    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [part for part in parts if part]


# --------------------------------------------------------------- contrast
def readable(foreground: str, background: str, *,
             large_text: bool = False) -> bool:
    """WCAG 1.4.3: 4.5:1 for body text, 3:1 for large text."""
    from app.templates.brand_system import contrast_ratio

    return contrast_ratio(foreground, background) >= (3.0 if large_text else 4.5)
