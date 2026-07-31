"""PDF extractor (spec §5.3).

The spec is specific about the tooling: "Use PyMuPDF as the primary PDF extraction
library. Use pdfplumber for more detailed table extraction. If the PDF is image-based
or scanned, use OCR or a vision-capable model."

So: PyMuPDF reads the text, pdfplumber reads the tables, and any page with no text
layer is treated as an *image* — a scan of a signed governance doc has no characters
to extract, only pixels. Those pages go to the vision model as a `document` block,
and everything read from them is marked low-confidence, exactly like a screenshot
(§9: images are the least-trusted source).

The failure mode this avoids: a scanned status report yields zero text, the old code
returned zero records, and the report was silently built without it.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

import pdfplumber

from app.extractors.base import (
    classify_table,
    extract_actions_from_text,
    find_progress_mentions,
    make_source,
    rows_to_records,
)
from app.models.pmi import ExtractionMethod, SourceFormat

log = logging.getLogger("pmi.extract.pdf")

suffixes: tuple[str, ...] = (".pdf",)
format: SourceFormat = SourceFormat.PDF

#: Below this many characters, a page is almost certainly a scan, not a text PDF.
_SCANNED_CHAR_THRESHOLD = 40


def extract(path: Path) -> list[dict]:
    records: list[dict] = []
    scanned_pages: list[int] = []

    # --- text (PyMuPDF, the spec's primary) ---------------------------------
    page_text = _text_by_page(path)

    for page_number, text in page_text.items():
        source = make_source(
            path.name, format,
            page_number=page_number,
            extraction_method=ExtractionMethod.TEXT_REGEX,
        )
        if len(text.strip()) < _SCANNED_CHAR_THRESHOLD:
            scanned_pages.append(page_number)
            continue

        for pct in find_progress_mentions(text):
            records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                            "unit": "%", "source": source})
        for item in extract_actions_from_text(text):
            records.append({**item, "source": source})

        records.append({"type": "note", "text": text.strip()[:2000], "source": source})

    # --- tables (pdfplumber, the spec's detailed table pass) -----------------
    records.extend(_tables(path))

    # --- scanned pages (vision) ---------------------------------------------
    if scanned_pages:
        records.extend(_interpret_scanned(path, scanned_pages))

    return records


# ------------------------------------------------------------------- internals
def _text_by_page(path: Path) -> dict[int, str]:
    try:
        import fitz  # PyMuPDF
    except ImportError:  # pragma: no cover - declared dependency
        return _text_by_page_plumber(path)

    try:
        with fitz.open(str(path)) as doc:
            return {i: page.get_text() or "" for i, page in enumerate(doc, start=1)}
    except Exception as exc:
        log.warning("PyMuPDF could not read %s (%s); falling back to pdfplumber",
                    path.name, exc)
        return _text_by_page_plumber(path)


def _text_by_page_plumber(path: Path) -> dict[int, str]:
    with pdfplumber.open(str(path)) as pdf:
        return {i: (page.extract_text() or "")
                for i, page in enumerate(pdf.pages, start=1)}


def _tables(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                for table_index, table in enumerate(page.extract_tables() or [], start=1):
                    if not table or len(table) < 2:
                        continue
                    headers = [h or "" for h in table[0]]
                    source = make_source(
                        path.name, format,
                        page_number=page_number,
                        table_name=f"table {table_index}",
                        extraction_method=ExtractionMethod.TABLE_PARSE,
                    )
                    records.extend(rows_to_records(
                        headers, table[1:], classify_table(headers), source,
                    ))
    except Exception as exc:
        log.warning("table extraction failed for %s: %s", path.name, exc)
    return records


def _interpret_scanned(path: Path, pages: list[int]) -> list[dict]:
    """Send a scanned PDF to the vision model as a document block (§5.3).

    With no vision model available we say the pages could not be read. We do not
    return an empty list and let the report proceed as though the file were blank —
    that is the difference between "there was nothing in it" and "we could not open
    it", and only one of those is honest (§21.17).
    """
    from app.llm import DocumentPart, LLMError, get_client, vision_model
    from app.llm.prompts import load as load_prompt
    from app.llm.schemas import ImageExtraction

    listing = ", ".join(str(p) for p in pages)
    client = get_client()

    if not client.supports_vision:
        return [{
            "type": "note",
            "is_warning": True,
            "text": (
                f"Page(s) {listing} appear to be scanned images with no text layer and "
                f"could NOT be read: no vision-capable model is configured. Any tasks, "
                f"risks or figures on those pages are missing from this report."
            ),
            "source": make_source(
                path.name, format,
                extraction_method=ExtractionMethod.LLM_VISION,
                extraction_confidence=0.0,
            ),
        }]

    try:
        b64 = base64.standard_b64encode(path.read_bytes()).decode()
        result = client.structured(
            system=load_prompt("interpret_pmi_image"),
            user=(
                f"This is a scanned PDF with no text layer. Read pages {listing} and "
                f"extract the PMI information they contain."
            ),
            output_model=ImageExtraction,
            model=vision_model(),
            documents=[DocumentPart(b64=b64)],
        )
    except (LLMError, Exception) as exc:
        log.warning("vision pass failed for scanned %s: %s", path.name, exc)
        return [{
            "type": "note",
            "is_warning": True,
            "text": (
                f"Page(s) {listing} are scanned images and could not be interpreted "
                f"({type(exc).__name__}). Their content is missing from this report."
            ),
            "source": make_source(
                path.name, format,
                extraction_method=ExtractionMethod.LLM_VISION,
                extraction_confidence=0.0,
            ),
        }]

    # Reuse the image pipeline's confidence rules — a scan is a picture, and §9 ranks
    # what we read off it accordingly.
    from app.extractors.image import records_from_extraction

    return records_from_extraction(
        result,
        file_name=path.name,
        source_format=format,
        quality_penalty=1.0,
        page_number=pages[0] if pages else None,
    )
