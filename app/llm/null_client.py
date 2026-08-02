"""The no-key client.

Every call raises `NotConfigured`, which each task in `tasks.py` catches and
answers from `fallbacks.py` instead. That keeps the whole pipeline — extraction,
standardization, conflict detection, generation — runnable with zero cost and zero
credentials, which is what makes the acceptance test cheap to run in CI.

It raises rather than returning empty output on purpose: a task that silently
returned `[]` would be indistinguishable from a model that genuinely found nothing.
"""
from __future__ import annotations

from typing import Optional, Sequence

from app.llm.base import DocumentPart, ImagePart, NotConfigured, T


class NullClient:
    name = "none"
    supports_vision = False

    def __init__(self, reason: str = "no LLM provider configured") -> None:
        self._reason = reason

    def structured(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout_s: Optional[float] = None,
        max_retries: Optional[int] = None,
        images: Sequence[ImagePart] = (),
        documents: Sequence[DocumentPart] = (),
    ) -> T:
        raise NotConfigured(self._reason)
