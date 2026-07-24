"""The shared formatters (`app/report/format.py`).

These exist because the deck and the workbook format the same value differently
on purpose, and that divergence is now expressed as arguments rather than as two
copies of the code. If someone "tidies up" the defaults, these fail loudly —
which is the point, because the alternative is a silently reworded deck.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.models.enums import SourceFormat
from app.models.pmi import SourceReference
from app.report import format as fmt


class _Entity:
    """Minimal stand-in — `cite` only ever touches `primary_source`."""

    def __init__(self, ref):
        self.primary_source = ref


def _ref(**kwargs) -> SourceReference:
    """`location` is a computed property, so build the locator from real fields."""
    return SourceReference(
        **{"file_name": "tracker.xlsx", "file_type": SourceFormat.EXCEL, **kwargs}
    )


# ------------------------------------------------------------------ numbers
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "Not Reported"),
        (0, "0"),          # a real zero is a value, and must survive as one
        (45, "45"),
        (45.0, "45"),      # %g, so no "45.000000" on a slide
        (999, "999"),
        (1000, "1,000"),   # thousands separator kicks in at 1000
        (-2500, "-2,500"),
    ],
)
def test_numbers_render_readably(value, expected):
    assert fmt.num(value) == expected


def test_missing_number_is_never_zero():
    """§7: a zero is a claim, an absence is not. Never conflate them."""
    assert fmt.num(None) == "Not Reported"
    assert fmt.num(None) != "0"


# -------------------------------------------------------------------- dates
def test_dates_are_day_month_year():
    assert fmt.date_str(date(2026, 3, 9)) == "09-03-2026"


def test_each_renderer_picks_its_own_missing_date_sentinel():
    # The deck writes an em dash; a workbook cell says so in words, because "—"
    # in a spreadsheet reads as a value rather than an absence.
    assert fmt.date_str(None, missing=fmt.DASH) == "—"
    assert fmt.date_str(None, missing=fmt.NOT_REPORTED) == "Not Reported"


# ----------------------------------------------------------------- citations
def test_slide_citation_is_file_name_only():
    """A slide has no room for `sheet 'Workplan'!A7`."""
    entity = _Entity(_ref(sheet_name="Workplan", cell_range="A7"))
    assert fmt.cite(entity, missing=fmt.DASH) == "tracker.xlsx"


def test_workbook_citation_carries_the_location():
    """The workbook is where someone goes to check a figure."""
    entity = _Entity(_ref(sheet_name="Workplan", cell_range="A7"))
    assert fmt.cite(
        entity, with_location=True, missing=fmt.NOT_REPORTED, warn_sep=" "
    ) == "tracker.xlsx (sheet 'Workplan'!A7)"


def test_low_confidence_is_flagged_in_both_dialects():
    """Reading a figure off a screenshot must never look like reading a tracker."""
    entity = _Entity(
        _ref(file_name="deck.pptx", file_type=SourceFormat.POWERPOINT,
             slide_number=4, extraction_confidence=0.4)
    )

    # The spacing after the glyph genuinely differs between the two renderers;
    # this pins the current output so extracting the function changed no string.
    assert fmt.cite(entity, missing=fmt.DASH) == "deck.pptx ⚠40%"
    assert fmt.cite(
        entity, with_location=True, missing=fmt.NOT_REPORTED, warn_sep=" "
    ) == "deck.pptx (slide 4) ⚠ 40%"


def test_a_confident_read_carries_no_warning():
    entity = _Entity(_ref(sheet_name="Workplan", extraction_confidence=1.0))
    assert "⚠" not in fmt.cite(entity, with_location=True)


def test_a_claim_with_no_source_says_so():
    assert fmt.cite(_Entity(None), missing=fmt.DASH) == "—"
    assert fmt.cite(_Entity(None), missing=fmt.NOT_REPORTED) == "Not Reported"


def test_location_is_omitted_when_the_source_did_not_record_one():
    """Never render an empty `()` — that reads as a bug, not as an absence."""
    entity = _Entity(_ref())          # no locator fields at all
    assert fmt.cite(entity, with_location=True) == "tracker.xlsx"
