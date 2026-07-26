"""Image extractor (spec §5.6).

Screenshots of trackers, risk heatmaps, milestone timelines, photos of whiteboards,
scanned pages. §5.6 gives a ten-step pipeline; steps 1-4 (validate, orient, resize,
enhance) live in `app/utils/images.py`, steps 5-10 are here.

Two rules govern this module, and they are the reason it exists at all rather than
just calling the model and trusting the answer:

**§21.14 — "Treat image extraction as lower confidence unless confirmed."**
Confidence is computed in Python from measured image quality and the model's own
self-report, then *capped below 1.0*. An image reading is never as good as reading
the tracker. §9 ranks images last for exactly this reason, so any figure read off a
screenshot loses an automatic conflict against the spreadsheet it was screenshotted
from — which is correct.

**§7 — "The agent must never silently invent missing PMI information."**
With no vision model and no local OCR, this extractor reports that it could not read
the image. It does not return an empty list and let the report proceed as though the
file were blank. "There was nothing in it" and "I could not open it" are different
statements, and only one of them is true.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.extractors.base import make_source
from app.llm import ImagePart, LLMError, get_client, vision_model
from app.llm.prompts import load as load_prompt
from app.llm.schemas import ExtractedImageItem, ImageExtraction
from app.models.pmi import ExtractionMethod, ImageRegion, SourceFormat
from app.utils.images import (
    SUPPORTED_SUFFIXES,
    PreparedImage,
    UnreadableImage,
    prepare,
    rescale_region,
)

log = logging.getLogger("pmi.extract.image")

suffixes: tuple[str, ...] = SUPPORTED_SUFFIXES
format: SourceFormat = SourceFormat.IMAGE

#: Nothing read from a picture ever reaches full confidence (§21.14). Even a
#: pin-sharp screenshot is a transcription, and transcriptions have a failure rate
#: that reading the source file does not.
_CEILING = 0.90
_FLOOR = 0.05

_LEGIBILITY_FACTOR = {"good": 1.0, "medium": 0.85, "poor": 0.60}
_HANDWRITING_FACTOR = 0.80
_CROPPED_FACTOR = 0.90
_OCR_CONFIDENCE = 0.40


def extract(path: Path) -> list[dict]:
    try:
        prepared = prepare(path)
    except UnreadableImage as exc:
        return [_unreadable(path, str(exc))]

    client = get_client()

    if client.supports_vision:
        try:
            result = _interpret(prepared)
        except (LLMError, Exception) as exc:
            log.warning("vision interpretation failed for %s: %s", path.name, exc)
            return _ocr_or_give_up(path, prepared, reason=f"{type(exc).__name__}: {exc}")

        return records_from_extraction(
            result,
            file_name=path.name,
            source_format=format,
            quality_penalty=prepared.quality.penalty,
            quality=prepared.quality,
        )

    return _ocr_or_give_up(
        path, prepared, reason="no vision-capable model is configured"
    )


def _interpret(prepared: PreparedImage) -> ImageExtraction:
    """One call: classify the content AND read it (§5.6 steps 5-8).

    Folded together deliberately — a separate "what kind of image is this?" call
    would cost a round trip to learn something the model works out anyway while
    interpreting.
    """
    return get_client().structured(
        system=load_prompt("interpret_pmi_image"),
        user=(
            "Read this image and extract every Post-Merger Integration fact you can "
            "actually see. Leave out anything you cannot read."
        ),
        output_model=ImageExtraction,
        model=vision_model(),
        images=[ImagePart(b64=prepared.b64, media_type=prepared.media_type)],
    )


# --------------------------------------------------------------------- mapping
def records_from_extraction(
    result: ImageExtraction,
    *,
    file_name: str,
    source_format: SourceFormat,
    quality_penalty: float = 1.0,
    quality=None,
    page_number: Optional[int] = None,
) -> list[dict]:
    """Turn a vision reading into raw records with honest confidence.

    Shared with the PDF extractor: a scanned page is a picture, and everything read
    off it earns exactly the same scepticism.
    """
    records: list[dict] = []

    for item in result.items:
        confidence = _score(item, result, quality_penalty)
        source = make_source(
            file_name,
            source_format,
            page_number=page_number,
            image_region=_region(item, quality),
            original_value=item.original_value,
            extraction_method=ExtractionMethod.LLM_VISION,
            extraction_confidence=confidence,
        )

        record: dict = {"type": item.type, "source": source}
        if item.type in ("kpi", "synergy"):
            record["name"] = item.title
        record["title"] = item.title
        # Field values are strings from the model; standardize.py parses and
        # validates them like any other source's. Nothing bypasses that.
        record.update({k: v for k, v in item.fields.items() if v not in (None, "")})

        records.append(record)

    # The model's own caveats are user-visible, not debug output — §5.6 requires
    # low-confidence findings be shown for review.
    if result.notes:
        records.append({
            "type": "note",
            "text": "Image interpretation caveats: " + " ".join(result.notes),
            "source": make_source(
                file_name, source_format,
                page_number=page_number,
                extraction_method=ExtractionMethod.LLM_VISION,
                extraction_confidence=_CEILING * quality_penalty,
            ),
        })

    log.info(
        "%s: read %d item(s) [%s, legibility=%s%s%s]",
        file_name, len(result.items),
        ", ".join(c for c in result.content_types) or "unclassified",
        result.legibility,
        ", handwritten" if result.is_handwritten else "",
        ", cropped" if result.is_cropped else "",
    )
    return records


def _score(
    item: ExtractedImageItem, result: ImageExtraction, quality_penalty: float
) -> float:
    """Combine the model's self-report with what we measured ourselves (§21.14).

    The model is not the authority on how much to trust the model. Its confidence is
    an input, multiplied down by every condition §5.6 says should reduce trust, and
    capped so that no image reading can ever outrank a spreadsheet.
    """
    confidence = item.model_confidence
    confidence *= _LEGIBILITY_FACTOR.get(result.legibility, 0.7)
    confidence *= quality_penalty

    if result.is_handwritten:
        confidence *= _HANDWRITING_FACTOR
    if result.is_cropped:
        confidence *= _CROPPED_FACTOR

    return round(max(_FLOOR, min(confidence, _CEILING)), 3)


def _region(item: ExtractedImageItem, quality) -> Optional[ImageRegion]:
    if item.region is None:
        return None

    box = None
    if None not in (item.region.x, item.region.y, item.region.width, item.region.height):
        box = (item.region.x, item.region.y, item.region.width, item.region.height)
        if quality is not None:
            # Back into the user's own pixel space — they will open their screenshot,
            # not our resized copy.
            box = rescale_region(box, quality)

    return ImageRegion(
        description=item.region.description,
        x=box[0] if box else None,
        y=box[1] if box else None,
        width=box[2] if box else None,
        height=box[3] if box else None,
    )


# ------------------------------------------------------------------- fallbacks
def _ocr_or_give_up(path: Path, prepared: PreparedImage, reason: str) -> list[dict]:
    """Tier 2 (local OCR) then tier 3 (admit defeat). Never tier 4 (guess)."""
    ocr_text = _try_ocr(prepared)

    if ocr_text:
        from app.extractors.base import extract_actions_from_text, find_progress_mentions

        source = make_source(
            path.name, format,
            extraction_method=ExtractionMethod.OCR,
            extraction_confidence=_OCR_CONFIDENCE,
        )
        records: list[dict] = [{
            "type": "note",
            "is_warning": True,
            "text": (
                f"Read by local OCR only ({reason}) — no semantic interpretation, so "
                f"charts, colours and table structure in this image were NOT understood. "
                f"Text found: {ocr_text[:1500]}"
            ),
            "source": source,
        }]
        for pct in find_progress_mentions(ocr_text):
            records.append({"type": "kpi", "name": "Overall Progress", "value": pct,
                            "unit": "%", "source": source})
        for action in extract_actions_from_text(ocr_text):
            records.append({**action, "source": source})
        return records

    return [_unreadable(
        path,
        f"{reason}, and no local OCR is available. Install a vision model "
        f"(set ANTHROPIC_API_KEY) or local OCR (pip install -r requirements-ocr.txt).",
    )]


def _try_ocr(prepared: PreparedImage) -> Optional[str]:
    """Optional local OCR. Deliberately not a core dependency — it is a weak
    substitute that reads text but understands nothing (a risk heatmap is colour and
    position, and OCR sees neither)."""
    try:
        import base64
        import io

        import pytesseract
        from PIL import Image
    except ImportError:
        return None

    try:
        image = Image.open(io.BytesIO(base64.b64decode(prepared.b64)))
        text = pytesseract.image_to_string(image)
    except Exception as exc:
        log.warning("local OCR failed: %s", exc)
        return None

    return text.strip() or None


def _unreadable(path: Path, reason: str) -> dict:
    """The honest answer.

    `is_warning` promotes this out of the notes list and into the run's warnings, so it
    reaches the data-quality report, the deck's limitations slide and the UI. Otherwise
    an uninterpretable screenshot is indistinguishable from an empty one, and the user
    would never learn that their risk dashboard contributed nothing (§21.17).
    """
    return {
        "type": "note",
        "is_warning": True,
        "text": (
            f"Could NOT interpret this image: {reason} "
            f"Any tasks, risks or figures in it are MISSING from this report."
        ),
        "source": make_source(
            path.name, format,
            extraction_method=ExtractionMethod.LLM_VISION,
            extraction_confidence=0.0,
        ),
    }
