"""The template system: what the Deloitte master actually says, and the traps.

These tests are deliberately specific about this template. That is the point —
the old renderer used 2 of its 59 layouts and deleted every placeholder it
touched, so nothing inherited the theme and nobody noticed. Each assertion here
pins a fact that, if it silently changed, would put a deck back on white slides.

Where a value is a property of *this* file (59 layouts, `Aptos`, `#046A38`) the
test says so. Where it is a property of the extraction *rules* (index by
geometry, rank by size, never trust `shapes.title`) the test exercises the rule.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.templates import brand_system, layout_catalog, template_registry
from app.templates.brand_system import (
    MIN_MARK_CONTRAST,
    MIN_SERIES_DISTANCE,
    color_distance,
    contrast_ratio,
    ensure_contrast,
)
from app.templates.extract_layouts import build as build_layouts
from app.templates.extract_theme import extract as extract_theme
from app.templates.inspect_pptx import NO_IDX, inspect


@pytest.fixture(scope="module")
def reference():
    template_registry.reset_cache()
    return template_registry.default()


@pytest.fixture(scope="module")
def catalog(reference):
    return reference.catalog


@pytest.fixture(scope="module")
def brand(reference):
    return reference.brand


# ------------------------------------------------------------- inspection
def test_the_template_is_the_one_we_think_it_is(reference):
    assert reference.available, "the Deloitte master is missing from app/assets"
    assert reference.name == "Deloitte_Master.pptx"
    assert reference.master_count == 1
    assert reference.layout_count == 59
    assert reference.slide_w_in == pytest.approx(13.3333, abs=0.001)
    assert reference.slide_h_in == pytest.approx(7.5, abs=0.001)


def test_the_template_defines_no_table_styles(reference):
    """`tableStyles.xml` is a 182-byte stub naming only the built-in GUID.

    A substring test for "tblStyle" matches the empty file's `<a:tblStyleLst>`
    wrapper, which would tell a renderer it may inherit table formatting when
    there is none to inherit.
    """
    assert reference.needs_explicit_table_styles
    assert any("no table styles" in note for note in reference.notes)


def test_no_layout_defines_a_footer_or_slide_number_placeholder():
    """Nothing to inherit, so Python must draw the footer band itself."""
    template = inspect(get_settings().pptx_template)
    kinds = {ph.ph_type for layout in template.layouts for ph in layout.placeholders}
    assert not kinds & {"FOOTER", "SLIDE_NUMBER", "DATE"}


# ------------------------------------------------------------------ theme
def test_theme_colours_and_fonts_are_read_from_the_file(brand):
    assert brand.derived_from_template
    assert brand.font_major == "Aptos" and brand.font_minor == "Aptos"
    assert brand.scheme["accent3"] == "046A38"     # Deloitte dark green
    assert brand.scheme["accent1"] == "86BC25"     # signature bright green
    assert brand.semantic["primary"] == "#046A38"
    assert brand.semantic["emphasis"] == "#86BC25"
    assert brand.semantic["rag_red"] == "#DA291C"
    assert len(brand.custom) == 32                 # the custClrLst


def test_sysclr_resolves_through_lastclr_not_val():
    """`dk1` is `<a:sysClr val="windowText" lastClr="000000"/>`.

    Reading `val` yields the literal string "windowText", which is not a colour
    and would silently become a fallback everywhere `tx1` is referenced.
    """
    template = inspect(get_settings().pptx_template)
    palette = extract_theme(template.theme_xml, template.master_xml)
    assert palette.scheme["dk1"] == "000000"
    assert palette.resolve("tx1") == "#000000"     # via the master's clrMap


def test_master_text_styles_are_measured(brand):
    """21pt titles and 12pt body come from the master, not from a constant."""
    assert brand.type_scale["title"].size_pt == 21.0
    assert brand.type_scale["body"].size_pt == 12.0
    # These live only as layout overrides; the master claims every title is 21pt.
    assert brand.type_scale["cover"].size_pt == 32.0
    assert brand.type_scale["display"].size_pt == 36.0
    assert brand.type_scale["subtitle"].size_pt == 18.0


def test_bullet_characters_come_from_the_master():
    template = inspect(get_settings().pptx_template)
    palette = extract_theme(template.theme_xml, template.master_xml)
    assert palette.body_level(1).bullet_char is None      # level 1 has no bullet
    assert palette.body_level(2).bullet_char == "•"
    assert palette.body_level(3).bullet_char == "−"  # a minus, not a hyphen


# ------------------------------------------------------------ layout slots
def test_columns_are_ordered_by_geometry_not_by_placeholder_index(catalog):
    """`idx` is not a slot identity in this template.

    Layout 30's columns are idx 10/20, layout 53's are 10/15 and layout 55's are
    10/18/19/20 — all for the same visual arrangement. Sorting by idx scrambles
    them; sorting by `left` does not.
    """
    assert [s.left_in for s in catalog.by_index(30).column_slots] == \
        pytest.approx([0.5139, 6.836], abs=0.01)
    assert [s.ph_idx for s in catalog.by_index(53).column_slots] == [10, 15]
    assert [s.left_in for s in catalog.by_index(53).column_slots] == \
        pytest.approx([0.5139, 6.8346], abs=0.01)
    assert [s.ph_idx for s in catalog.by_index(55).column_slots] == [10, 18, 19, 20]


def test_the_light_gray_family_has_no_title_placeholder_but_still_has_a_title(catalog):
    """Fourteen layouts (36-49) expose only BODY placeholders.

    `slide.shapes.title` returns `None` on every one of them, so a renderer
    built on it loses the heading across a quarter of the template. The slot
    exists regardless, and the flag exists so nothing reaches for `shapes.title`.
    """
    for index in (36, 37, 43, 44):
        layout = catalog.by_index(index)
        assert layout.has_title_slot is False
        assert layout.slot("title") is not None, f"layout {index} lost its heading"

    assert catalog.by_index(27).has_title_slot is True     # 'Title Only' does


def test_the_title_is_the_largest_header_placeholder_not_the_topmost(catalog):
    """In the Light Gray family the topmost box is a 9pt eyebrow.

    The real 28pt title sits *below* it. Ranking by position picks the eyebrow
    and sizes every heading in that family at 9pt.
    """
    title = catalog.by_index(37).slot("title")
    assert title.ph_idx == 27
    assert title.default_pt == 28.0
    assert title.top_in > catalog.by_index(37).slot("subtitle").top_in

    # The White family, where position and size agree.
    white = catalog.by_index(30)
    assert white.slot("title").default_pt == 21.0
    assert white.slot("subtitle").default_pt == 18.0


def test_the_no_idx_sentinel_is_never_addressable(catalog):
    """python-pptx reports a missing `idx` as 2**32-1.

    Four layouts carry two such placeholders each, and two of them share a name
    on the same layout. There is no safe way to target one, so they are never
    offered as a slot a renderer may fill.
    """
    for layout in catalog.layouts:
        for slot in layout.slots:
            assert slot.ph_idx != NO_IDX
            if slot.ph_idx is None:
                assert slot.accepts == (), "an unaddressable slot was offered"

    # Layout 34 has 4 body boxes below the header, 2 of them sentinels.
    assert catalog.by_index(34).columns == 2


def test_slot_styles_resolve_through_the_inheritance_chain(catalog):
    """python-pptx resolves none of this: a cloned run reports `size is None`."""
    cover = catalog.by_index(1).slot("title")
    assert cover.default_pt == 32.0 and cover.default_color == "#046A38"

    divider = catalog.by_index(19).slot("title")
    assert divider.default_pt == 36.0 and divider.default_color == "#1C3D26"

    assert catalog.by_index(30).slot("subtitle").default_color == "#53565A"


# ---------------------------------------------------------- naming traps
def test_layout_ids_survive_trailing_spaces_and_casing(catalog):
    """Seven layouts have trailing spaces; two differ only by the case of "Only"."""
    assert catalog.by_name("Title Only").index == 27
    assert catalog.by_name("title ONLY - black").index == 50
    assert catalog.by_name("Team profile").index == 33      # stored with a trailing space
    assert catalog.by_index(33).raw_name != catalog.by_index(33).raw_name.strip()

    assert catalog.by_index(27).layout_id == "27:title-only"
    assert catalog.by_index(50).layout_id == "50:title-only-black"
    ids = [lay.layout_id for lay in catalog.layouts]
    assert len(ids) == len(set(ids)), "layout ids must be unique"


def test_layout_roles_and_families_are_classified(catalog):
    assert catalog.by_index(1).role == "title"
    assert catalog.by_index(19).role == "divider"
    assert catalog.by_index(30).role == "content"
    assert catalog.by_index(35).role == "end"
    assert catalog.by_index(30).family == "white"
    assert catalog.by_index(40).family == "light_gray"
    assert catalog.by_index(47).family == "pale_green"
    assert catalog.by_index(55).family == "black"


def test_thinkcell_objects_are_flagged_and_left_alone(catalog):
    """The OLE object is inherited, never cloned onto a slide.

    So it is safe — provided nothing mutates the layout part. The flag exists so
    that stays a deliberate choice rather than luck.
    """
    flagged = [lay.index for lay in catalog.layouts if lay.has_thinkcell]
    assert 30 in flagged and 17 in flagged
    for index in flagged:
        assert any("think-cell" in name.casefold()
                   for name in catalog.by_index(index).decorations)


# ---------------------------------------------------------------- choosing
@pytest.mark.parametrize("composition,columns", [
    ("single", 1), ("two_column", 2), ("three_column", 3), ("four_column", 4),
    ("chart_plus_commentary", 2),
])
def test_a_composition_gets_a_native_layout_with_the_right_columns(
        catalog, composition, columns):
    choice = catalog.choose(composition=composition)
    assert choice.exact and choice.columns == columns
    assert choice.layout.slot("title") is not None
    assert choice.reason == ""


def test_page_purposes_land_on_their_own_layout_families(catalog):
    assert catalog.choose(purpose="cover").layout.role == "title"
    assert catalog.choose(purpose="closing").layout.role == "end"

    divider = catalog.choose(purpose="divider").layout
    quote = catalog.choose(composition="quote").layout
    assert divider.role == quote.role == "divider"
    # A section break and a one-sentence statement page are different slides.
    assert divider.index != quote.index
    assert quote.slot("title").top_in > divider.slot("title").top_in


def test_a_composition_the_template_cannot_serve_degrades_with_a_reason(catalog):
    """The failure mode is the point.

    Falling back to free-floating textboxes is how the previous renderer ended
    up ignoring 57 of 59 layouts. A degraded choice stays on a native layout and
    says what it gave up, so the page can carry the warning.
    """
    black = layout_catalog.build(
        [lay for lay in catalog.layouts if lay.columns <= 2 or lay.role != "content"])
    choice = black.choose(composition="four_column")
    assert choice.degraded
    assert choice.requested_columns == 4 and choice.columns < 4
    assert "4 columns" in choice.reason and choice.layout.raw_name.strip() in choice.reason


def test_choosing_never_leaves_the_template(catalog):
    for composition in layout_catalog.COMPOSITION_COLUMNS:
        for family in ("white", "black", "light_gray", "pale_green"):
            choice = catalog.choose(composition=composition, family=family)
            assert catalog.by_id(choice.layout.layout_id) is not None


# ------------------------------------------------------------ brand system
def test_every_chart_series_colour_is_legible_and_distinguishable(brand):
    """Brand fidelity and legibility, resolved rather than traded off.

    The signature bright green is 1.9:1 on white — beautiful on a headline,
    unreadable as a bar. It is darkened along its own hue for chart use and
    stays unmodified as the `emphasis` role.
    """
    assert len(brand.categorical) >= 6
    surface = brand.semantic["surface"]
    for color in brand.categorical:
        assert contrast_ratio(color, surface) >= MIN_MARK_CONTRAST, color

    for i, first in enumerate(brand.categorical):
        for second in brand.categorical[i + 1:]:
            assert color_distance(first, second) >= MIN_SERIES_DISTANCE

    assert brand.semantic["emphasis"] == "#86BC25"          # untouched
    assert "#86BC25" not in brand.categorical               # corrected for charts
    assert any("darkened for legibility" in note for note in brand.notes)


def test_ensure_contrast_preserves_hue_and_reaches_the_target():
    fixed = ensure_contrast("#86BC25", "#FFFFFF", MIN_MARK_CONTRAST)
    assert contrast_ratio(fixed, "#FFFFFF") >= MIN_MARK_CONTRAST
    # Still recognisably the same green: darker, not re-hued.
    assert color_distance(fixed, "#86BC25") < 30
    r, g, b = (int(fixed[i:i + 2], 16) for i in (1, 3, 5))
    assert g > r and g > b

    already = ensure_contrast("#046A38", "#FFFFFF", MIN_MARK_CONTRAST)
    assert already == "#046A38", "a colour that already passes must not move"


def test_the_grid_is_measured_from_the_template(brand):
    """So the Word and HTML grids line up with the deck's by construction."""
    grid = brand.grid
    assert grid.column_widths_in[1] == pytest.approx(12.33, abs=0.01)
    assert grid.column_widths_in[2] == pytest.approx(6.00, abs=0.01)
    assert grid.column_widths_in[3] == pytest.approx(3.88, abs=0.01)
    assert grid.column_widths_in[4] == pytest.approx(2.94, abs=0.01)
    assert grid.content_top_in == pytest.approx(1.84, abs=0.01)
    assert grid.content_height_in == pytest.approx(5.12, abs=0.01)


