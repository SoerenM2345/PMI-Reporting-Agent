"""One design language, derived from the template, shared by all four formats.

`app/report/brand.py` was eleven hex strings. Four other modules each kept their
own copy of some of them, so the deck, the workbook, the charts and the dashboard
could disagree about what green meant with nothing to catch it. Worse, none of
them was *measured*: the template says the cover title is 32pt accent3 and the
divider is 36pt accent4, and no renderer knew.

A `BrandSystem` is built by reading the template, so swapping the master moves
the whole design language — colours, type scale, grid, chart styling — across
PowerPoint, Word, PDF and HTML at once.

Two decisions worth stating:

* **Chart colours are contrast-corrected, not merely copied.** The brand's
  signature bright green is beautiful and fails WCAG 1.4.11 against white at
  1.9:1. Dropping it would lose the brand; using it raw makes a bar chart
  unreadable. So each categorical colour is darkened along its own hue until it
  clears 3:1, and adjacent series are checked for perceptual distance (CIE76)
  so a reader can tell them apart. The signature colour stays available
  unmodified as `semantic["emphasis"]`, where it sits on large type and rules.

* **The grid is measured, not declared.** Column widths come from the template's
  own 1/2/3/4-column layouts, so the Word and HTML grids line up with the deck's
  by construction rather than by a developer copying numbers.
"""
from __future__ import annotations

import base64
import logging
import math
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from app.templates.extract_layouts import TemplateLayout
from app.templates.extract_theme import DEFAULT_COLOR_MAP, ThemePalette

log = logging.getLogger("pmi.templates.brand")

#: WCAG 2.2 SC 1.4.11 for graphical objects. Chart marks are graphical objects.
MIN_MARK_CONTRAST = 3.0
#: WCAG 2.2 SC 1.4.3 for body text.
MIN_TEXT_CONTRAST = 4.5
#: CIE76 distance below which two series read as "the same colour" to most
#: viewers. ~2.3 is the just-noticeable difference; series need much more.
MIN_SERIES_DISTANCE = 18.0

#: Candidate chart series colours, in preference order, named as the template
#: names them. Missing names are skipped, so this degrades to whatever a
#: different template happens to define.
_CATEGORICAL_CANDIDATES = (
    "accent3", "Teal 5", "Blue 4", "accent1", "Cool Gray 9",
    "Teal 7", "Blue 2", "Green 4", "Orange", "Blue 6",
)
_SEQUENTIAL_CANDIDATES = ("accent6", "Green 1", "Green 2", "accent1",
                          "Green 4", "accent2", "accent3", "accent4")
_DIVERGING_CANDIDATES = ("Red", "Orange", "Yellow", "lt2", "Green 2",
                         "Green 4", "accent3")

#: Fallback tokens for a missing or unreadable template. Deliberately the
#: Deloitte values the old `brand.py` carried, so behaviour does not regress
#: when the asset is absent — but a gap is recorded either way.
_FALLBACK_SCHEME = {
    "dk1": "000000", "lt1": "FFFFFF", "dk2": "222222", "lt2": "E6E6E6",
    "accent1": "86BC25", "accent2": "26890D", "accent3": "046A38",
    "accent4": "1C3D26", "accent5": "0DF200", "accent6": "F1F6E4",
    "hlink": "26890D", "folHlink": "75787B",
}
_FALLBACK_CUSTOM = {"Red": "DA291C", "Orange": "ED8B00", "Yellow": "FFCD00",
                    "Cool Gray 9": "75787B", "Cool Gray 6": "A7A8AA",
                    "Cool Gray 2": "D0D0CE", "Green 5": "009A44",
                    "Teal 5": "0097A9", "Blue 4": "0076A8"}


class TypeToken(BaseModel):
    size_pt: float
    bold: bool = False
    color: str = "#222222"
    line_height: float = 1.2


