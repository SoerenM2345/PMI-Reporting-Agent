"""P2/P3: extractors, including the image pipeline (spec §5)."""
from __future__ import annotations

import pytest

from app import llm
from app.agent.standardize import standardize
from app.extractors import SUPPORTED_EXTENSIONS, extract_file, format_of
from app.extractors import image as image_extractor
from app.models.pmi import ExtractionMethod, Severity, SourceFormat
from app.utils.images import prepare


# ------------------------------------------------------------------- dispatch
def test_every_format_in_the_spec_is_supported():
    """§4 step 1: spreadsheets, presentations, documents, web content, images."""
    required = {".xlsx", ".xls", ".csv", ".pptx", ".pdf", ".docx",
                ".html", ".htm", ".png", ".jpg", ".jpeg"}
    assert required <= SUPPORTED_EXTENSIONS


def test_unsupported_type_raises_rather_than_returning_nothing():
    with pytest.raises(ValueError, match="Unsupported file type"):
        extract_file(__import__("pathlib").Path("notes.txt"))


# ------------------------------------------------------------------- §5.1 CSV
def test_csv_extraction_with_european_semicolons(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text(
        "Risk;Owner;Impact;Status\n"
        "Payroll data incomplete;Anna Schmidt;High;Open\n"
        "Vendor contract lapse;Jonas Weber;Critical;Open\n",
        encoding="utf-8",
    )
    records = extract_file(path)

    assert format_of(path) is SourceFormat.CSV
    risks = [r for r in records if r["type"] == "risk"]
    assert len(risks) == 2
    assert risks[0]["owner"] == "Anna Schmidt"
    # Provenance down to the row (§6.14)
    assert risks[0]["source"].cell_range == "A2:D2"


def test_csv_with_a_title_row_above_the_header(tmp_path):
    """Tool exports routinely prepend a title line. Assuming row 0 is the header
    silently yields zero rows."""
    path = tmp_path / "tracker.csv"
    path.write_text(
        "Project Aurora - Risk Register (exported 01-07-2026)\n"
        "\n"
        "Risk,Owner,Impact\n"
        "TSA exit slipping,Lisa Chen,High\n",
        encoding="utf-8",
    )
    risks = [r for r in extract_file(path) if r["type"] == "risk"]
    assert len(risks) == 1
    assert risks[0]["title"] == "TSA exit slipping"


# ----------------------------------------------------------------- §5.1 Excel
def test_excel_reads_stacked_tables_on_one_sheet(tmp_path):
    """PMI trackers stack tables ("Open Risks" over "Closed Risks"). Reading only the
    first header row drops everything below the second."""
    import xlsxwriter

    path = tmp_path / "stacked.xlsx"
    wb = xlsxwriter.Workbook(str(path))
    ws = wb.add_worksheet("Risks")
    rows = [
        ["Risk", "Owner", "Impact"],
        ["Open risk one", "Anna", "High"],
        ["Open risk two", "Jonas", "Medium"],
        [],
        [],
        ["Risk", "Owner", "Impact"],
        ["Closed risk one", "Lisa", "Low"],
    ]
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            ws.write(i, j, value)
    wb.close()

    risks = [r for r in extract_file(path) if r["type"] == "risk"]
    titles = {r["title"] for r in risks}
    assert titles == {"Open risk one", "Open risk two", "Closed risk one"}


def test_a_data_row_is_never_mistaken_for_a_header(sample_files):
    """Regression. Header detection runs on every row, so a false positive on a data
    cell promotes that row to a header and splits the table there — silently losing
    every row below it.

    The cases that actually bit: "Not Started" matched a 3-letter alias "art", and
    "In Progress" matched "progress". Both are ordinary status values.
    """
    from app.extractors.base import normalize_header

    for value in ("Not Started", "In Progress", "Done", "Anna Schmidt", "High", "EUR"):
        assert normalize_header(value) is None, f"{value!r} is data, not a column header"

    # ...while real headers still map.
    assert normalize_header("Progress %") == "progress_pct"
    assert normalize_header("Owner (Function)") == "owner"
    assert normalize_header("Realized") == "realized"


def test_every_entity_type_survives_extraction(sample_files):
    """All ten record types the model supports must actually come out of the sample
    set. A type that never populates is a table the classifier is quietly dropping —
    which is how a synergy tracker (the artefact the deal was justified with) ends up
    read as a list of KPIs and never reaches a Finance deck."""
    from collections import Counter

    found = Counter()
    for path in sample_files.iterdir():
        if path.is_file():
            found.update(r["type"] for r in extract_file(path))

    for record_type in ("task", "milestone", "risk", "issue", "dependency",
                        "decision", "budget", "synergy", "kpi"):
        assert found[record_type] > 0, f"no {record_type} records in the §19 sample set"


def test_excel_carries_sheet_and_cell_provenance(sample_files):
    records = extract_file(sample_files / "integration_tracker.xlsx")
    task = next(r for r in records if r["type"] == "task")
    ref = task["source"]

    assert ref.file_type is SourceFormat.EXCEL
    assert ref.sheet_name  # which sheet
    assert ref.cell_range  # which row
    assert ref.extraction_confidence == 1.0  # a tracker read is fully trusted


# ------------------------------------------------------------ §5.6 image: no key
def test_an_image_without_a_vision_model_says_so_instead_of_guessing(
    sample_files, monkeypatch
):
    """§7: 'never silently invent'. An empty list would be read downstream as
    'the screenshot contained nothing', which is a different claim entirely."""
    monkeypatch.setattr("app.config.settings.anthropic_api_key", None)
    llm.reset_client()

    records = extract_file(sample_files / "risk_dashboard.png")

    assert len(records) == 1
    note = records[0]
    assert note["type"] == "note"
    assert "Could NOT interpret" in note["text"]
    assert "MISSING from this report" in note["text"]
    assert note["source"].extraction_confidence == 0.0


# --------------------------------------------------------- §5.6 image: vision
def test_image_extraction_reads_the_dashboard(sample_files, fake_vision):
    records = extract_file(sample_files / "risk_dashboard.png")

    risks = [r for r in records if r["type"] == "risk"]
    assert any("GDPR" in r["title"] for r in risks)
    assert fake_vision.calls == 1

    gdpr = next(r for r in risks if "GDPR" in r["title"])
    assert gdpr["owner"] == "Lisa Chen"
    assert gdpr["probability"] == "4"
    assert gdpr["impact"] == "5"


def test_image_confidence_is_capped_below_a_spreadsheet_read(sample_files, fake_vision):
    """§21.14: 'Treat image extraction as lower confidence unless confirmed.'

    The fixture's model_confidence is 0.88 — high. It must still land below 1.0, so a
    screenshot can never outrank the tracker it was taken from.
    """
    records = extract_file(sample_files / "risk_dashboard.png")
    gdpr = next(r for r in records if r["type"] == "risk" and "GDPR" in r["title"])
    ref = gdpr["source"]

    assert ref.extraction_method is ExtractionMethod.LLM_VISION
    assert 0.0 < ref.extraction_confidence <= 0.90
    assert ref.file_type is SourceFormat.IMAGE


def test_the_models_confidence_is_not_taken_at_face_value(sample_files, fake_vision):
    """A perfectly confident model reading a blurry image is still reading a blurry
    image. Python multiplies the self-report down; it does not defer to it."""
    from app.llm.schemas import ExtractedImageItem, ImageExtraction

    overconfident = ImageExtraction(
        content_types=["table"],
        legibility="poor",
        is_handwritten=True,
        is_cropped=True,
        items=[ExtractedImageItem(type="risk", title="Barely legible",
                                  model_confidence=1.0)],
    )
    records = image_extractor.records_from_extraction(
        overconfident,
        file_name="blur.jpg",
        source_format=SourceFormat.IMAGE,
        quality_penalty=0.85 * 0.90,  # low-res AND blurry
    )
    confidence = records[0]["source"].extraction_confidence

    # 1.0 * poor(0.60) * handwritten(0.80) * cropped(0.90) * quality(0.765) = ~0.33
    assert confidence < 0.4
    assert records[0]["source"].is_low_confidence


def test_image_regions_map_back_to_the_users_own_pixels(sample_files, fake_vision):
    """The user opens their screenshot, not our resized copy (§5.6 step 9)."""
    records = extract_file(sample_files / "risk_dashboard.png")
    gdpr = next(r for r in records if r["type"] == "risk" and "GDPR" in r["title"])
    region = gdpr["source"].image_region

    assert region is not None
    assert "matrix" in region.description.lower()
    assert region.has_box


def test_the_models_caveats_reach_the_user(sample_files, fake_vision):
    """§5.6: 'Low-confidence findings should be shown to the user for review.' The
    things the model could NOT read are exactly what a reviewer needs to know."""
    records = extract_file(sample_files / "risk_dashboard.png")
    caveats = [r for r in records if r["type"] == "note"
               and "caveat" in r["text"].lower()]

    assert caveats
    assert "obscured by a cursor" in caveats[0]["text"]


def test_image_findings_survive_standardization_with_their_confidence(
    sample_files, fake_vision
):
    """End to end: a risk that exists only in a screenshot reaches the data model,
    scored, and flagged for review."""
    records = extract_file(sample_files / "risk_dashboard.png")
    model = standardize(records, ["risk_dashboard.png"])

    gdpr = next(r for r in model.risks if "GDPR" in r.title)
    assert gdpr.probability == 4
    assert gdpr.impact == 5
    assert gdpr.primary_source.file_type is SourceFormat.IMAGE

    from app.agent.calculations import recompute_derived

    model, _ = recompute_derived(model)
    assert gdpr.risk_score == 20
    assert gdpr.rating is Severity.CRITICAL


# ------------------------------------------------------- §5.6 preprocessing
def test_preprocessing_measures_quality_rather_than_assuming_it(sample_files):
    crisp = prepare(sample_files / "risk_dashboard.png")
    photo = prepare(sample_files / "milestone_whiteboard.jpg")

    assert crisp.media_type == "image/png"
    assert crisp.quality.is_low_res is False
    # The whiteboard is a noisy, rotated, JPEG-compressed phone photo.
    assert photo.quality.penalty <= crisp.quality.penalty


def test_oversized_images_are_downscaled(tmp_path):
    """Beyond ~1568px the model downsamples anyway; sending 4000px only costs tokens."""
    from PIL import Image

    path = tmp_path / "huge.png"
    Image.new("RGB", (4000, 3000), (255, 255, 255)).save(path)

    prepared = prepare(path)
    assert prepared.quality.width == 4000       # original dimensions retained
    assert prepared.quality.scale_factor > 1.0  # ...but we sent a smaller copy
