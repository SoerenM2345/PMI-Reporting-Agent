"""Turn raw layouts into addressable `TemplateLayout`s with named slots.

A renderer wants to say "put the message in the title and the chart in the left
column". It cannot say that to python-pptx, which offers only `placeholder_format.idx`
— and in this template `idx` is not a slot identity: the visual left-hand column
is `idx=10` on layout 30, `idx=10` on 53 (whose right column is `idx=15`, not 20)
and `idx=10` on 55 (whose remaining columns are 18/19/20). Ordering by `idx`
scrambles the columns; ordering by `left` does not.

`slide.shapes.title` is equally unusable here. **Fourteen of this template's
layouts — the whole Light Gray (36-42) and Pale Green (43-49) families — have no
`TITLE` placeholder at all.** Their heading is a `BODY` placeholder at the same
y as every other layout's title. `shapes.title` returns `None` on them, so any
renderer built on it silently loses the heading on a third of the deck. Slots are
therefore resolved by **role, then band, then geometry**, and callers address
`slot_id`.

Slot vocabulary: `title`, `subtitle`, `col1`..`colN`, `picture1`..`pictureN`,
`body`. Every layout that can carry a message exposes `title`.
"""
from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.templates.extract_theme import ThemePalette
from app.templates.inspect_pptx import RawLayout, RawPlaceholder, RawTemplate

log = logging.getLogger("pmi.templates.layouts")

LayoutRole = Literal["title", "divider", "content", "team", "qualification", "end"]
LayoutFamily = Literal["white", "light_gray", "pale_green", "black", "image"]

#: Text placeholders above this line are the heading band; below it they are
#: content columns. Measured: every content layout in the Deloitte master puts
#: its title at y=0.38 and its subtitle at y=0.67-0.75, and starts content at
#: y=1.84. Anything in between would be ambiguous, and nothing is.
HEADER_BAND_IN = 1.60

_FAMILY_PATTERNS: tuple[tuple[str, LayoutFamily], ...] = (
    ("full bleed image", "image"),
    ("light gray", "light_gray"),
    ("light grey", "light_gray"),
    ("pale green", "pale_green"),
    ("black", "black"),
)

_ROLE_PATTERNS: tuple[tuple[str, LayoutRole], ...] = (
    ("title slide", "title"),
    ("divider", "divider"),
    ("end slide", "end"),
    ("team profile", "team"),
    ("qualifications", "qualification"),
)


class LayoutSlot(BaseModel):
    """One addressable region of a layout, with its inherited text style."""

    slot_id: str
    ph_idx: Optional[int] = None
    ph_type: str = ""
    left_in: float = 0.0
    top_in: float = 0.0
    width_in: float = 0.0
    height_in: float = 0.0

    default_pt: float = 12.0
    default_color: str = "#222222"
    font_family: str = ""
    bullet_char: Optional[str] = None
    #: What may be placed here. Empty means "never target this slot" — the
    #: no-idx sentinel placeholders resolve that way.
    accepts: tuple[str, ...] = ()

    @property
    def area_in2(self) -> float:
        return round(self.width_in * self.height_in, 4)

    @property
    def is_addressable(self) -> bool:
        return bool(self.accepts)