class GridTokens(BaseModel):
    """Measured from the template's own column layouts."""

    margin_x_in: float = 0.5
    content_top_in: float = 1.84
    content_bottom_in: float = 6.96
    gutter_in: float = 0.33
    #: Column count -> width of one column, in inches.
    column_widths_in: dict[int, float] = Field(default_factory=dict)

    def column_width(self, columns: int) -> float:
        if columns in self.column_widths_in:
            return self.column_widths_in[columns]
        full = self.column_widths_in.get(1, 12.33)
        return round((full - self.gutter_in * (columns - 1)) / max(columns, 1), 4)

    @property
    def content_height_in(self) -> float:
        return round(self.content_bottom_in - self.content_top_in, 4)


class ChartTokens(BaseModel):
    axis_color: str = "#75787B"
    gridline_color: str = "#E6E6E6"
    gridline_pt: float = 0.75
    tick_pt: float = 9.0
    label_pt: float = 9.0
    title_pt: float = 12.0
    legend: str = "bottom"
    bar_gap_percent: int = 40
    series_overlap_percent: int = -10
    #: Rendered on a white surface unless a page says otherwise.
    surface: str = "#FFFFFF"


class BrandSystem(BaseModel):
    """The full design language. Every value here came from the template."""

    system_id: str
    source_template: str
    derived_from_template: bool = True

    scheme: dict[str, str] = Field(default_factory=dict)
    custom: dict[str, str] = Field(default_factory=dict)
    semantic: dict[str, str] = Field(default_factory=dict)
    categorical: list[str] = Field(default_factory=list)
    sequential: list[str] = Field(default_factory=list)
    diverging: list[str] = Field(default_factory=list)

    font_major: str = "Aptos"
    font_minor: str = "Aptos"
    font_fallbacks: list[str] = Field(
        default_factory=lambda: ["Segoe UI", "Calibri", "DejaVu Sans", "sans-serif"])
    type_scale: dict[str, TypeToken] = Field(default_factory=dict)

    slide_w_in: float = 13.3333
    slide_h_in: float = 7.5
    grid: GridTokens = Field(default_factory=GridTokens)
    spacing_in: dict[str, float] = Field(
        default_factory=lambda: {"xs": 0.06, "sm": 0.12, "md": 0.22,
                                 "lg": 0.36, "xl": 0.6})
    rule_pt: float = 0.75
    chart: ChartTokens = Field(default_factory=ChartTokens)

    #: Where Python draws the footer, because this template defines no FOOTER,
    #: SLIDE_NUMBER or DATE placeholder on any of its 59 layouts. The geometry
    #: mirrors the hand-drawn `CaseCode`/`Copyright` boxes on the dividers so a
    #: generated footer reads as native rather than bolted on.
    footer_top_in: float = 7.02
    footer_height_in: float = 0.28
    footer_pt: float = 8.0

    logo_png_b64: Optional[str] = None
    notes: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------- lookups
    def color(self, role: str) -> str:
        """A colour by semantic role, scheme slot or custom name."""
        if role.startswith("#"):
            return role.upper()
        if role in self.semantic:
            return self.semantic[role]
        if role in self.scheme:
            return "#" + self.scheme[role]
        for name, value in self.custom.items():
            if name.casefold() == role.casefold():
                return "#" + value
        log.debug("unknown colour role %r; using text", role)
        return self.semantic.get("text", "#222222")

    def pptx_rgb(self, role: str):
        from pptx.dml.color import RGBColor

        value = self.color(role).lstrip("#")
        return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))

    def font(self, token: str = "body") -> TypeToken:
        return self.type_scale.get(token) or TypeToken(size_pt=12.0)

    def series_color(self, index: int) -> str:
        palette = self.categorical or ["#046A38"]
        return palette[index % len(palette)]

    @property
    def font_stack(self) -> str:
        names = [self.font_minor or "Aptos", *self.font_fallbacks]
        seen: list[str] = []
        for name in names:
            if name and name not in seen:
                seen.append(name)
        return ", ".join(f"'{n}'" if " " in n else n for n in seen)

    def logo_data_uri(self) -> Optional[str]:
        return f"data:image/png;base64,{self.logo_png_b64}" if self.logo_png_b64 else None

    def css_vars(self) -> str:
        """`:root { … }` so the HTML dashboard and the deck share one palette."""
        lines = [f"  --brand-{_css_name(k)}: {v};" for k, v in sorted(self.semantic.items())]
        lines += [f"  --type-{_css_name(k)}: {v.size_pt}pt;"
                  for k, v in sorted(self.type_scale.items())]
        lines += [f"  --space-{k}: {v}in;" for k, v in sorted(self.spacing_in.items())]
        lines += [f"  --series-{i}: {c};" for i, c in enumerate(self.categorical)]
        lines.append(f"  --font-stack: {self.font_stack};")
        lines.append(f"  --grid-gutter: {self.grid.gutter_in}in;")
        return ":root {\n" + "\n".join(lines) + "\n}"

    def docx_theme(self) -> dict:
        """The subset `renderers/docx_styles.py` needs to define Word styles."""
        return {
            "font": self.font_minor or "Aptos",
            "colors": dict(self.semantic),
            "sizes": {k: v.size_pt for k, v in self.type_scale.items()},
            "rule_pt": self.rule_pt,
        }


