"""What one assistant turn is.

The old shape was `Reply(kind, content: dict)` — eleven declared kinds, an
untyped payload, and a frontend `switch` that decided what the user saw. It made
the *card* the answer: a turn could only say something the card vocabulary had a
slot for, so the assistant could not explain, could not choose a shape to suit
the question, and could not simply talk. Two `preview` replies even carried
different keys, because nothing typed them.

Here the prose is the answer. `content` is Markdown and it is always the
substance of the reply. Everything else is something the UI *may* offer
underneath it:

* **`actions`** — an affordance, never information. Resolving a conflict with one
  click is genuinely better than typing "use the 82 from the tracker", so the
  button survives; what does not survive is the answer being a button.
* **`artifacts`** — files this turn produced. A generated deck is a thing the
  user can download, not a thing the assistant says instead of answering.

Actions are a discriminated union rather than a free dict. The dict is how the
old model let two sites build the same `kind` with different keys, and neither
the frontend nor a test could tell until something rendered blank.

Nothing here embeds the report. An `open_preview` action names the session and
version and the UI fetches `GET /api/content/{session_id}` when the user asks to
see it — so the transcript does not carry a second copy of a document that
already exists, and `agent/budget.py` has less to compact.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, computed_field


# ------------------------------------------------------------------- actions
class ResolveConflictAction(BaseModel):
    """§9 Mode A: the sources disagree and only the user can settle it."""

    type: Literal["resolve_conflict"] = "resolve_conflict"
    #: `Conflict.model_dump(mode="json")`. Kept whole rather than re-modelled:
    #: the resolve endpoint and the UI both already read this shape.
    conflicts: list[dict] = Field(default_factory=list)


class ChooseAudienceAction(BaseModel):
    """§4's question, asked openly rather than as a closed list.

    The four `Audience` values are planning keys — there are four report shapes
    and no more — but they are not the vocabulary a reader thinks in. The chips
    are examples; anything typed is kept verbatim for the title page.
    """

    type: Literal["choose_audience"] = "choose_audience"
    options: list[str] = Field(default_factory=list)
    free_text: bool = True
    placeholder: str = ""


class ChooseFormatAction(BaseModel):
    """The required first decision for a new report request."""

    type: Literal["choose_format"] = "choose_format"
    options: list[str] = Field(default_factory=lambda: [
        "powerpoint", "pdf", "word", "excel", "html", "chart",
    ])


class LowConfidenceItem(BaseModel):
    kind: str = ""
    label: str = ""
    confidence: float = 0.0


class ReviewFindingsAction(BaseModel):
    """§5.6. A count of findings that need checking is not a review — nobody can
    act on "three". Each one is named, with how confident the reading was."""

    type: Literal["review_low_confidence"] = "review_low_confidence"
    items: list[LowConfidenceItem] = Field(default_factory=list)


class OpenPreviewAction(BaseModel):
    """The drafted report, on request. The UI fetches it; it is not inlined."""

    type: Literal["open_preview"] = "open_preview"
    session_id: str = ""
    version: int = 0
    #: What "generate it as…" can produce from this draft.
    formats: list[str] = Field(default_factory=list)
    selected_format: Optional[str] = None
    open_by_default: bool = False
    approval_required: bool = False


Action = Annotated[
    Union[ResolveConflictAction, ChooseAudienceAction, ChooseFormatAction,
          ReviewFindingsAction,
          OpenPreviewAction],
    Field(discriminator="type"),
]


def _dedupe_actions(actions: list[Action]) -> list[Action]:
    """Compose affordances without rendering the same control twice.

    Data review can surface every open conflict while planning separately
    surfaces the critical subset. Those are two explanations of one decision,
    not two decisions. Merge conflict payloads by id and collapse other exact
    duplicates while preserving their first position in the turn.
    """
    import json

    merged: list[Action] = []
    resolve: Optional[ResolveConflictAction] = None
    conflict_positions: dict[str, int] = {}

    for action in actions:
        if isinstance(action, ResolveConflictAction):
            if resolve is None:
                resolve = action.model_copy(deep=True)
                resolve.conflicts = []
                merged.append(resolve)
            for conflict in action.conflicts:
                key = str(conflict.get("conflict_id") or json.dumps(
                    conflict, sort_keys=True, default=str))
                if key in conflict_positions:
                    resolve.conflicts[conflict_positions[key]] = conflict
                else:
                    conflict_positions[key] = len(resolve.conflicts)
                    resolve.conflicts.append(conflict)
            continue
        if action not in merged:
            merged.append(action)
    return merged


# ----------------------------------------------------------------- artifacts
ArtifactType = Literal["pptx", "docx", "pdf", "xlsx", "html", "md", "png", "other"]

_EXTENSIONS: dict[str, ArtifactType] = {
    ".pptx": "pptx", ".docx": "docx", ".pdf": "pdf", ".xlsx": "xlsx",
    ".html": "html", ".htm": "html", ".md": "md", ".png": "png",
}


class GeneratedArtifact(BaseModel):
    """A file this turn produced.

    `status` exists because generation can be interrupted: a stopped run must
    leave something the UI can show as stopped, and must never leave a partial
    file labelled ready.
    """

    filename: str
    session_id: str = ""
    type: ArtifactType = "other"
    title: str = ""
    status: Literal["generating", "ready", "failed", "stopped"] = "ready"

    @computed_field                                    # type: ignore[prop-decorator]
    @property
    def download_url(self) -> str:
        """Serialized, not just available in Python — a nested `model_dump`
        uses Pydantic's own serializer and never calls an overridden one, so a
        plain `@property` would reach the UI on a bare artifact and vanish the
        moment it sat inside a `ChatAnswer`."""
        return f"/api/download/{self.session_id}/{self.filename}"


def artifact(filename: str, session_id: str, *, title: str = "",
             status: str = "ready") -> GeneratedArtifact:
    """Classify a produced file by its extension, so callers do not repeat it."""
    from pathlib import Path

    suffix = Path(filename).suffix.lower()
    return GeneratedArtifact(
        filename=filename, session_id=session_id,
        type=_EXTENSIONS.get(suffix, "other"),
        title=title or Path(filename).stem.replace("_", " "),
        status=status,                                 # type: ignore[arg-type]
    )


# ------------------------------------------------------- what the user sent
class ChatAttachment(BaseModel):
    """A file on a *user's* message.

    Stored on the message rather than derived from the session's file list, so
    reopening a chat still shows which files went with which request. The name
    was already stored; nothing else was, which is why an uploaded file rendered
    as an empty bubble — the UI had a filename it never read and no type, size
    or status at all.
    """

    filename: str
    session_id: str = ""
    mime_type: str = ""
    size: Optional[int] = None
    status: Literal["uploading", "ready", "failed"] = "ready"
    error: str = ""

    @computed_field                                    # type: ignore[prop-decorator]
    @property
    def extension(self) -> str:
        from pathlib import Path

        return Path(self.filename).suffix.lower().lstrip(".")

    @computed_field                                    # type: ignore[prop-decorator]
    @property
    def download_url(self) -> str:
        return f"/api/download/{self.session_id}/{self.filename}"


def attachment(filename: str, session_id: str, *, size: Optional[int] = None,
               status: str = "ready", error: str = "") -> dict:
    """One attachment, as the transcript stores it."""
    import mimetypes

    mime, _ = mimetypes.guess_type(filename)
    return ChatAttachment(
        filename=filename, session_id=session_id, mime_type=mime or "",
        size=size, status=status,                      # type: ignore[arg-type]
        error=error,
    ).model_dump(mode="json")


# -------------------------------------------------------------- the answer
class ChatAnswer(BaseModel):
    """One assistant turn. Prose is the answer."""

    content: str = ""
    format: Literal["markdown"] = "markdown"
    actions: list[Action] = Field(default_factory=list)
    artifacts: list[GeneratedArtifact] = Field(default_factory=list)
    status: Literal["completed", "stopped", "failed"] = "completed"

    def then(self, other: Optional["ChatAnswer"]) -> "ChatAnswer":
        """Compose two things said in one turn into one message.

        A turn that re-read the files, found a conflict and drafted a report
        used to arrive as three separate bubbles, which reads as three
        interruptions rather than one answer. Paragraphs join; affordances
        accumulate.
        """
        if other is None:
            return self
        parts = [part for part in (self.content.strip(), other.content.strip())
                 if part]
        return ChatAnswer(
            content="\n\n".join(parts),
            actions=_dedupe_actions([*self.actions, *other.actions]),
            artifacts=[*self.artifacts, *other.artifacts],
            # A failure anywhere in the turn is the turn's status: a message that
            # reports an error and calls itself completed is lying about itself.
            status=_worst(self.status, other.status),
        )

    @property
    def is_empty(self) -> bool:
        return not (self.content.strip() or self.actions or self.artifacts)


_SEVERITY = {"completed": 0, "stopped": 1, "failed": 2}


def _worst(left: str, right: str) -> str:
    return left if _SEVERITY[left] >= _SEVERITY[right] else right


def say(content: str, **kwargs) -> ChatAnswer:
    """The common case: the assistant says something."""
    return ChatAnswer(content=content, **kwargs)
