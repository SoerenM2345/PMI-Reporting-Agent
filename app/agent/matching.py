"""Entity matching across sources (spec §10 node 18, §11).

The same milestone is "ERP go-live" in the masterplan, "ERP Go Live" in the SteerCo
deck, and "ERP cutover" on a whiteboard. Unless those are recognised as one thing,
no cross-source conflict can ever be detected — the deck and the tracker simply hold
two unrelated milestones, and the disagreement about their dates goes unnoticed.

Matching is deterministic: normalized text + token overlap. The LLM is *allowed* to
match semantically (§11 lists "Matching semantically identical tasks or milestones"),
but it is not required, and it is never the sole basis for merging two entities —
a bad merge silently destroys one source's value, and that is exactly the kind of
irreversible, invisible error the spec's provenance rules exist to prevent.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from app.models.pmi import PMIDataModel

#: Words that carry no distinguishing signal in a PMI title.
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "for", "to", "and", "in", "on", "at", "by", "with",
    "der", "die", "das", "und", "für", "von", "zu",
    "project", "task", "milestone", "risk", "issue", "action", "item",
})

#: Below this Jaccard overlap, two titles are different things.
#:
#: Tuned deliberately high, because the two failure modes are not symmetric. A *missed*
#: match means a conflict goes undetected — bad, but the data is still there and both
#: values still appear with their sources. A *false* match merges two different things
#: and silently destroys one of them, and produces a fictitious "conflict" between
#: facts that were never about the same subject.
#:
#: At 0.6, "Migrate payroll to new provider" and "Migrate CRM to new provider" merge
#: (they share migrate/new/provider — 3 of 5 tokens). They are obviously different
#: tasks. 0.75 separates them while still matching "ERP go-live" to "ERP go-live
#: cutover" (3 of 4).
_MATCH_THRESHOLD = 0.75


@dataclass
class EntityGroup:
    """One real-world thing, as reported by one or more sources."""

    key: str
    label: str
    entity_type: str
    members: list[Any] = field(default_factory=list)

    @property
    def files(self) -> set[str]:
        return {f for m in self.members for f in m.source_files}

    @property
    def is_cross_source(self) -> bool:
        return len(self.files) >= 2

    def values_of(self, attribute: str) -> list[tuple[Any, Any]]:
        """(entity, value) for every member that states `attribute`."""
        out = []
        for member in self.members:
            value = getattr(member, attribute, None)
            if value is None:
                continue
            if hasattr(value, "value") and value.value == "unknown":
                continue
            out.append((member, value))
        return out


@dataclass
class EntityGroups:
    """Matched groups, by entity type. Built once and shared by every check, so the
    checks agree with each other about what counts as 'the same task'."""

    tasks: list[EntityGroup] = field(default_factory=list)
    milestones: list[EntityGroup] = field(default_factory=list)
    risks: list[EntityGroup] = field(default_factory=list)
    issues: list[EntityGroup] = field(default_factory=list)
    budget: list[EntityGroup] = field(default_factory=list)
    synergies: list[EntityGroup] = field(default_factory=list)
    kpis: list[EntityGroup] = field(default_factory=list)
    dependencies: list[EntityGroup] = field(default_factory=list)
    decisions: list[EntityGroup] = field(default_factory=list)
    workstreams: list[EntityGroup] = field(default_factory=list)

    def cross_source(self, attribute: str) -> Iterable[EntityGroup]:
        for group in getattr(self, attribute):
            if group.is_cross_source:
                yield group


def match_entities(model: PMIDataModel) -> EntityGroups:
    return EntityGroups(
        tasks=_group(model.tasks, "task", lambda t: t.title),
        milestones=_group(model.milestones, "milestone", lambda m: m.name),
        risks=_group(model.risks, "risk", lambda r: r.title),
        issues=_group(model.issues, "issue", lambda i: i.title),
        budget=_group(model.budget, "budget", lambda b: b.category),
        synergies=_group(model.synergies, "synergy", lambda s: s.title),
        kpis=_group(model.kpis, "kpi", lambda k: k.name),
        dependencies=_group(model.dependencies, "dependency", lambda d: d.description),
        decisions=_group(model.decisions, "decision", lambda d: d.title),
        workstreams=_group(model.workstreams, "workstream", lambda w: w.name),
    )


# ------------------------------------------------------------------- internals
def _group(
    entities: list, entity_type: str, label_of: Callable[[Any], str]
) -> list[EntityGroup]:
    """Exact-normalized matches first, then fuzzy merge the leftovers.

    Two passes because exact matching is safe and cheap, and doing it first means the
    fuzzy pass only ever sees genuinely different strings.
    """
    exact: dict[str, EntityGroup] = {}
    for entity in entities:
        label = label_of(entity) or ""
        key = _normalize(label)
        if not key:
            continue
        group = exact.get(key)
        if group is None:
            group = EntityGroup(key=key, label=label, entity_type=entity_type)
            exact[key] = group
        group.members.append(entity)

    groups = list(exact.values())
    merged: list[EntityGroup] = []

    for group in groups:
        target = _best_match(group, merged)
        if target is not None:
            target.members.extend(group.members)
        else:
            merged.append(group)

    return merged


def _best_match(group: EntityGroup, candidates: list[EntityGroup]) -> Optional[EntityGroup]:
    tokens = _tokens(group.key)
    if not tokens:
        return None

    best, best_score = None, 0.0
    for candidate in candidates:
        score = _similarity(tokens, _tokens(candidate.key))
        if score > best_score:
            best, best_score = candidate, score

    return best if best_score >= _MATCH_THRESHOLD else None


def _normalize(text: str) -> str:
    text = str(text).casefold().strip()
    text = re.sub(r"[^\w\s-]", " ", text)      # punctuation carries no meaning here
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokens(key: str) -> frozenset[str]:
    return frozenset(
        t for t in key.replace("-", " ").split()
        if t and t not in _STOPWORDS and len(t) > 1
    )


def _similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Jaccard overlap. 'ERP go live' vs 'ERP go-live cutover' -> 2/3 = 0.67."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def merge_group_sources(group: EntityGroup) -> list:
    """All source references across a group's members, de-duplicated."""
    seen: dict[tuple, Any] = {}
    for member in group.members:
        for ref in member.source_references:
            seen.setdefault((ref.file_name, ref.location), ref)
    return list(seen.values())
