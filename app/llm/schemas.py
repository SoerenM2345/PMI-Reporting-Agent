"""Pydantic output contracts for every LLM task (spec §11).

Nothing the model returns enters the pipeline except through one of these. Note
what is *absent*: no schema here carries a figure that lands in a calculation.
Progress percentages, budget variances, risk scores and synergy values all come
from the extractors and `app/agent/calculations.py` in deterministic Python — the
model classifies, matches and words things, but it never does arithmetic (§11).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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
        default="",
        description=(
            "Where this sits in the image, in words a person could follow — "
            "e.g. 'red cell at Probability=High / Impact=High', 'third bar from the left'."
        )
    )
    box: list[int] = Field(
        default_factory=list,
        min_length=0,
        max_length=4,
        description=(
            "Empty if exact coordinates are unknown; otherwise exactly "
            "[left, top, width, height] in pixels."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_coordinates(cls, value):
        if isinstance(value, dict) and "box" not in value:
            coordinates = [
                value.get("x"), value.get("y"),
                value.get("width"), value.get("height"),
            ]
            value = {k: v for k, v in value.items()
                     if k not in {"x", "y", "width", "height"}}
            if None not in coordinates:
                value["box"] = coordinates
        return value

    @property
    def x(self) -> Optional[int]:
        return self.box[0] if len(self.box) == 4 else None

    @property
    def y(self) -> Optional[int]:
        return self.box[1] if len(self.box) == 4 else None

    @property
    def width(self) -> Optional[int]:
        return self.box[2] if len(self.box) == 4 else None

    @property
    def height(self) -> Optional[int]:
        return self.box[3] if len(self.box) == 4 else None


ImageFieldName = Literal[
    "owner", "status", "due_date", "workstream", "probability", "impact",
    "severity", "mitigation", "category", "planned", "actual", "forecast",
    "target", "value", "unit", "description",
]


class ImageAttribute(BaseModel):
    """One closed PMI attribute read from an image.

    A list of name/value pairs is intentionally used instead of sixteen nullable
    object properties. Anthropic has a finite structured-output grammar budget;
    the previous shape exceeded it and returned HTTP 400 before reading the
    image. The enum remains closed, so unknown fields still cannot enter the
    standardizer.
    """

    name: ImageFieldName
    value: str


class ExtractedImageItem(BaseModel):
    """One PMI fact read out of a picture."""

    type: RecordType = Field(description="Which PMI entity this is.")
    title: str = Field(description="The item's name, exactly as written in the image.")
    fields: list[ImageAttribute] = Field(
        default_factory=list,
        description=(
            "Other attributes you can read, as name/value pairs. Use these names "
            "where they apply: owner, status, due_date, workstream, probability, impact, "
            "severity, mitigation, category, planned, actual, forecast, target, value, "
            "unit, description. Omit anything the image does not state — do not guess."
        ),
    )

    @field_validator("fields", mode="before")
    @classmethod
    def _accept_legacy_field_object(cls, value):
        """Keep stored readings made with the former ``{name: value}`` shape readable."""
        if isinstance(value, dict):
            return [
                {"name": name, "value": str(raw)}
                for name, raw in value.items()
                if raw not in (None, "")
            ]
        return value
    original_value: str = Field(
        default="",
        description="The raw text as it literally appears in the image, before any tidying.",
    )
    region: VisionRegion = Field(
        default_factory=VisionRegion,
        description="Where the item appears; leave description and box empty if unknown.",
    )
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