# ------------------------------------------------------------------- build
def build(palette: ThemePalette, layouts: Sequence[TemplateLayout], *,
          slide_w_in: float = 13.3333, slide_h_in: float = 7.5,
          source: str = "", system_id: str = "",
          logo_png: Optional[bytes] = None,
          derive_brand: bool = True) -> BrandSystem:
    """Derive the design language from a parsed template.

    `derive_brand=False` keeps the measured geometry but ignores the file's own
    colours and fonts. That is for the substitute-template path: when the
    configured master is missing, python-pptx's default is a perfectly good
    source of *layouts* and an actively harmful source of *brand* — inheriting
    it would silently reissue the deliverable in Microsoft's Office palette,
    which is worse than the documented fallback tokens.
    """
    if not derive_brand:
        # Discard the substitute file's colours, fonts and type overrides in one
        # place, so every derivation below falls back consistently.
        palette = ThemePalette("", "", {}, {}, dict(DEFAULT_COLOR_MAP), "", "")
    derived = bool(palette.scheme)
    scheme = dict(palette.scheme) if derived else dict(_FALLBACK_SCHEME)
    custom = dict(palette.custom) if derived else dict(_FALLBACK_CUSTOM)
    notes: list[str] = []
    if not derived:
        notes.append("Brand tokens are the built-in Deloitte defaults, not "
                     "measured from a template file.")

    lookup = _Lookup(scheme, custom, palette.color_map)
    surface = lookup.get("lt1") or "#FFFFFF"
    text = lookup.get("dk2") or "#222222"

    semantic = {
        "primary": lookup.get("accent3") or "#046A38",
        "emphasis": lookup.get("accent1") or "#86BC25",
        "deep": lookup.get("accent4") or "#1C3D26",
        "text": text,
        "text_inverse": lookup.get("lt1") or "#FFFFFF",
        "muted": lookup.get("Cool Gray 9") or lookup.get("folHlink") or "#75787B",
        "surface": surface,
        "surface_alt": lookup.get("lt2") or "#E6E6E6",
        "rule": lookup.get("lt2") or "#E6E6E6",
        "link": lookup.get("hlink") or "#26890D",
        "rag_red": lookup.get("Red") or "#DA291C",
        "rag_amber": lookup.get("Orange") or "#ED8B00",
        "rag_green": lookup.get("Green 5") or lookup.get("accent2") or "#26890D",
        "rag_grey": lookup.get("Cool Gray 6") or "#A7A8AA",
    }
    semantic["positive"] = semantic["rag_green"]
    semantic["negative"] = semantic["rag_red"]
    semantic["neutral"] = semantic["muted"]

    # Body text must be legible on the surface it sits on; a template that
    # fails this is reporting a real problem, so say so rather than silently
    # restyling the brand's own text colour.
    text_ratio = contrast_ratio(semantic["text"], surface)
    if text_ratio < MIN_TEXT_CONTRAST:
        notes.append(f"Template body text ({semantic['text']}) reaches only "
                     f"{text_ratio:.1f}:1 on {surface}; below the 4.5:1 bar.")

    categorical, adjusted = _categorical(lookup, surface)
    if adjusted:
        notes.append("Chart series colours darkened for legibility: "
                     + ", ".join(adjusted) + ". The unmodified brand colour "
                     "remains available as the 'emphasis' role.")

    return BrandSystem(
        system_id=system_id or "unversioned",
        source_template=source,
        derived_from_template=derived,
        scheme=scheme,
        custom=custom,
        semantic=semantic,
        categorical=categorical,
        sequential=[c for c in (lookup.get(n) for n in _SEQUENTIAL_CANDIDATES) if c],
        diverging=[c for c in (lookup.get(n) for n in _DIVERGING_CANDIDATES) if c],
        font_major=palette.font_major or "Aptos",
        font_minor=palette.font_minor or palette.font_major or "Aptos",
        type_scale=_type_scale(palette, semantic),
        slide_w_in=slide_w_in,
        slide_h_in=slide_h_in,
        grid=_grid(layouts, slide_w_in, slide_h_in),
        chart=ChartTokens(
            axis_color=semantic["muted"],
            gridline_color=semantic["rule"],
            surface=surface,
            title_pt=12.0,
        ),
        logo_png_b64=base64.b64encode(logo_png).decode("ascii") if logo_png else None,
        notes=notes,
    )


