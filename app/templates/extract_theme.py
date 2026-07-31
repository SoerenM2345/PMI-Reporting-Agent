"""Parse a template's theme and master text styles into measured values.

Everything the brand system knows is read from the file. Nothing here hard-codes
a Deloitte colour or the string "Aptos" — swap the template and the palette,
the type scale and the bullet characters all move with it.

Three OOXML details this has to get right:

* **`sysClr` carries the resolved colour in `lastClr`, not `val`.** `dk1` in the
  Deloitte theme is `<a:sysClr val="windowText" lastClr="000000"/>`; reading
  `val` yields the literal string "windowText".

* **`schemeClr` names are indirections through the master's `clrMap`.** A run
  coloured `tx1` does not mean `dk1` by definition — the map says which. The
  default mapping is the common case, but reading the map costs four lines and
  makes a re-themed template work.

* **Text styles are per outline level.** `bodyStyle` in this master is 12pt at
  every level; what changes is `marL`, `indent` and the bullet character (level
  1 has none, level 2 is `•`, level 3 is `−`). A renderer that hard-codes "•"
  disagrees with the template on every nested bullet.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree

log = logging.getLogger("pmi.templates.theme")

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": _A, "p": _P}

#: The slots a theme's `clrScheme` always defines, in OOXML order.
SCHEME_SLOTS = ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3",
                "accent4", "accent5", "accent6", "hlink", "folHlink")

#: Used when a master defines no `clrMap` of its own.
DEFAULT_COLOR_MAP = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}


@dataclass(frozen=True)
class TextLevel:
    """One outline level of a master text style."""

    level: int
    size_pt: Optional[float]
    color_hex: Optional[str]
    font: Optional[str]
    bullet_char: Optional[str]
    indent_in: float = 0.0
    hanging_in: float = 0.0
    bold: bool = False


@dataclass(frozen=True)
class ThemePalette:
    theme_name: str
    scheme_name: str
    #: Slot name -> `RRGGBB`, already resolved through `sysClr`.
    scheme: dict[str, str]
    #: The template author's named palette (`Teal 5`, `Cool Gray 9`, `Red`, …).
    #: The Deloitte master defines 32; most templates define none.
    custom: dict[str, str]
    color_map: dict[str, str]
    font_major: str
    font_minor: str
    title_style: tuple[TextLevel, ...] = ()
    body_style: tuple[TextLevel, ...] = ()
    other_style: tuple[TextLevel, ...] = ()
    #: Layout index -> placeholder key -> level-1 override, e.g. the 32pt
    #: accent3 title on the cover and the 36pt accent4 title on a divider.
    layout_overrides: dict[int, dict[str, TextLevel]] = field(default_factory=dict)

    def resolve(self, name: str) -> Optional[str]:
        """A colour by scheme slot, `clrMap` alias or custom name -> `#RRGGBB`."""
        if not name:
            return None
        if name.startswith("#"):
            return name.upper()
        slot = self.color_map.get(name, name)
        if slot in self.scheme:
            return "#" + self.scheme[slot]
        for key, value in self.custom.items():
            if key.casefold() == name.casefold():
                return "#" + value
        return None

    def body_level(self, level: int) -> Optional[TextLevel]:
        for entry in self.body_style:
            if entry.level == level:
                return entry
        return self.body_style[0] if self.body_style else None


def extract(theme_xml: bytes, master_xml: bytes = b"",
            layout_xml: Optional[dict[int, bytes]] = None) -> ThemePalette:
    """Build a `ThemePalette` from the raw parts `inspect_pptx` collected.

    An unparseable or absent theme yields an empty palette rather than raising:
    `brand_system` then falls back to its documented defaults and records a gap,
    which is the same posture the rest of the app takes toward a missing asset.
    """
    if not theme_xml:
        log.warning("no theme part; the brand system will use fallback tokens")
        return ThemePalette("", "", {}, {}, dict(DEFAULT_COLOR_MAP), "", "")

    try:
        theme = etree.fromstring(theme_xml)
    except etree.XMLSyntaxError as exc:                       # noqa: BLE001
        log.warning("theme1.xml did not parse (%s); using fallback tokens", exc)
        return ThemePalette("", "", {}, {}, dict(DEFAULT_COLOR_MAP), "", "")

    scheme_node = theme.find(".//a:clrScheme", NS)
    scheme: dict[str, str] = {}
    for child in scheme_node if scheme_node is not None else []:
        slot = etree.QName(child).localname
        value = _color_of(child)
        if value:
            scheme[slot] = value

    custom: dict[str, str] = {}
    for entry in theme.findall(".//a:custClrLst/a:custClr", NS):
        value = _color_of(entry)
        name = entry.get("name")
        if name and value:
            custom[name] = value

    fonts = theme.find(".//a:fontScheme", NS)
    palette = ThemePalette(
        theme_name=theme.get("name") or "",
        scheme_name=(scheme_node.get("name") if scheme_node is not None else "") or "",
        scheme=scheme,
        custom=custom,
        color_map=_color_map(master_xml),
        font_major=_typeface(fonts, "majorFont"),
        font_minor=_typeface(fonts, "minorFont"),
        title_style=_text_style(master_xml, "titleStyle"),
        body_style=_text_style(master_xml, "bodyStyle"),
        other_style=_text_style(master_xml, "otherStyle"),
        layout_overrides=_layout_overrides(layout_xml or {}),
    )
    log.info(
        "theme %r: %d scheme slots, %d custom colours, fonts %s/%s",
        palette.theme_name, len(scheme), len(custom),
        palette.font_major or "?", palette.font_minor or "?",
    )
    return palette


# ---------------------------------------------------------------- internals
def _color_of(node) -> Optional[str]:
    """The `RRGGBB` under a colour-bearing element.

    `sysClr` keeps the resolved value in `lastClr`; `val` is the system role
    name ("windowText") and is useless as a colour.
    """
    for child in node.iter():
        tag = etree.QName(child).localname
        if tag == "srgbClr" and child.get("val"):
            return child.get("val").upper()
        if tag == "sysClr":
            last = child.get("lastClr")
            if last:
                return last.upper()
    return None


def _color_map(master_xml: bytes) -> dict[str, str]:
    if not master_xml:
        return dict(DEFAULT_COLOR_MAP)
    try:
        master = etree.fromstring(master_xml)
    except etree.XMLSyntaxError:
        return dict(DEFAULT_COLOR_MAP)
    node = master.find("p:clrMap", NS)
    if node is None:
        return dict(DEFAULT_COLOR_MAP)
    mapping = dict(DEFAULT_COLOR_MAP)
    for alias in ("bg1", "tx1", "bg2", "tx2"):
        target = node.get(alias)
        if target:
            mapping[alias] = target
    return mapping


def _typeface(fonts, which: str) -> str:
    if fonts is None:
        return ""
    latin = fonts.find(f"a:{which}/a:latin", NS)
    return (latin.get("typeface") or "") if latin is not None else ""


def _text_style(master_xml: bytes, style: str) -> tuple[TextLevel, ...]:
    if not master_xml:
        return ()
    try:
        master = etree.fromstring(master_xml)
    except etree.XMLSyntaxError:
        return ()
    node = master.find(f".//p:txStyles/p:{style}", NS)
    if node is None:
        return ()

    levels: list[TextLevel] = []
    for child in node:
        name = etree.QName(child).localname
        if not name.startswith("lvl"):
            continue                       # `defPPr` carries no level of its own
        try:
            level = int(name[3:].rstrip("pPr") or 1)
        except ValueError:
            continue
        levels.append(_level(child, level))
    return tuple(levels)


def _level(node, level: int) -> TextLevel:
    rpr = node.find("a:defRPr", NS)
    size = rpr.get("sz") if rpr is not None else None
    latin = rpr.find("a:latin", NS) if rpr is not None else None
    bullet = node.find("a:buChar", NS)
    font = latin.get("typeface") if latin is not None else None
    return TextLevel(
        level=level,
        size_pt=(int(size) / 100.0) if size else None,
        color_hex=_style_color(rpr),
        # "+mn-lt" / "+mj-lt" are theme references, not typefaces; the caller
        # substitutes the theme font, so report them as "inherit".
        font=None if not font or font.startswith("+") else font,
        bullet_char=bullet.get("char") if bullet is not None else None,
        indent_in=_emu_in(node.get("marL")),
        hanging_in=abs(_emu_in(node.get("indent"))),
        bold=(rpr.get("b") == "1") if rpr is not None else False,
    )


def _style_color(rpr) -> Optional[str]:
    """A style's colour as a scheme slot name (`tx1`) or a literal `#RRGGBB`."""
    if rpr is None:
        return None
    scheme = rpr.find(".//a:schemeClr", NS)
    if scheme is not None and scheme.get("val"):
        return scheme.get("val")
    srgb = rpr.find(".//a:srgbClr", NS)
    if srgb is not None and srgb.get("val"):
        return "#" + srgb.get("val").upper()
    return None