class TemplateLayout(BaseModel):
    """A native layout, described well enough to fill without guessing."""

    #: Stable across renames and trailing whitespace: seven layouts in this
    #: template have trailing spaces, and `Title only - Black` differs from
    #: `Title Only` only by case. Anchoring on the index makes both harmless.
    layout_id: str
    index: int
    raw_name: str
    normalized_name: str
    role: LayoutRole
    family: LayoutFamily
    slots: list[LayoutSlot] = Field(default_factory=list)
    decorations: tuple[str, ...] = ()

    def slot(self, slot_id: str) -> Optional[LayoutSlot]:
        for candidate in self.slots:
            if candidate.slot_id == slot_id:
                return candidate
        return None

    @property
    def columns(self) -> int:
        """Addressable content columns.

        Excludes the no-idx sentinel placeholders on the qualification layouts:
        there is no safe way to target them, so counting them would promise a
        column the renderer cannot fill.
        """
        return len(self.column_slots)

    @property
    def column_slots(self) -> list[LayoutSlot]:
        return sorted(
            (s for s in self.slots
             if s.slot_id.startswith("col") and s.is_addressable),
            key=lambda s: (s.left_in, s.top_in),
        )

    @property
    def picture_slots(self) -> list[LayoutSlot]:
        return [s for s in self.slots if s.slot_id.startswith("picture")]

    @property
    def has_title_slot(self) -> bool:
        """Whether a *real* `TITLE` placeholder backs the title slot.

        False for the Light Gray and Pale Green families, whose heading is a
        `BODY` placeholder. The `title` slot still exists and still works — this
        flag exists so nothing reaches for `shapes.title`.
        """
        slot = self.slot("title")
        return slot is not None and slot.ph_type in ("TITLE", "CENTER_TITLE")

    @property
    def has_subtitle_slot(self) -> bool:
        return self.slot("subtitle") is not None

    @property
    def has_picture_slot(self) -> bool:
        return bool(self.picture_slots)

    @property
    def is_full_bleed(self) -> bool:
        return any(s.width_in >= 13.0 and s.height_in >= 7.0
                   for s in self.picture_slots)

    @property
    def has_thinkcell(self) -> bool:
        """A think-cell OLE object sits on the layout. It is never cloned onto a
        slide, so this is an audit flag: do not mutate this layout's part."""
        return any("think-cell" in name.casefold() for name in self.decorations)


def build(template: RawTemplate, palette: ThemePalette) -> list[TemplateLayout]:
    """Describe every layout in `template`, in file order."""
    layouts = [_layout(raw, palette) for raw in template.layouts]
    untitled = [lay.index for lay in layouts
                if lay.role in ("content", "divider") and lay.slot("title") is None]
    if untitled:
        log.warning("layouts %s expose no title slot; they cannot carry a message",
                    untitled)
    return layouts


# ---------------------------------------------------------------- internals
def _layout(raw: RawLayout, palette: ThemePalette) -> TemplateLayout:
    role = _role(raw.normalized_name)
    slots = _slots(raw, role, palette)
    return TemplateLayout(
        layout_id=f"{raw.index:02d}:{_slug(raw.raw_name)}",
        index=raw.index,
        raw_name=raw.raw_name,
        normalized_name=raw.normalized_name,
        role=role,
        family=_family(raw.normalized_name),
        slots=slots,
        decorations=raw.decorations,
    )


def _role(normalized: str) -> LayoutRole:
    for needle, role in _ROLE_PATTERNS:
        if normalized.startswith(needle):
            return role
    return "content"


def _family(normalized: str) -> LayoutFamily:
    for needle, family in _FAMILY_PATTERNS:
        if needle in normalized:
            return family
    return "white"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", " ".join(name.split()).casefold()).strip("-")


