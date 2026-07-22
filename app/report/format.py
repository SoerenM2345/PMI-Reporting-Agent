"""Value formatting, shared by every renderer.

Until now each generator carried its own `_n` / `_d` / `_cite`, and they did not
agree: the deck omits a source's location and writes an em dash for a missing
one, the workbook includes the location and writes "Not Reported". Both are
deliberate — a slide has no room for `sheet 'Workplan' cell A7`, and a
spreadsheet cell that says "—" reads as a value rather than an absence.

So this module does not unify the output. It unifies the *code* and makes the
differences arguments, so that a change to citation formatting is one edit
rather than two, and so the divergence is visible instead of implicit.

§7: a value we do not have is "Not Reported". Never `0`, never blank.
"""
from __future__ import annotations

NOT_REPORTED = "Not Reported"
DASH = "—"


def num(value, *, missing: str = NOT_REPORTED) -> str:
    """Thousands-separated above 1000, compact below it.

    `%g` keeps 45 as "45" rather than "45.000000", which matters because these
    strings are read off a slide by a human, not parsed.
    """
    if value is None:
        return missing
    return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:g}"


def date_str(value, *, missing: str = NOT_REPORTED) -> str:
    """§7: presented DD-MM-YYYY; stored as a date."""
    return f"{value:%d-%m-%Y}" if value else missing


def cite(
    entity,
    *,
    with_location: bool = False,
    missing: str = NOT_REPORTED,
    warn_sep: str = "",
) -> str:
    """Where a claim came from, and how much to trust it.

    `with_location` adds the sheet/cell/slide reference — worth the width in a
    workbook, too long for a slide.

    `warn_sep` sits between the warning glyph and the percentage. The deck
    writes `⚠60%` and the workbook `⚠ 60%`; that is a real difference in the
    current output and is preserved deliberately rather than normalised, so
    that extracting this function changes no rendered string.
    """
    ref = entity.primary_source
    if ref is None:
        return missing

    text = ref.file_name
    if with_location and ref.location:
        text = f"{text} ({ref.location})"
    if ref.is_low_confidence:
        text += f" ⚠{warn_sep}{ref.extraction_confidence:.0%}"
    return text