# --------------------------------------------------------------- internals
class _Lookup:
    """Resolve a scheme slot, `clrMap` alias or custom colour name to `#RRGGBB`."""

    def __init__(self, scheme: dict[str, str], custom: dict[str, str],
                 color_map: dict[str, str]) -> None:
        self._scheme = scheme
        self._custom = {k.casefold(): v for k, v in custom.items()}
        self._map = color_map

    def get(self, name: str) -> Optional[str]:
        slot = self._map.get(name, name)
        if slot in self._scheme:
            return "#" + self._scheme[slot].upper()
        value = self._custom.get(name.casefold())
        return "#" + value.upper() if value else None


def _categorical(lookup: _Lookup, surface: str) -> tuple[list[str], list[str]]:
    """An ordered series palette that is legible and internally distinguishable."""
    palette: list[str] = []
    adjusted: list[str] = []
    for name in _CATEGORICAL_CANDIDATES:
        raw = lookup.get(name)
        if raw is None:
            continue
        fixed = ensure_contrast(raw, surface, MIN_MARK_CONTRAST)
        if fixed != raw:
            adjusted.append(f"{name} {raw}→{fixed}")
        if any(color_distance(fixed, seen) < MIN_SERIES_DISTANCE for seen in palette):
            continue                      # too close to a colour already in use
        palette.append(fixed)
    if not palette:
        palette = ["#046A38", "#0097A9", "#0076A8", "#75787B"]
    return palette, adjusted


def _type_scale(palette: ThemePalette, semantic: dict[str, str]) -> dict[str, TypeToken]:
    """Seed from measured styles, derive the rest at a 1.25 modular ratio."""
    def measured(index: int, key: str, default: float) -> float:
        overrides = palette.layout_overrides.get(index, {})
        level = overrides.get(key)
        return float(level.size_pt) if level and level.size_pt else default

    master_title = palette.title_style[0].size_pt if palette.title_style else None
    master_body = palette.body_style[0].size_pt if palette.body_style else None
    body = float(master_body or 12.0)
    title = float(master_title or 21.0)

    # The cover and divider carry their sizes as layout overrides, not in the
    # master; the master would claim every title is 21pt.
    display = measured(19, "title", 36.0)
    cover = measured(1, "ctrTitle", 32.0)
    subtitle = measured(28, "body", 18.0)

    text, primary, muted = semantic["text"], semantic["primary"], semantic["muted"]
    return {
        "display": TypeToken(size_pt=display, color=semantic["deep"], line_height=1.1),
        "cover": TypeToken(size_pt=cover, color=primary, line_height=1.1),
        "title": TypeToken(size_pt=title, color=text, line_height=1.15),
        "subtitle": TypeToken(size_pt=subtitle, color=muted, line_height=1.2),
        "h1": TypeToken(size_pt=round(body * 1.5, 1), bold=True, color=text),
        "h2": TypeToken(size_pt=round(body * 1.25, 1), bold=True, color=text),
        "h3": TypeToken(size_pt=round(body * 1.1, 1), bold=True, color=text),
        "body": TypeToken(size_pt=body, color=text, line_height=1.3),
        "small": TypeToken(size_pt=round(body / 1.2, 1), color=text),
        "caption": TypeToken(size_pt=round(body / 1.33, 1), color=muted),
        "label": TypeToken(size_pt=round(body / 1.45, 1), color=muted),
        "kpi": TypeToken(size_pt=round(body * 2.2, 1), bold=True, color=primary,
                         line_height=1.0),
    }


