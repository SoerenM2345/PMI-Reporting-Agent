"""Provider-neutral LLM interface (spec §15: the model/provider must be swappable).

One method, `structured()`, which always returns a validated Pydantic instance —
spec §11: "All LLM outputs used programmatically must be validated using Pydantic."
There is deliberately no free-text method: every call site in this codebase consumes
a schema, so text-in/text-out would only invite unvalidated parsing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Any provider failure that callers should fall back from, not crash on."""


class NotConfigured(LLMError):
    """No provider/key available — the deterministic fallback path should run."""


@dataclass(frozen=True)
class ImagePart:
    """A base64 image to attach to the user turn (§5.6)."""

    b64: str
    media_type: str  # "image/png" | "image/jpeg"


@dataclass(frozen=True)
class DocumentPart:
    """A base64 PDF. Used for scanned/image-based PDFs (§5.3) — the model reads
    the page images directly, so no local OCR dependency is required."""

    b64: str
    media_type: str = "application/pdf"


@runtime_checkable
class LLMClient(Protocol):
    name: str
    supports_vision: bool

    def structured(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        images: Sequence[ImagePart] = (),
        documents: Sequence[DocumentPart] = (),
    ) -> T:
        """Return a validated `output_model`, or raise LLMError."""
        ...
