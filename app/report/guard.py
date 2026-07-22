"""Numeric containment: the check that makes model-authored prose safe.

§11 says the model is never the authority for a calculation. The revision op
schema already makes an invented figure *unrepresentable* in structured fields —
there is no op that writes a cell, a tile or a fact. This is the second layer,
for the one place a model does emit free text: a headline or a bullet.

The rule is containment, not plausibility. Every number appearing in authored
text must already appear somewhere in the report's own fact table. "Three
critical risks are open" is fine when the fact table says 3; the same sentence
with a 4 in it is rejected, regardless of how reasonable it reads.

This will occasionally reject a valid rephrase — "the top 5 risks" when 5 is not
a figure the report states. That asymmetry is deliberate and is the correct
direction to be wrong in: a rejected rephrase costs the user a click, an
accepted invented figure goes to a Steering Committee.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.report.content import ReportContent, _normalise_number

#: Matches integers, decimals, thousands-separated numbers and percentages.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")

#: Ordinals and small words that read as numbers but never state a figure —
#: "the first slide", "a second look". Excluded so ordinary prose is not
#: rejected for containing "1st".
_ORDINAL = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)


class Rejection(Exception):
    """Raised only where a caller wants failure to be loud. Most callers use
    `check_text`, which returns the offending figures instead."""


def numbers_in(text: str) -> set[str]:
    """Normalised numeric literals in `text`, ignoring ordinals."""
    without_ordinals = _ORDINAL.sub(" ", text or "")
    return {_normalise_number(m) for m in _NUMBER.findall(without_ordinals)}


def check_text(text: str, corpus: Iterable[str]) -> list[str]:
    """Figures in `text` that the report is not entitled to state.

    Empty list means the text is safe to accept.
    """
    allowed = set(corpus)
    return sorted(numbers_in(text) - allowed)


def check_against(text: str, content: ReportContent) -> list[str]:
    """`check_text` against a report's own fact table."""
    return check_text(text, content.numeric_corpus_cached())


def describe(offending: list[str], text: str) -> str:
    """A rejection message a user can act on, not a stack trace."""
    figures = ", ".join(offending)
    return (
        f"Rejected: {figures} {'is' if len(offending) == 1 else 'are'} not a "
        f"figure this report states. Text was: “{text[:120]}”. If the number is "
        f"correct, it belongs in the source data, not in the wording."
    )
