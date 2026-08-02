"""OpenAI backend.

Kept genuinely working (not a stub) because spec §15 requires that the model and
provider can be changed. Select it with `LLM_PROVIDER=openai` plus `OPENAI_API_KEY`
and an `LLM_MODEL` that exists on that platform.
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Sequence

from pydantic import ValidationError

from app.config import get_settings
from app.llm.base import DocumentPart, ImagePart, LLMError, NotConfigured, T

log = logging.getLogger("pmi.llm.openai")


class OpenAIClient:
    name = "openai"
    supports_vision = True

    def __init__(self, api_key: str) -> None:
        try:
            import openai
        except ImportError as exc:  # pragma: no cover
            raise NotConfigured("the `openai` package is not installed") from exc

        self._openai = openai
        s = get_settings()
        self._client = openai.OpenAI(
            api_key=api_key, timeout=s.llm_timeout_s, max_retries=0
        )

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
        if documents:
            # Native PDF input differs materially across providers; rather than
            # silently dropping the document (and returning a confident answer
            # about a file the model never saw), refuse. The PDF extractor's
            # text/table path still works — only the scanned-page vision fallback
            # is Anthropic-only. Documented in docs/known_limitations.md.
            raise LLMError(
                "the OpenAI backend does not accept PDF document parts; "
                "use LLM_PROVIDER=anthropic for scanned-PDF interpretation"
            )

        s = get_settings()
        content: list[dict] = [{"type": "text", "text": user}]
        for img in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{img.media_type};base64,{img.b64}"},
                }
            )

        kwargs = {
            "model": model or s.llm_model,
            # `max_tokens` is rejected outright by the GPT-5 / o-series reasoning
            # models and is deprecated on the rest; `max_completion_tokens` is
            # accepted by every chat-completions model this app can be pointed at.
            # It also budgets reasoning tokens, which the older name did not.
            "max_completion_tokens": max_tokens or s.llm_max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "response_format": output_model,
        }
        if timeout_s is not None:
            kwargs["timeout"] = timeout_s

        response = self._with_retries(kwargs, max_retries=max_retries)
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise LLMError(f"model returned no parseable {output_model.__name__}")
        return parsed

    def _with_retries(self, kwargs: dict, *, max_retries: Optional[int] = None):
        s = get_settings()
        O = self._openai
        last: Exception | None = None

        retries = s.llm_max_retries if max_retries is None else max(0, max_retries)
        for attempt in range(retries + 1):
            try:
                return self._client.chat.completions.parse(**kwargs)
            except O.APITimeoutError as exc:
                raise LLMError(f"request timed out: {exc}") from exc
            except (O.RateLimitError, O.APIConnectionError, O.InternalServerError) as exc:
                last = exc
                delay = 1.0 * (2**attempt)
                log.warning("transient API failure (%s); retrying in %.1fs",
                            type(exc).__name__, delay)
            except ValidationError as exc:
                raise LLMError(f"schema validation failed: {exc}") from exc
            except O.APIStatusError as exc:
                raise LLMError(f"{type(exc).__name__}: {exc}") from exc

            if attempt < retries:
                time.sleep(delay)

        raise LLMError(f"giving up after {retries + 1} attempts: {last}")
