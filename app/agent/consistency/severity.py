"""Severity assignment (spec §9).

This module is what makes Mode C work, and it is more load-bearing than it looks.

§9 lists the conflicts that are *critical* — the ones that change the management
message and must reach a human: overall integration status, Day 1 readiness, major
go-live dates, budget totals, synergy realization, critical risks, Steering Committee
decisions, TSA exit dates, regulatory milestones.

Note what that list is: it is about the **topic**, not the size of the disagreement.
The spec's own worked example (§20) is 82% vs 75% — a 9% relative delta. A severity
rule based on magnitude alone would rank that "medium", auto-resolve it by source
priority, and the user would never be asked. §20 step 9 says the system *must* ask.
So topic outranks magnitude, and the topic rules below are the reason the acceptance
scenario passes.

Magnitude still matters as a second axis: a 60% disagreement about a minor budget line
is material even though the line is not on §9's list.
"""
from __future__ import annotations

import re
from typing import Optional

from app.models.pmi import ConflictEvidence, Severity

#: §9's "Critical PMI conflicts", as patterns matched against the entity key.
CRITICAL_TOPICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("overall integration status / progress",
     re.compile(r"\boverall\b|\bgesamt|integration (status|progress)", re.I)),
    ("Day 1 readiness",
     re.compile(r"day[\s\-]?1\b|day one|\bd1\b", re.I)),
    ("major go-live / cutover date",
     re.compile(r"go[\s\-]?live|cutover|migration date|launch", re.I)),
    ("budget total",
     re.compile(r"total budget|budget total|gesamtbudget|total cost", re.I)),
    ("synergy realization",
     re.compile(r"synerg", re.I)),
    ("TSA exit",
     re.compile(r"\btsa\b", re.I)),
    ("regulatory / compliance milestone",
     re.compile(r"regulator|compliance|antitrust|merger control|gdpr", re.I)),
    ("Steering Committee decision",
     re.compile(r"steerco|steering committee", re.I)),
)

#: A numeric disagreement this large is material whatever the topic.
ESCALATE_PCT = 20.0
CRITICAL_PCT = 50.0

_ORDER = (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)


def critical_topic(entity_key: str) -> Optional[str]:
    """The §9 topic this key falls under, if any. Returned rather than a bool so the
    conflict card can tell the user *why* it is being asked."""
    for label, pattern in CRITICAL_TOPICS:
        if pattern.search(entity_key or ""):
            return label
    return None


def escalate(
    entity_key: str,
    evidence: list[ConflictEvidence],
    base: Severity,
    *,
    is_critical_entity: bool = False,
) -> Severity:
    """Raise `base` by topic (§9) and by magnitude."""
    if critical_topic(entity_key) is not None:
        return Severity.CRITICAL

    # A disagreement about a risk that is itself critical is a critical disagreement.
    if is_critical_entity:
        return Severity.CRITICAL

    delta = relative_delta(evidence)
    if delta is not None:
        if delta >= CRITICAL_PCT:
            return Severity.CRITICAL
        if delta >= ESCALATE_PCT:
            return bump(base)

    return base


def relative_delta(evidence: list[ConflictEvidence]) -> Optional[float]:
    """Spread between the numeric claims, as a percentage of the smallest."""
    numbers = []
    for item in evidence:
        try:
            numbers.append(float(item.value))
        except (TypeError, ValueError):
            continue

    if len(numbers) < 2:
        return None

    low, high = min(numbers), max(numbers)
    if low == 0:
        return 100.0 if high != 0 else 0.0
    return abs(high - low) / abs(low) * 100.0


def bump(severity: Severity) -> Severity:
    return _ORDER[min(_ORDER.index(severity) + 1, len(_ORDER) - 1)]
