"""Short, automatic names for otherwise untitled conversations."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.llm import fast_model, get_client
from app.llm.base import LLMError


DEFAULT_TITLES = frozenset({"new chat", "chat name", "untitled chat"})


class ChatTitle(BaseModel):
    title: str = Field(min_length=1, max_length=80)


def is_default(title: str) -> bool:
    return (title or "").strip().casefold() in DEFAULT_TITLES


def summarize(user_text: str, assistant_text: str = "") -> str:
    """Return a compact topic label, with an honest keyless fallback.

    The model sees the completed first exchange, as ChatGPT-style naming does.
    If no provider is configured (or title generation fails), the user's own
    words still produce a useful, deterministic name.
    """
    fallback = _fallback(user_text)
    try:
        result = get_client().structured(
            system=(
                "Name this PMI reporting conversation. Return a concise noun "
                "phrase of 3-8 words that captures its subject and requested "
                "outcome. Do not use quotation marks, terminal punctuation, "
                "or generic labels such as 'Chat' or 'Conversation'."
            ),
            user=f"User:\n{user_text}\n\nAssistant:\n{assistant_text[:2000]}",
            output_model=ChatTitle,
            model=fast_model(),
            max_tokens=40,
        ).title
    except (LLMError, ValueError):
        return fallback
    return _clean(result) or fallback


def _fallback(text: str) -> str:
    words = re.findall(r"[\w][\w'&/-]*", text, flags=re.UNICODE)
    if not words:
        return "PMI reporting request"
    selected = words[:8]
    title = " ".join(selected)
    if len(words) > len(selected):
        title += "…"
    return _clean(title) or "PMI reporting request"


def _clean(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    value = value.strip(" \t\r\n\"'`.,:;!?-–—")
    return value[:80].rstrip()
