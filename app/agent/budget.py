"""The chat's context budget, and what happens when it runs out.

A conversation that grows without limit eventually fails mid-request, and the
failure lands on the user at the least convenient moment — usually several turns
into a revision loop. So the transcript is kept inside the chosen model's window
by summarising the oldest turns once it approaches the ceiling.

**This is only safe because the transcript is not the source of truth.** The
extracted data lives in `analysis.json` and the report itself in
`content/vN.json`; the chat is a record of the discussion around them. Compaction
therefore loses conversational nuance — "make it shorter", "no, the other one" —
and never a figure, a conflict decision, or a version of the report. If the chat
ever became the place a decision was *stored*, this would have to change.

The window comes from `MODEL_CATALOGUE`, so switching a chat from Haiku (200K) to
Opus (1M) genuinely changes how much history it can hold, rather than every chat
sharing one guessed number.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.config import get_settings, model_choice
from app.storage import chat_store
from app.storage.chat_store import Chat, Message

log = logging.getLogger("pmi.budget")

#: Compact at 70% rather than at the limit. The turn that trips the threshold
#: still has to fit, along with the system prompt, the report's table of
#: contents and the model's reply — leaving that headroom is the difference
#: between compacting early and failing the request that would have overflowed.
COMPACT_AT = 0.70

#: Recent turns always survive verbatim. Summarising what was said thirty
#: seconds ago would make the agent look like it had stopped listening.
KEEP_RECENT = 8

#: Below this there is nothing worth summarising.
MIN_TO_COMPACT = 4

#: Used when the model is unknown — an unlisted id should not mean "unlimited".
FALLBACK_WINDOW = 128_000


def window_for(chat: Chat) -> int:
    choice = model_choice(chat.model or get_settings().llm_model)
    return choice.context_window if choice else FALLBACK_WINDOW


def usage(chat: Chat) -> dict:
    """What the UI shows, and what `should_compact` decides on."""
    window = window_for(chat)
    used = chat_store.live_token_estimate(chat.chat_id)
    return {
        "used": used,
        "window": window,
        "fraction": round(used / window, 4) if window else 0.0,
        "compact_at": COMPACT_AT,
        "near_limit": used >= window * COMPACT_AT,
    }


def should_compact(chat: Chat) -> bool:
    return usage(chat)["near_limit"]


def compact(chat: Chat) -> Optional[Message]:
    """Summarise the older turns. Returns the summary message, or `None`.

    The compacted turns are marked rather than deleted: the user can still
    scroll back and read exactly what was said. Only what is *sent to a model*
    shrinks — which is the actual constraint.
    """
    live = [m for m in chat_store.list_messages(chat.chat_id)
            if not m.superseded]
    if len(live) <= KEEP_RECENT + MIN_TO_COMPACT:
        return None

    older = live[:-KEEP_RECENT]
    summary_text = _summarise(older)

    note = chat_store.add_message(
        chat.chat_id, "system",
        {
            "text": summary_text,
            "compacted": len(older),
            "reason": "context budget",
        },
        kind="notice",
    )
    chat_store.supersede([m.message_id for m in older])
    chat_store.recount_tokens(chat.chat_id)

    log.info("compacted %d turn(s) in chat %s", len(older), chat.chat_id)
    return note


def _summarise(messages: list[Message]) -> str:
    """A deterministic account of what was compacted.

    Deliberately *not* an LLM call. Summarising the history is the one moment
    where a model could quietly rewrite what the user asked for — "generate the
    Finance deck" becoming "generate the deck" — and unlike report prose there
    is no fact table to check it against. Counting what happened is duller and
    cannot be wrong.
    """
    said = [m.content.get("text", "") for m in messages
            if m.role == "user" and m.content.get("text")]
    kinds = {m.kind for m in messages if m.role == "agent"}

    parts = [f"Earlier in this chat ({len(messages)} turns, summarised to stay "
             f"inside the context limit):"]
    if said:
        shown = said[:5]
        parts.append("you asked for — " + "; ".join(f"“{s[:70]}”" for s in shown))
        if len(said) > len(shown):
            parts.append(f"…and {len(said) - len(shown)} more request(s)")
    if "preview" in kinds:
        parts.append("drafts were reviewed")
    if "conflict" in kinds:
        parts.append("source conflicts were raised")
    if "downloads" in kinds:
        parts.append("files were generated")

    parts.append(
        "The extracted data and every version of the report are unaffected — "
        "only the conversation above was condensed."
    )
    return " ".join(parts)
