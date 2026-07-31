"""Check the artifact against the request, not against itself.

A document can be internally impeccable and still be the wrong document. These
checks compare what was delivered with what was asked for, and with what the
evidence says must be disclosed whatever was asked for.

The load-bearing one is `must_include`. Retrieval ranks evidence, the planner
selects it and a repair pass may drop a page — three separate places where an
unresolved critical conflict or an unmitigated critical risk could quietly fail
to make the document. This is the check that makes those disappearances loud.
The whole point of the evidence layer's `must_include()` is that it is verified
here at the end, not merely honoured in the middle.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from app.context.schemas import GenerationContext
from app.deliverable.model import Deliverable
from app.quality.schemas import ArtifactReview, Finding, finding

log = logging.getLogger("pmi.quality.completeness")

_STOP = frozenset("""
the a an and or of for to in on at from with by vs versus analysis overview
status update report summary section review dashboard progress key major
required from recommended and
""".split())


def check(deliverable: Deliverable, context: GenerationContext, *,
          brief=None, pass_number: int = 1) -> ArtifactReview:
    review = ArtifactReview(review_id=f"completeness-{pass_number}",
                            pass_number=pass_number)

    review.add(*_check_requested_topics(deliverable, context))
    review.add(*_check_must_include(deliverable, context))
    review.add(*_check_conflicts_disclosed(deliverable, context))
    review.add(*_check_assumptions_labelled(deliverable, context))
    review.add(*_check_pages_have_evidence(deliverable))
    review.add(*_check_constraints(deliverable, context))
    review.add(*_check_quality_disclosed(deliverable, context))
    if brief is not None:
        review.add(*_check_format_and_decisions(deliverable, context, brief))

    if review.findings:
        log.info("completeness pass %d: %s", pass_number, review.summary())
    return review


# ============================================================ what was asked
def _check_requested_topics(deliverable: Deliverable,
                            context: GenerationContext) -> list[Finding]:
    """Every topic the user named must be covered, or stated as uncovered."""
    findings: list[Finding] = []
    if not context.requested_sections:
        return findings

    body = _searchable(deliverable)
    for topic in context.requested_sections:
        pages = deliverable.covered_sections.get(topic) or []
        if pages and _pages_exist(deliverable, pages):
            continue
        if _mentioned(topic, body):
            findings.append(finding(
                "completeness", "note",
                f"The requested topic “{topic}” is not a section of its own, but "
                f"the document does address it.",
                detail=topic))
            continue
        findings.append(finding(
            "completeness", "block",
            f"The user asked for “{topic}” and the document neither covers it "
            f"nor says why it cannot.",
            action="regenerate_page", detail=topic))
    return findings


def _pages_exist(deliverable: Deliverable, section_ids: Sequence[str]) -> bool:
    """A section can be planned and then lose its page to a repair pass."""
    return any(deliverable.pages_of_section(section_id)
               for section_id in section_ids)


def _mentioned(topic: str, body: str) -> bool:
    words = {w for w in re.split(r"[^a-z0-9]+", topic.casefold())
             if len(w) > 3 and w not in _STOP}
    if not words:
        return False
    needed = len(words) if len(words) <= 2 else max(2, int(len(words) * 0.6))
    return len(words & set(body.split())) >= needed


def _searchable(deliverable: Deliverable) -> str:
    parts = [deliverable.title, deliverable.subtitle,
             deliverable.governing_message, deliverable.executive_takeaway]
    for page in deliverable.pages:
        parts.append(page.text_content())
        parts.append(page.source_note)
    for spec in deliverable.specs.tables.values():
        parts.append(spec.caption)
        parts.extend(column.header for column in spec.columns)
        for row in spec.rows:
            parts.extend(cell.text for cell in row)
    for spec in deliverable.specs.charts.values():
        parts.extend([spec.title, spec.caption, spec.insight])
    for spec in deliverable.specs.diagrams.values():
        parts.extend([spec.title, spec.caption])
    parts.extend(deliverable.notes)
    return " ".join(re.split(r"[^a-z0-9]+", " ".join(parts).casefold()))


# ==================================================== what must be disclosed
def _check_must_include(deliverable: Deliverable,
                        context: GenerationContext) -> list[Finding]:
    """The check that stops bad news going missing.

    Three separate layers could drop it — retrieval ranking, planner selection,
    a repair pass removing a page — so it is verified against the artifact.
    """
    required = set(context.evidence.must_include())
    if not required:
        return []

    present = set(deliverable.evidence_ids)
    for spec in deliverable.specs.charts.values():
        present |= set(spec.evidence_ids)
    for spec in deliverable.specs.tables.values():
        present |= set(spec.evidence_ids)
    for spec in deliverable.specs.diagrams.values():
        present |= set(spec.evidence_ids)

    missing = required - present
    if not missing:
        return []

    described = []
    for evidence_id in sorted(missing)[:3]:
        item = context.evidence.get(evidence_id)
        described.append(item.label if item is not None else evidence_id)

    return [finding(
        "completeness", "block",
        f"{len(missing)} finding(s) that must be disclosed appear nowhere in "
        f"this document: {', '.join(described)}. These are unresolved "
        f"disagreements between sources, or critical risks with no mitigation.",
        evidence_ids=sorted(missing), action="regenerate_page")]


def _check_conflicts_disclosed(deliverable: Deliverable,
                               context: GenerationContext) -> list[Finding]:
    """A contested figure must not be presented as settled."""
    conflicts = context.unresolved_critical_conflicts
    if not conflicts:
        return []

    body = _searchable(deliverable)
    if any(word in body for word in ("disagree", "disputed", "unresolved",
                                     "conflict")):
        return []
    return [finding(
        "completeness", "block",
        f"{len(conflicts)} unresolved conflict(s) affect figures this document "
        f"states, and nothing in it tells the reader the figures are disputed.",
        action="regenerate_page")]


def _check_assumptions_labelled(deliverable: Deliverable,
                                context: GenerationContext) -> list[Finding]:
    """An assumption used as though it were a fact."""
    used = set(deliverable.evidence_ids)
    assumptions = [context.evidence.get(i) for i in used
                   if (context.evidence.get(i) is not None
                       and context.evidence.get(i).origin == "user_assumption")]
    if not assumptions:
        return []

    body = _searchable(deliverable)
    if "assumption" in body or "assumed" in body:
        return []
    return [finding(
        "completeness", "fix",
        f"This document rests on {len(assumptions)} stated assumption(s) and "
        f"never labels them as assumptions.",
        evidence_ids=[a.evidence_id for a in assumptions if a],
        action="add_citation")]


def _check_quality_disclosed(deliverable: Deliverable,
                             context: GenerationContext) -> list[Finding]:
    """A document built on weak data must say so somewhere."""
    findings: list[Finding] = []
    transcribed = [i for i in context.evidence.resolve(deliverable.evidence_ids)
                   if i.needs_review]
    body = _searchable(deliverable)

    if transcribed and "image" not in body:
        findings.append(finding(
            "completeness", "fix",
            f"{len(transcribed)} figure(s) in this document were read from an "
            f"image, and nothing tells the reader that.",
            evidence_ids=[i.evidence_id for i in transcribed],
            action="add_citation"))

    report = context.quality_report
    score = getattr(report, "score", None) if report is not None else None
    if score is not None and score < 60 and "limitation" not in body:
        findings.append(finding(
            "completeness", "warn",
            f"The source data scores {score:.0f}/100, and the document does not "
            f"state its own limitations."))
    return findings


# ================================================================== hygiene
def _check_pages_have_evidence(deliverable: Deliverable) -> list[Finding]:
    findings: list[Finding] = []
    exempt = {"cover", "divider", "closing", "agenda"}
    for page in deliverable.pages:
        if page.purpose in exempt:
            continue
        if not page.evidence_ids:
            findings.append(finding(
                "completeness", "warn",
                "This page cites no evidence, so nothing on it can be traced to "
                "a source.",
                page_id=page.page_id, action="regenerate_page"))
    return findings


def _check_constraints(deliverable: Deliverable,
                       context: GenerationContext) -> list[Finding]:
    """Hard limits the user stated. A one-pager that is six pages is not one."""
    findings: list[Finding] = []
    for constraint in context.user_constraints:
        if constraint.kind == "max_pages" and constraint.value.isdigit():
            limit = int(constraint.value)
            # Covers and dividers are furniture, not content the user counted.
            counted = len([p for p in deliverable.pages
                           if p.purpose not in ("cover", "divider", "closing")])
            if counted > limit:
                findings.append(finding(
                    "completeness", "fix",
                    f"The user asked for at most {limit} page(s) and this "
                    f"document has {counted}.",
                    action="split_page", detail=f"{counted} > {limit}"))
        elif constraint.kind == "min_pages" and constraint.value.isdigit():
            if len(deliverable.pages) < int(constraint.value):
                findings.append(finding(
                    "completeness", "warn",
                    f"The user asked for at least {constraint.value} pages and "
                    f"this document has {len(deliverable.pages)}."))
        elif constraint.kind == "no_charts":
            charts = [p.page_id for p in deliverable.pages if p.of_role("chart")]
            if charts:
                findings.append(finding(
                    "completeness", "fix",
                    "The user asked for no charts and this document contains "
                    f"{len(charts)}.",
                    page_id=charts[0], action="drop_element"))
        elif constraint.kind == "exclude_topic":
            if _mentioned(constraint.value, _searchable(deliverable)):
                findings.append(finding(
                    "completeness", "warn",
                    f"The user asked not to cover “{constraint.value}” and the "
                    f"document appears to mention it."))
    return findings


def _check_format_and_decisions(deliverable: Deliverable,
                                context: GenerationContext,
                                brief) -> list[Finding]:
    findings: list[Finding] = []

    if context.requested_output_format and \
            deliverable.primary_format != context.requested_output_format:
        findings.append(finding(
            "completeness", "fix",
            f"The user asked for {context.requested_output_format} and the "
            f"document was planned as {deliverable.primary_format}.",
            action="relayout"))

    body = _searchable(deliverable)
    missing = [decision for decision in getattr(brief, "decisions_sought", [])
               if not _mentioned(decision, body)]
    if missing:
        findings.append(finding(
            "completeness", "fix",
            f"{len(missing)} decision(s) the reader is being asked to take are "
            f"not in the document: {'; '.join(missing[:2])}.",
            action="regenerate_page"))

    if context.audience and deliverable.audience_label:
        if not _mentioned(context.audience, deliverable.audience_label.casefold()):
            findings.append(finding(
                "completeness", "note",
                f"The user named the reader as “{context.audience}” and the "
                f"document addresses “{deliverable.audience_label}”."))
    return findings


def missing_requirements(deliverable: Deliverable,
                         context: GenerationContext) -> list[str]:
    """The blocking completeness findings, as sentences. For an API response."""
    return [f.message for f in check(deliverable, context).blocking]
