"""Interpreting a revision instruction with no model available.

Follows the same discipline as `app/llm/fallbacks.py`: when the semantic layer
is unavailable the feature degrades to something deterministic and honest rather
than disappearing. It also keeps the whole revision path testable without an API
key, which is what lets the suite stay green and free.

Keyword matching only. It recognises the instructions people actually type —
"remove the dependencies slide", "put risks first", "show 5 rows" — and refuses
everything else by returning no ops, which the caller reports as "I did not
understand that" rather than guessing.
"""
from __future__ import annotations

import re
from typing import Optional

from app.report.content import ReportContent, Section
from app.report.ops import ContentRevision, ReviseOp

_STOPWORDS = {
    "the", "a", "an", "slide", "section", "page", "and", "of", "for", "on",
    "please", "to", "from", "my", "our", "this", "that",
}


def interpret(instruction: str, content: ReportContent) -> ContentRevision:
    """Best-effort ops for `instruction`. Empty when nothing matched."""
    text = (instruction or "").strip().lower()
    if not text:
        return ContentRevision(ops=[], rationale="no instruction given")

    for rule in (_drop, _restore, _move_first, _row_limit):
        revision = rule(text, content)
        if revision is not None:
            return revision

    return ContentRevision(
        ops=[],
        rationale=("Could not interpret that without a language model. Try "
                   "“remove the dependencies section”, “put risks first”, or "
                   "“show 5 rows in milestones”."),
    )


# ------------------------------------------------------------------- rules
def _drop(text: str, content: ReportContent) -> Optional[ContentRevision]:
    if not re.search(r"\b(remove|drop|delete|take out|hide)\b", text):
        return None
    section = _match_section(text, content, in_narrative=True)
    if section is None:
        return None
    return ContentRevision(
        ops=[ReviseOp(op="drop_section", section_id=section.section_id)],
        rationale=f"remove “{section.label}”",
    )


def _restore(text: str, content: ReportContent) -> Optional[ContentRevision]:
    if not re.search(r"\b(restore|bring back|put back|add back|show again)\b", text):
        return None
    section = _match_section(text, content, in_narrative=False)
    if section is None:
        return None
    return ContentRevision(
        ops=[ReviseOp(op="restore_section", section_id=section.section_id)],
        rationale=f"restore “{section.label}”",
    )


def _move_first(text: str, content: ReportContent) -> Optional[ContentRevision]:
    if not re.search(r"\b(first|to the top|up front|lead with|start with)\b", text):
        return None
    section = _match_section(text, content, in_narrative=True)
    if section is None:
        return None

    # The executive summary stays at position 1 — a report that opens with a
    # risk table and explains itself afterwards is not a report.
    order = [s.section_id for s in content.narrative()]
    order.remove(section.section_id)
    head = ["summary.executive"] if "summary.executive" in order else []
    for sid in head:
        order.remove(sid)
    return ContentRevision(
        ops=[ReviseOp(op="reorder", order=head + [section.section_id] + order)],
        rationale=f"move “{section.label}” to the front",
    )


def _row_limit(text: str, content: ReportContent) -> Optional[ContentRevision]:
    match = re.search(r"\bshow (?:me )?(?:only )?(\d+)\b", text)
    if not match:
        return None
    section = _match_section(text, content, in_narrative=True)
    if section is None:
        return None
    return ContentRevision(
        ops=[ReviseOp(op="set_row_limit", section_id=section.section_id,
                      row_limit=int(match.group(1)))],
        rationale=f"limit “{section.label}” to {match.group(1)} rows",
    )


# ----------------------------------------------------------------- matching
def _match_section(
    text: str, content: ReportContent, *, in_narrative: bool
) -> Optional[Section]:
    """The section whose label best overlaps the instruction.

    Requires a real word in common, so "remove that" matches nothing rather
    than picking whichever section happens to sort first.
    """
    words = _words(text)
    best, best_score = None, 0

    for section in content.sections:
        is_shown = section.narrative_order is not None
        if is_shown != in_narrative:
            continue
        label_words = _words(section.label) | _words(section.section_id.replace(".", " "))
        score = len(words & label_words)
        if score > best_score:
            best, best_score = section, score

    return best if best_score else None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower())
            if w not in _STOPWORDS and len(w) > 2}