def _grid(layouts: Sequence[TemplateLayout], slide_w_in: float,
          slide_h_in: float) -> GridTokens:
    """Measure the content grid from the template's own column layouts."""
    widths: dict[int, float] = {}
    tops: list[float] = []
    bottoms: list[float] = []
    lefts: list[float] = []
    gutters: list[float] = []

    for layout in layouts:
        if layout.role != "content" or layout.family != "white":
            continue
        columns = layout.column_slots
        if not columns:
            continue
        widths.setdefault(len(columns), round(columns[0].width_in, 4))
        tops.append(columns[0].top_in)
        bottoms.append(columns[0].top_in + columns[0].height_in)
        lefts.append(min(c.left_in for c in columns))
        for left, right in zip(columns, columns[1:]):
            gutters.append(round(right.left_in - (left.left_in + left.width_in), 4))

    return GridTokens(
        margin_x_in=round(min(lefts), 2) if lefts else 0.5,
        content_top_in=round(min(tops), 4) if tops else 1.84,
        content_bottom_in=round(max(bottoms), 4) if bottoms else slide_h_in - 0.54,
        gutter_in=round(sum(gutters) / len(gutters), 4) if gutters else 0.33,
        column_widths_in=widths,
    )


def _css_name(token: str) -> str:
    return token.replace("_", "-")


# ------------------------------------------------------------ colour maths
def _srgb(hex_color: str) -> tuple[float, float, float]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    r, g, b = (_linear(c) for c in _srgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast, 1.0 (identical) to 21.0 (black on white)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return round((lighter + 0.05) / (darker + 0.05), 3)


def ensure_contrast(color: str, against: str, minimum: float) -> str:
    """Move `color` along its own hue until it clears `minimum` against `against`.

    Darkens on a light background and lightens on a dark one, in 4% steps, so a
    brand hue survives the correction rather than being replaced by a generic
    accessible colour. Gives up after 25 steps and returns the best it reached —
    a colour that cannot be made legible is a template problem, and the caller
    records it as a note rather than pretending it succeeded.
    """
    if contrast_ratio(color, against) >= minimum:
        return color.upper()
    darken = relative_luminance(against) > 0.5
    r, g, b = (int(c * 255) for c in _srgb(color))
    for _ in range(25):
        factor = 0.96 if darken else 1.0
        if darken:
            r, g, b = (int(c * factor) for c in (r, g, b))
        else:
            r, g, b = (min(255, int(c + (255 - c) * 0.06) + 2) for c in (r, g, b))
        candidate = f"#{r:02X}{g:02X}{b:02X}"
        if contrast_ratio(candidate, against) >= minimum:
            return candidate
    return f"#{r:02X}{g:02X}{b:02X}"


def _lab(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in _srgb(hex_color))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b)
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def color_distance(a: str, b: str) -> float:
    """CIE76 ΔE. Roughly: below ~2.3 is imperceptible, above ~18 is obvious."""
    la, aa, ba = _lab(a)
    lb, ab, bb = _lab(b)
    return round(math.sqrt((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2), 2)