def test_the_brand_exports_itself_to_every_format(brand):
    css = brand.css_vars()
    assert "--brand-primary: #046A38;" in css
    assert "--series-0:" in css and "--font-stack:" in css
    assert "Aptos" in brand.font_stack

    theme = brand.docx_theme()
    assert theme["font"] == "Aptos" and theme["sizes"]["body"] == 12.0

    assert brand.pptx_rgb("primary") == (0x04, 0x6A, 0x38)
    assert brand.color("#abc123") == "#ABC123"
    assert brand.color("Cool Gray 9") == "#75787B"


def test_the_logo_is_extracted_for_inlining(brand):
    uri = brand.logo_data_uri()
    assert uri and uri.startswith("data:image/png;base64,")


def test_series_colours_cycle_rather_than_run_out(brand):
    assert brand.series_color(0) == brand.categorical[0]
    assert brand.series_color(len(brand.categorical)) == brand.categorical[0]


# ------------------------------------------------------- missing template
def test_a_missing_template_degrades_visibly_and_still_works(tmp_path):
    """Generation never hard-depends on the asset — but it says what was lost."""
    template_registry.reset_cache()
    try:
        reference = template_registry.load(tmp_path / "not-here.pptx")
    finally:
        template_registry.reset_cache()

    assert reference.available is False
    assert reference.catalog.layouts, "a fallback catalog must still be usable"
    assert reference.catalog.choose(composition="single").layout is not None
    assert reference.brand.derived_from_template is False
    # The Deloitte defaults are preserved so nothing regresses visually...
    assert reference.brand.semantic["primary"] == "#046A38"
    # ...but the loss is stated rather than hidden.
    assert any("No PowerPoint template" in note for note in reference.notes)
    assert any("not applied" in note for note in reference.notes)


def test_the_registry_caches_on_content_not_on_path():
    # Self-contained: any test that resets the cache must not break this one.
    first = template_registry.default()
    again = template_registry.default()
    assert again is first, "re-reading a 920 KB zip per render is not free"
    assert first.template_digest and len(first.template_digest) == 16


def test_an_unreadable_theme_falls_back_rather_than_raising():
    palette = extract_theme(b"<not-xml", b"")
    assert palette.scheme == {}
    system = brand_system.build(palette, [])
    assert system.derived_from_template is False
    assert system.categorical, "a chart still needs colours"
    assert any("not measured" in note for note in system.notes)


def test_layout_extraction_is_pure(reference):
    """Describing a template must never modify it."""
    path = get_settings().pptx_template
    before = path.read_bytes()
    template = inspect(path)
    build_layouts(template, extract_theme(template.theme_xml, template.master_xml,
                                          template.layout_xml))
    assert path.read_bytes() == before
