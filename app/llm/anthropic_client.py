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
        timeout_s: Optional[float] = None,
        max_retries: Optional[int] = None,
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

        # Anthropic prompt caching has a minimum useful prefix and a cache write
        # on the first request.  Marking every tiny classifier system prompt as
        # cacheable made interactive replies pay that setup cost without a
        # reusable payload.  Long extraction/planning instructions still get
        # cached; short routing prompts go as ordinary strings.
        system_payload: object = system
        if len(system) >= 4096:
            system_payload = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        kwargs: dict = {
            "model": model or s.llm_model,
            "max_tokens": max_tokens or s.llm_max_tokens,
            "system": system_payload,
            "messages": [{"role": "user", "content": content}],
            "output_format": output_model,
            "service_tier": "auto",
        }
        if timeout_s is not None:
            # Per-task override. Vision uses this to fail fast without changing
            # the more tolerant timeout for report prose and planning.
            kwargs["timeout"] = timeout_s
        if s.llm_thinking:
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": s.llm_effort}

        response = self._with_retries(kwargs, max_retries=max_retries)

        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(
                f"{kwargs['model']} returned no parseable {output_model.__name__} "
                f"(stop_reason={getattr(response, 'stop_reason', '?')})"
            )
        return parsed

    # ----------------------------------------------------------------- private
    def _with_retries(self, kwargs: dict, *, max_retries: Optional[int] = None):
        """Retry transient failures only. A 4xx is a bug in our request — surfacing
        it immediately is more useful than retrying it twice and then falling back."""
        s = get_settings()
        A = self._anthropic
        last: Exception | None = None

        retries = s.llm_max_retries if max_retries is None else max(0, max_retries)
        for attempt in range(retries + 1):
            try:
                return self._client.messages.parse(**kwargs)
            except A.RateLimitError as exc:
                last = exc
                delay = self._retry_after(exc, default=2.0 * (2**attempt))
                log.warning("rate limited; retrying in %.1fs", delay)
            except A.APITimeoutError as exc:
                # A full request already consumed its entire latency budget.
                # Repeating it is what turned one 45-second miss into 90+ seconds
                # in the chat path; fall back immediately instead.
                raise LLMError(f"request timed out: {exc}") from exc
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

            if attempt < retries:
                time.sleep(delay)

        raise LLMError(f"giving up after {retries + 1} attempts: {last}")

    @staticmethod
    def _retry_after(exc: Exception, default: float) -> float:
        response = getattr(exc, "response", None)
        header = getattr(response, "headers", {}) or {}
        try:
            return float(header.get("retry-after", default))
        except (TypeError, ValueError):
            return default
