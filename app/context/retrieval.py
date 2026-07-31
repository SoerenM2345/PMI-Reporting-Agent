"""Pick the chat turns a generation actually needs.

A long chat is mostly uploads, acknowledgements and corrections that the
knowledge store has already absorbed. Feeding all of it to a planner costs
tokens and, worse, buries the request under small talk.

No model call: this reuses the evidence layer's BM25 scorer, so chat selection
and evidence selection rank on the same terms and cannot disagree about what
"the budget question" means.

The transcript is deliberately *not* treated as a source of truth — `analysis.json`
and the knowledge store are. Anything selected here is context for phrasing and
intent, never a figure to quote.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from app.context.schemas import ChatExcerpt
from app.evidence.scoring import build_index, expand, tokenize

log = logging.getLogger("pmi.context.retrieval")

#: Message kinds that carry the user's intent. The rest — file lists, download
#: cards, conflict widgets — are UI state the planner cannot use.
_MEANINGFUL_KINDS = frozenset({"text", "preview", "notice"})

#: Phrasings that make a turn a *request* rather than a remark. Used to build
#: `request_history`, which is what stops the first turn's wording being sticky.
_REQUEST_HINTS = re.compile(
    r"\b(report|deck|presentation|slides?|pack|summary|update|memo|dashboard|"
    r"one[- ]pager|write|draft|prepare|produce|generate|create|build|make|"
    r"put together|give me|i need|i want|can you|please)\b", re.I)


def relevant_messages(messages: Sequence, query: str, *, k: int = 12,
                      budget_chars: int = 6000) -> list[ChatExcerpt]:
    """The turns most related to `query`, newest-first on ties, within budget."""
    candidates = [m for m in messages if _is_usable(m)]
    if not candidates:
        return []

    texts = {}
    for index, message in enumerate(candidates):
        texts[str(index)] = _text_of(message)

    scorer = build_index(texts.items())
    tokens = expand(tokenize(query))

    scored = []
    for index, message in enumerate(candidates):
        text = texts[str(index)]
        if not text:
            continue
        score = scorer.bm25(str(index), tokens)
        # Recency as a tiebreaker, not as a ranking signal: the last thing said
        # is usually the current ask, but an older turn that answered the
        # question still outranks a newer "thanks".
        score += 0.01 * index
        scored.append((score, index, message, text))

    scored.sort(key=lambda row: (-row[0], -row[1]))

    picked: list[ChatExcerpt] = []
    used = 0
    for score, _index, message, text in scored[:k]:
        clipped = text[:1200]
        if used + len(clipped) > budget_chars and picked:
            break
        used += len(clipped)
        picked.append(ChatExcerpt(
            message_id=getattr(message, "message_id", ""),
            role="assistant" if getattr(message, "role", "user") == "assistant"
            else "user",
            text=clipped,
            at=getattr(message, "created_at", ""),
            relevance=round(score, 4),
        ))

    picked.sort(key=lambda excerpt: excerpt.at)     # chronological for reading
    return picked


def request_history(messages: Sequence) -> list[str]:
    """Every user turn that asked for something, oldest first.

    The old router made the first turn's phrasing permanent: `request_text` was
    only ever set when it was empty, so a user who refined the ask three times
    got a document built from their first sentence.
    """
    out: list[str] = []
    for message in messages:
        if getattr(message, "role", "") != "user" or not _is_usable(message):
            continue
        text = _text_of(message).strip()
        if text and _REQUEST_HINTS.search(text):
            out.append(text)
    return out


def summarize_chat(messages: Sequence, *, budget_chars: int = 1500) -> str:
    """A plain recap of the conversation so far. Deterministic, no model call."""
    usable = [m for m in messages if _is_usable(m)]
    if not usable:
        return ""

    users = sum(1 for m in usable if getattr(m, "role", "") == "user")
    lines = [f"{len(usable)} messages exchanged ({users} from the user)."]

    asks = request_history(usable)
    if asks:
        lines.append("The user has asked for: "
                     + "; ".join(a[:160] for a in asks[-3:]) + ".")

    recent = [m for m in usable if getattr(m, "role", "") == "user"][-3:]
    for message in recent:
        text = _text_of(message).strip()
        if text:
            lines.append(f"- {text[:200]}")

    summary = "\n".join(lines)
    return summary[:budget_chars]


# --------------------------------------------------------------- internals
def _is_usable(message) -> bool:
    if getattr(message, "superseded", False):
        return False
    return getattr(message, "kind", "text") in _MEANINGFUL_KINDS


def _text_of(message) -> str:
    """The readable text of a message, whatever shape its content takes."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("text", "message", "markdown", "body"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def latest_request(messages: Sequence, fallback: str = "") -> Optional[str]:
    history = request_history(messages)
    return history[-1] if history else (fallback or None)