def _slots(raw: RawLayout, role: LayoutRole,
           palette: ThemePalette) -> list[LayoutSlot]:
    """Assign slot ids by role, then by band, then by rank.

    The banding only applies to `content`-role layouts. A cover's title sits at
    y=5.67 and a divider's at y=1.84 or y=3.39 — well inside what would be the
    "content" band — so those roles name their single text placeholder directly
    instead of measuring it.

    Within the heading band, the title is **the largest** text placeholder, not
    the topmost. In the Light Gray and Pale Green families the topmost is a 9pt
    bold eyebrow at y=0.38 and the real 28pt title sits *below* it at y=0.67 —
    the template says so itself, in prompt text this ranking never has to read.
    """
    pictures = sorted((ph for ph in raw.placeholders if ph.is_picture),
                      key=lambda p: (p.top_in, p.left_in))
    texts = [ph for ph in raw.placeholders if not ph.is_picture]
    styles = {id(ph): _style_for(ph, raw, palette) for ph in texts}

    def rank(ph: RawPlaceholder) -> tuple:
        # A real TITLE wins outright; then the larger type; then the higher box.
        return (not ph.is_title, -styles[id(ph)][0], ph.top_in, ph.left_in)

    slots: list[LayoutSlot] = []
    for order, ph in enumerate(pictures, start=1):
        slots.append(_slot(f"picture{order}", ph, raw, palette, ("image",)))

    if role in ("title", "divider"):
        ranked = sorted(texts, key=rank)
        for slot_id, ph in zip(("title", "subtitle"), ranked):
            slots.append(_slot(slot_id, ph, raw, palette, ("text",), styles[id(ph)]))
    elif role == "end":
        for ph in sorted(texts, key=lambda p: p.top_in)[:1]:
            slots.append(_slot("body", ph, raw, palette, ("text", "bullets"),
                               styles[id(ph)]))
    else:
        header = sorted((p for p in texts if p.top_in < HEADER_BAND_IN), key=rank)
        content = sorted((p for p in texts if p.top_in >= HEADER_BAND_IN),
                         key=lambda p: (p.left_in, p.top_in))
        for slot_id, ph in zip(("title", "subtitle"), header):
            slots.append(_slot(slot_id, ph, raw, palette, ("text",), styles[id(ph)]))
        for order, ph in enumerate(content, start=1):
            slots.append(_slot(f"col{order}", ph, raw, palette,
                               ("text", "bullets", "table", "chart",
                                "diagram", "image"), styles[id(ph)]))
    return slots


def _slot(slot_id: str, ph: RawPlaceholder, raw: RawLayout,
          palette: ThemePalette, accepts: tuple[str, ...],
          style: Optional[tuple[float, str, str, Optional[str]]] = None) -> LayoutSlot:
    style = style or _style_for(ph, raw, palette)
    return LayoutSlot(
        slot_id=slot_id,
        ph_idx=ph.ph_idx,
        ph_type=ph.ph_type,
        left_in=ph.left_in,
        top_in=ph.top_in,
        width_in=ph.width_in,
        height_in=ph.height_in,
        default_pt=style[0],
        default_color=style[1],
        font_family=style[2],
        bullet_char=style[3],
        # The no-idx sentinel cannot be addressed safely: there is no index to
        # look it up by and two of them share a name on the same layout.
        accepts=accepts if ph.is_addressable else (),
    )


def _style_for(ph: RawPlaceholder, raw: RawLayout, palette: ThemePalette
               ) -> tuple[float, str, str, Optional[str]]:
    """Resolve level-1 size, colour, font and bullet through the inheritance chain.

    Layout override -> master `titleStyle`/`bodyStyle` -> theme font. python-pptx
    resolves none of this: a run in a freshly cloned placeholder reports
    `font.size is None` and `font.name is None`, which is correct (it inherits)
    and useless for measuring whether the text will fit.
    """
    override = palette.layout_overrides.get(raw.index, {})
    # Index first: it names exactly this placeholder. Type is a fallback, and
    # on layouts carrying two BODY placeholders it can only describe one.
    level = override.get(f"idx{ph.ph_idx}") if ph.ph_idx is not None else None
    if level is None:
        key = {"TITLE": "title", "CENTER_TITLE": "ctrTitle",
               "BODY": "body", "OBJECT": "body"}.get(ph.ph_type)
        level = override.get(key) if key else None

    master = palette.title_style if ph.is_title else palette.body_style
    base = master[0] if master else None

    size = (level.size_pt if level and level.size_pt else None) \
        or (base.size_pt if base and base.size_pt else None) \
        or (18.0 if ph.is_title else 12.0)
    raw_color = (level.color_hex if level and level.color_hex else None) \
        or (base.color_hex if base and base.color_hex else None)
    color = palette.resolve(raw_color or "") or "#222222"
    font = (level.font if level and level.font else None) \
        or (base.font if base and base.font else None) \
        or palette.font_minor or ""
    bullet = base.bullet_char if base else None
    return round(float(size), 2), color, font, bullet
