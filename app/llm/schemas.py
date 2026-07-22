"""Pydantic output contracts for every LLM task (spec §11).

Nothing the model returns enters the pipeline except through one of these. Note
what is *absent*: no schema here carries a figure that lands in a calculation.
Progress percentages, budget variances, risk scores and synergy values all come
from the extractors and `app/agent/calculations.py` in deterministic Python — the
model classifies, matches and words things, but it never does arithmetic (§11).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.pmi import Audience

#: `word`, `pdf` and `html` render from the approved `ReportContent`, so they
#: say exactly what the user read in the preview. `excel` remains a data dump of
#: every sheet (§13) rather than an audience-shaped narrative.
OutputType = Literal["powerpoint", "excel", "chart", "word", "pdf", "html"]


class RequestParse(BaseModel):
    """What the user asked for (spec §4 step 2)."""

    output_type: OutputType = Field(
        description="The deliverable the user is asking for."
    )
    audience: Optional[Audience] = Field(
        default=None,
        description=(
            "Target audience if the request states or clearly implies one. "
            "Null when it is genuinely ambiguous — the app will ask the user "
            "rather than guess (§4)."
        ),
    )
    topic: str = Field(
        description="Short slug of the PMI topic in focus, e.g. 'risks', 'status', 'synergies'."
    )


class SummaryBullets(BaseModel):
    """Executive summary prose (spec §11: 'Generating executive summaries')."""

    bullets: list[str] = Field(
        min_length=1,
        max_length=8,
        description=(
            "3-6 crisp management bullets. Use ONLY figures present in the supplied "
            "data. Never introduce a number that is not in the data."
        ),
    )


# ------------------------------------------------------- image interpretation (§5.6)
ImageContent = Literal[
    "text", "table", "chart", "timeline", "diagram", "dashboard", "handwriting"
]

RecordType = Literal[
    "task", "milestone", "risk", "issue", "dependency", "decision",
    "budget", "synergy", "kpi", "note",
]


class VisionRegion(BaseModel):
    """Where in the image a value was read from (§5.6 step 9)."""

    description: str = Field(
        description=(
            "Where this sits in the image, in words a person could follow — "
            "e.g. 'red cell at Probability=High / Impact=High', 'third bar from the left'."
        )
    )
    x: Optional[int] = Field(
        default=None, description="Left edge in pixels, if you can locate it."
    )
    y: Optional[int] = Field(default=None, description="Top edge in pixels.")
    width: Optional[int] = Field(default=None, description="Box width in pixels.")
    height: Optional[int] = Field(default=None, description="Box height in pixels.")


class ExtractedImageItem(BaseModel):
    """One PMI fact read out of a picture."""

    type: RecordType = Field(description="Which PMI entity this is.")
    title: str = Field(description="The item's name, exactly as written in the image.")
    fields: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Other attributes you can read, as flat key/value strings. Use these keys "
            "where they apply: owner, status, due_date, workstream, probability, impact, "
            "severity, mitigation, category, planned, actual, forecast, target, value, "
            "unit, description. Omit anything the image does not state — do not guess."
        ),
    )
    original_value: Optional[str] = Field(
        default=None,
        description="The raw text as it literally appears in the image, before any tidying.",
    )
    region: Optional[VisionRegion] = None
    model_confidence: float = Field(
        ge=0.0, le=1.0,
        description=(
            "How sure you are that you read THIS item correctly. Be honest and be "
            "harsh: 0.9 for crisp printed text you can read without effort, 0.5 for "
            "something you are inferring from a colour or a position, 0.3 for "
            "handwriting or a blurred cell. A wrong figure stated confidently is far "
            "more damaging than an omitted one."
        ),
    )


class ImageExtraction(BaseModel):
    """The full reading of one image (§5.6)."""

    content_types: list[ImageContent] = Field(
        default_factory=list,
        description="Everything this image contains (§5.6 step 5). May be several.",
    )
    legibility: Literal["good", "medium", "poor"] = Field(
        description="How readable the image is overall."
    )
    is_handwritten: bool = Field(
        default=False, description="True if any content you extracted is handwritten."
    )
    is_cropped: bool = Field(
        default=False,
        description="True if content is cut off at an edge — a table whose rows run "
                    "past the bottom, a chart with a clipped axis.",
    )
    items: list[ExtractedImageItem] = Field(
        default_factory=list,
        description="The PMI facts you can read. Empty if the image contains none.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description=(
            "Anything the reader should know: values you could not make out, colours "
            "you could not distinguish, parts of the image you could not interpret."
        ),
    )
