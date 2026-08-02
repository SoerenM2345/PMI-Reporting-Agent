"""Validate and complete the storyline's sections.

Two jobs, both Python's:

**Drop what does not exist.** Every `evidence_id` the model returned is checked
against the index. Unknown ids are removed and reported — never accepted on
trust, because an id that resolves to nothing renders as a blank where a figure
should be, and blanks are how a report starts lying quietly. This generalises
the discipline `charts_registry` already used in refusing `getattr` lookups.

**Restore what was requested.** The user's topics are matched to the sections
that cover them; anything unmatched is appended as its own section rather than
lost. The planner's licence is to retitle, reorder and group. It is not to
remove. Where a restored topic has no evidence at all, it still becomes a
section — carrying the `absence` item that says so, so the document states the
gap instead of omitting the subject.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from app.evidence.model import EvidenceIndex
from app.planning.schemas import OutputBrief, SectionIntent, StorylinePlan

log = logging.getLogger("pmi.planning.sections")


def validate(plan: StorylinePlan, evidence: EvidenceIndex) -> list[str]:
    """Strip unresolvable evidence ids and duplicate section ids, in place."""
    warnings: list[str] = []
    seen_ids: set[str] = set()

    for index, section in enumerate(plan.sections, start=1):
        if not section.section_id or section.section_id in seen_ids:
            original = section.section_id
            section.section_id = _unique(
                _slug(section.working_title) or f"section-{index}", seen_ids)
            if original:
                warnings.append(f"Duplicate section id {original!r} was renamed "
                                f"to {section.section_id!r}.")
        seen_ids.add(section.section_id)

        unknown = evidence.unknown(section.evidence_ids)
        if unknown:
            section.evidence_ids = [i for i in section.evidence_ids
                                    if i not in unknown]
            warnings.append(
                f"Section {section.section_id!r} referenced "
                f"{len(unknown)} evidence item(s) that do not exist "
                f"({', '.join(unknown[:3])}); they were dropped.")

        if not section.evidence_ids and section.purpose != "frame":
            warnings.append(
                f"Section {section.section_id!r} cites no evidence, so it can "
                f"only state that nothing was found.")

        section.suggested_pages = max(1, min(section.suggested_pages or 1, 6))

    return warnings


def enforce_coverage(plan: StorylinePlan, brief: OutputBrief,
                     evidence: EvidenceIndex) -> list[str]:
    """Make sure every requested topic is covered by some section.

    Matching is by shared content words rather than by exact title, because
    retitling is the planner's job: "Budget vs. Actual Analysis" is covered by a
    section titled "Forecast spend exceeds the approved envelope", and the
    completeness critic must be able to see that.
    """
    warnings: list[str] = []
    if not brief.scope_topics:
        return warnings

    requested_sections: list[SectionIntent] = []
    claimed: set[str] = set()
    for topic in brief.scope_topics:
        # A named section is an output contract. The planner remains free to
        # decide its message and composition, but it may not merge two requested
        # slides into one or retitle them beyond recognition.
        match = next((section for section in plan.sections
                      if topic in section.covers_requested
                      and section.section_id not in claimed), None)
        match = match or _best_match(
            topic, [section for section in plan.sections
                    if section.section_id not in claimed])
        if match is not None:
            if topic not in match.covers_requested:
                match.covers_requested.append(topic)
            match.working_title = topic
            requested_sections.append(match)
            claimed.add(match.section_id)
            continue

        ids = _absence_or_search(topic, evidence)
        restored = SectionIntent(
            section_id=_unique(_slug(topic), {s.section_id for s in plan.sections}),
            working_title=topic,
            management_question=f"What is the position on {topic.lower()}?",
            purpose="evidence",
            evidence_ids=ids,
            depth="summary",
            covers_requested=[topic],
        )
        plan.sections.append(restored)
        requested_sections.append(restored)
        claimed.add(restored.section_id)
        warnings.append(
            f"The plan did not cover the requested topic {topic!r}; it was added "
            f"as its own section" + (" with no supporting evidence."
                                     if not ids else "."))

    # Preserve the order the user supplied. Additional editorial sections still
    # follow, and the mandatory limitations page is appended by the next stage.
    remaining = [section for section in plan.sections
                 if section.section_id not in claimed]
    plan.sections = requested_sections + remaining
    return warnings


#: What a limitations section can be called without being a second one.
#: Matched against the *title* only. Matching the section's message too was too
#: loose by one word: a status section whose finding reads "status cannot be
#: stated with confidence" is the strongest possible argument that a limitations
#: section is needed, and it was being read as one already existing.
_LIMITS_WORDS = ("limitation", "caveat", "data quality", "data-quality",
                 "what we could not", "gaps in the data")


def enforce_limitations(plan: StorylinePlan,
                        evidence: EvidenceIndex) -> list[str]:
    """Guarantee the document says what it could not establish (§12.5).

    Python's call, not the planner's. A model asked to write a compelling
    SteerCo pack has every incentive to leave out the slide admitting the
    figures disagree, and the keyless fallback has no way to think of it at all
    — so neither is trusted with the decision. Where a section already discusses
    the caveats it is annotated rather than duplicated; the point is that the
    disclosure exists once, not that it exists here.

    The section is appended last because it qualifies the argument above it, and
    it carries the conflicts, the quality issues and the absences as its
    evidence, so its wording comes from what actually went wrong rather than
    from a fixed apology.
    """
    ids = [item.evidence_id for item in evidence
           if item.kind in ("conflict", "quality_issue") or item.is_absence]
    ids += [i for i in evidence.must_include() if i not in ids]

    existing = _limitations_section(plan)
    if existing is not None:
        missing = [i for i in ids if i not in existing.evidence_ids]
        existing.evidence_ids.extend(missing)
        return []

    plan.sections.append(SectionIntent(
        section_id=_unique("data-quality-and-limitations",
                           {s.section_id for s in plan.sections}),
        working_title="Data quality and limitations",
        management_question="How far can these figures be relied on?",
        intended_message=("What follows qualifies everything above it."
                          if ids else
                          "No conflicts or data-quality issues were found in "
                          "the sources behind this report."),
        purpose="appendix",
        evidence_ids=ids,
        depth="summary",
        recommended_expression="table" if len(ids) >= 4 else "none",
        covers_requested=[],
    ))
    return [] if ids else [
        "No data-quality issues were found, so the limitations section states "
        "that rather than being omitted."]


def _limitations_section(plan: StorylinePlan) -> Optional[SectionIntent]:
    for section in plan.sections:
        haystack = f"{section.section_id} {section.working_title}".casefold()
        if any(word in haystack for word in _LIMITS_WORDS):
            return section
    return None


def coverage_map(plan: StorylinePlan,
                 brief: OutputBrief) -> dict[str, list[str]]:
    """`requested topic -> section ids that cover it`, for the critic."""
    out: dict[str, list[str]] = {topic: [] for topic in brief.scope_topics}
    for section in plan.sections:
        for topic in section.covers_requested:
            out.setdefault(topic, []).append(section.section_id)
    return out


# ---------------------------------------------------------------- internals
_STOP = frozenset("""
the a an and or of for to in on at from with by vs versus analysis overview
status update report summary section review dashboard progress key major
required from recommended
""".split())


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").casefold())
            if len(w) > 2 and w not in _STOP}


def _best_match(topic: str, sections: Sequence[SectionIntent]
                ) -> Optional[SectionIntent]:
    wanted = _words(topic)
    if not wanted:
        return None
    best, best_score = None, 0.0
    for section in sections:
        haystack = _words(section.working_title) | _words(section.intended_message) \
            | _words(section.management_question)
        if not haystack:
            continue
        score = len(wanted & haystack) / len(wanted)
        if score > best_score:
            best, best_score = section, score
    # Half the topic's distinctive words is a real match; less is a coincidence,
    # and a false match silently drops a requested section.
    return best if best_score >= 0.5 else None


def _absence_or_search(topic: str, evidence: EvidenceIndex) -> list[str]:
    from app.evidence.retrieval import retrieve

    slug = _slug(topic)
    absence = evidence.get(f"ev:absence:{slug}")
    if absence is not None:
        return [absence.evidence_id]
    hits = retrieve(topic, evidence, k=8)
    return [i.evidence_id for i in hits.included if not i.is_absence][:8]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").casefold()).strip("-")[:48]


def _unique(candidate: str, taken: set[str]) -> str:
    base = candidate or "section"
    if base not in taken:
        return base
    for suffix in range(2, 100):
        attempt = f"{base}-{suffix}"
        if attempt not in taken:
            return attempt
    return f"{base}-{len(taken)}"
