"""Provenance (spec §5, §6.14).

"Every extracted item must retain its original source." Everything downstream —
conflict resolution by source priority (§9), the data-quality report (§13 sheet 10),
the source notes on a slide (§12.5) — depends on this record being complete and
honest.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, computed_field

from app.models.enums import ExtractionMethod, SourceFormat


class ImageRegion(BaseModel):
    """Where in a picture a value was read from (§5.6 step 9).

    Coordinates are in the ORIGINAL image's pixel space, not the resized copy we
    sent to the model — the user is going to look at their own file, not ours.
    """

    description: str = Field(
        description="Human-readable locator, e.g. 'cell at Probability=High / Impact=High'."
    )
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

    @property
    def has_box(self) -> bool:
        return None not in (self.x, self.y, self.width, self.height)


class SourceReference(BaseModel):
    """Where one value came from, and how much we trust it (§6.14)."""

    file_name: str
    file_type: SourceFormat

    # Locators — whichever apply to the format.
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    page_number: Optional[int] = None
    section_name: Optional[str] = None
    table_name: Optional[str] = None
    cell_range: Optional[str] = None
    image_region: Optional[ImageRegion] = None

    #: The value exactly as it appeared in the source, before normalization. This
    #: is what lets a conflict card show the user what the file actually said.
    original_value: Optional[str] = None

    extraction_method: ExtractionMethod = ExtractionMethod.TABLE_PARSE

    #: 0.0-1.0. Deterministic table reads are 1.0. Anything read out of a picture
    #: is capped well below that (§21.14) — see app/extractors/image.py.
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def location(self) -> Optional[str]:
        """One-line locator for display. Also the back-compat shim for the old
        `SourceRef.location` string that the generators print."""
        if self.sheet_name:
            base = f"sheet '{self.sheet_name}'"
            return f"{base}!{self.cell_range}" if self.cell_range else base
        if self.slide_number is not None:
            return f"slide {self.slide_number}"
        if self.page_number is not None:
            return f"page {self.page_number}"
        if self.image_region is not None:
            return f"image region: {self.image_region.description}"
        if self.table_name:
            return self.table_name
        if self.section_name:
            return self.section_name
        return None

    @property
    def is_low_confidence(self) -> bool:
        from app.config import get_settings

        return self.extraction_confidence < get_settings().low_confidence_threshold

    @property
    def needs_review(self) -> bool:
        """Should a human check this value before it goes in a board pack?

        Two ways to qualify. The obvious one is a low confidence score. The other is
        *how* it was read: anything interpreted from a picture or run through OCR is a
        transcription, and transcriptions have a failure rate that reading the
        spreadsheet does not (§21.14: "Treat image extraction as lower confidence unless
        confirmed").

        So a pin-sharp screenshot read at 0.88 still lands in the review panel. It is
        not *low* confidence — but nobody has confirmed it against the source system,
        and the user is the only one who can.
        """
        return self.is_low_confidence or self.extraction_method in (
            ExtractionMethod.LLM_VISION,
            ExtractionMethod.OCR,
        )

    def cite(self) -> str:
        """Citation string for a slide footnote or a report cell."""
        where = self.location
        text = f"{self.file_name} ({where})" if where else self.file_name
        if self.is_low_confidence:
            text += f" — low confidence {self.extraction_confidence:.0%}"
        return text