def _layout_overrides(layout_xml: dict[int, bytes]) -> dict[int, dict[str, TextLevel]]:
    """Per-layout level-1 text overrides, keyed by placeholder type.

    This is where the cover's 32pt accent3 title and the divider's 36pt accent4
    title actually live — the master says 21pt for every title, and a renderer
    that trusted only the master would size every cover wrong.

    Each override is filed under **both** its placeholder type and its index.
    Filing by type alone loses data: the Light Gray layouts carry two `body`
    placeholders — a 21pt heading and a 9pt subheading — and the second would
    overwrite the first, sizing every heading in that family at 9pt.
    """
    out: dict[int, dict[str, TextLevel]] = {}
    for index, raw in layout_xml.items():
        if not raw:
            continue
        try:
            layout = etree.fromstring(raw)
        except etree.XMLSyntaxError:
            continue
        found: dict[str, TextLevel] = {}
        for shape in layout.findall(".//p:sp", NS):
            ph = shape.find(".//p:ph", NS)
            if ph is None:
                continue
            level_node = shape.find(".//a:lvl1pPr", NS)
            if level_node is None:
                continue
            level = _level(level_node, 1)
            idx = ph.get("idx")
            if idx is not None:
                found[f"idx{idx}"] = level
            ph_type = ph.get("type")
            if ph_type:
                found.setdefault(ph_type, level)      # first wins; see docstring
        if found:
            out[index] = found
    return out


def _emu_in(value: Optional[str]) -> float:
    try:
        return round(int(value) / 914400.0, 4) if value else 0.0
    except (TypeError, ValueError):
        return 0.0
