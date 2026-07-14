"""Anthropic (Claude) backend — the default provider.

Chosen over OpenAI for one concrete reason: the §5.6 image pipeline needs a
vision-capable model, and `messages.parse()` gives us schema-validated output
without hand-parsing JSON (§11).
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Sequence

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm.base import DocumentPart, ImagePart, LLMError, NotConfigured, T

log = logging.getLogger("pmi.llm.anthropic")


class AnthropicClient:
    name = "anthropic"
    supports_vision = True

    def __init__(self, api_key: str) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise NotConfigured("the `anthropic` package is not installed") from exc

        self._anthropic = anthropic
        s = get_settings()
        # max_retries=0: we drive retries ourselves so a fallback is never delayed
        # by the SDK's own backoff on top of ours.
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=s.llm_timeout_s, max_retries=0
        )

    # ------------------------------------------------------------------ public
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
        s = get_settings()
        content: list[dict] = []
        for doc in documents:
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": doc.media_type,
                        "data": doc.b64,
                    },
                }
            )
        for img in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.media_type,
                        "data": img.b64,
                    },
                }
            )
        content.append({"type": "text", "text": user})

        kwargs: dict = {
            "model": model or s.llm_model,
            "max_tokens": max_tokens or s.llm_max_tokens,
            # Cached: the extraction/interpretation prompts are long and reused
            # for every file in a session.
            "system": [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": content}],
            "output_format": output_model,
        }
        if s.llm_thinking:
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": s.llm_effort}

        response = self._with_retries(kwargs)

        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(
                f"{kwargs['model']} returned no parseable {output_model.__name__} "
                f"(stop_reason={getattr(response, 'stop_reason', '?')})"
            )
        return parsed

    # ----------------------------------------------------------------- private
    def _with_retries(self, kwargs: dict):
        """Retry transient failures only. A 4xx is a bug in our request — surfacing
        it immediately is more useful than retrying it twice and then falling back."""
        s = get_settings()
        A = self._anthropic
        last: Exception | None = None

        for attempt in range(s.llm_max_retries + 1):
            try:
                return self._client.messages.parse(**kwargs)
            except A.RateLimitError as exc:
                last = exc
                delay = self._retry_after(exc, default=2.0 * (2**attempt))
                log.warning("rate limited; retrying in %.1fs", delay)
            except (A.APIConnectionError, A.InternalServerError) as exc:
                last = exc
                delay = 1.0 * (2**attempt)
                log.warning("transient API failure (%s); retrying in %.1fs",
                            type(exc).__name__, delay)
            except ValidationError as exc:
                # The model answered but broke the schema. Not retryable.
                raise LLMError(f"schema validation failed: {exc}") from exc
            except A.APIStatusError as exc:
                raise LLMError(f"{type(exc).__name__}: {exc}") from exc

            if attempt < s.llm_max_retries:
                time.sleep(delay)

        raise LLMError(f"giving up after {s.llm_max_retries + 1} attempts: {last}")

    @staticmethod
    def _retry_after(exc: Exception, default: float) -> float:
        response = getattr(exc, "response", None)
        header = getattr(response, "headers", {}) or {}
        try:
            return float(header.get("retry-after", default))
        except (TypeError, ValueError):
            return default
