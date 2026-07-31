"""Check that everything the artifact states is actually supported.

`app/report/guard.py` already does the hardest part — numeric containment — and
is reused verbatim rather than reimplemented. This adds the three checks that
containment alone does not catch:

* **Entity containment.** "Owned by Sarah Chen" passes a numeric check
  effortlessly and is a fabrication if no Sarah Chen appears in any source. A
  hallucinated owner is more damaging than a hallucinated number, because
  somebody will go looking for her.
* **Date containment.** A date is a claim about the world and is trivially
  invented; the guard's tokeniser sees `2026` and a couple of negative numbers.
* **Claim binding.** An element the model authored, stating a figure, citing no
  evidence at all. Structurally that should be impossible — but if it happens the
  failure is silent, so it is checked.

The asymmetry that matters: **user-authored text is flagged, never rejected.** The
user is allowed to know something the files do not. A model is not.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, Optional, Sequence

from app.context.schemas import GenerationContext
from app.deliverable.model import Deliverable, PageDesign
from app.evidence.model import EvidenceIndex, EvidenceItem
from app.quality.schemas import ArtifactReview, Finding, finding

log = logging.getLogger("pmi.quality.grounding")

#: A capitalised run of two or more words: how a person or a system gets named.
_PROPER_NOUN = re.compile(r"\b([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,}){1,3})\b")

#: Words that start a sentence or head a list and are not names.
_NOT_NAMES = frozenset("""
The A An This That These Those Not Reported No None All Some Each Every Both
Day One Two Three Four Five Steering Committee Board Executive Management
Integration Management Office Sources Source Figure Page Contents Limitations
Overall Status Update Report Summary Risk Risks Issue Issues Budget Actual
Forecast Variance Synergy Synergies Milestone Milestones Task Tasks Decision
Decisions Next Steps Confirm Assign Approve Prepared Showing Includes Assembled
Delivery Forecast Sources Methodology What When Where Which Who Why How
""".split())

_DATE = re.compile(
    r"\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{4})\b", re.I)


def check(deliverable: Deliverable, context: GenerationContext, *,
          pass_number: int = 1) -> ArtifactReview:
    """Every grounding check, over the whole deliverable."""
    review = ArtifactReview(review_id=f"grounding-{pass_number}",
                            pass_number=pass_number)
    corpus = numeric_corpus(deliverable, context)
    names = entity_vocabulary(context.evidence, context)
    dates = date_vocabulary(context.evidence)

    for page in deliverable.pages:
        for element in page.elements:
            for text, where in _texts(element):
                review.add(*_check_text(text, where, element, page, corpus,
                                        names, dates))
        review.add(*_check_titles(page, corpus, dates))
        review.add(*_check_binding(page))

    review.add(*_check_specs(deliverable, context))
    if review.findings:
        log.info("grounding pass %d: %s", pass_number, review.summary())
    return review


# ================================================================== corpora
def numeric_corpus(deliverable: Deliverable,
                   context: GenerationContext) -> set[str]:
    """Every number the artifact may state.

    The evidence's own corpus, plus the figures Python itself placed — a table
    cell or a resolved KPI tile is grounded by construction, and its formatted
    form ("EUR 1,220,000") may differ from the raw value.
    """
    from app.report import guard

    corpus = context.evidence.numeric_corpus()
    for page in deliverable.pages:
        for element in page.elements:
            for tile in getattr(element, "tiles", []) or []:
                corpus |= guard.numbers_in(tile.display)
    for spec in deliverable.specs.tables.values():
        for row in spec.rows:
            for cell in row:
                corpus |= guard.numbers_in(cell.text)
    for spec in deliverable.specs.charts.values():
        for point in spec.all_points():
            corpus |= guard.numbers_in(point.display)
    return corpus


def entity_vocabulary(evidence: EvidenceIndex,
                      context: Optional[GenerationContext] = None) -> set[str]:
    """Every proper noun the sources or the user actually mentioned."""
    words: set[str] = set()
    for item in evidence.items.values():
        for text in (item.label, item.statement, item.owner or "",
                     item.workstream or ""):
            words |= _names(text)
        for value in item.payload.values():
            if isinstance(value, str):
                words |= _names(value)
        for reference in item.sources:
            words.add(reference.file_name.casefold())

    if context is not None:
        for text in (context.project_context, context.project_name,
                     *context.company_names.known,
                     *context.project_knowledge.confirmed_facts,
                     *context.project_knowledge.assumptions,
                     *context.requested_sections,
                     context.user_request, context.audience or ""):
            words |= _names(text)
    return words


def date_vocabulary(evidence: EvidenceIndex) -> set[str]:
    dates: set[str] = set()
    for item in evidence.items.values():
        for text in (item.display, item.statement):
            dates |= {_normalize_date(m) for m in _DATE.findall(text)}
        if item.due:
            dates.add(_normalize_date(item.due.isoformat()))
        for value in item.payload.values():
            if isinstance(value, str) and len(value) >= 8:
                dates |= {_normalize_date(m) for m in _DATE.findall(value)}
    return {d for d in dates if d}


def _names(text: str) -> set[str]:
    found: set[str] = set()
    for match in _PROPER_NOUN.finditer(text or ""):
        phrase = match.group(1)
        for word in phrase.split():
            if word not in _NOT_NAMES:
                found.add(word.casefold())
        found.add(phrase.casefold())
    return found


def _normalize_date(text: str) -> str:
    """Compare dates by their digits, not their formatting.

    `15-09-2026`, `2026-09-15` and `15 September 2026` are one date, and the
    renderers legitimately use different formats in different places.
    """
    digits = re.findall(r"\d+", str(text))
    if not digits:
        return ""
    months = {m: f"{i:02d}" for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"], start=1)}
    for name, number in months.items():
        if name in str(text).casefold():
            digits.append(number)
    return "-".join(sorted(d.zfill(2) for d in digits if d))


# ================================================================== checks
def _texts(element) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    text = getattr(element, "text", "")
    if text:
        out.append((text, element.role))
    for item in getattr(element, "items", []) or []:
        out.append((item, "bullet"))
    caption = getattr(element, "caption", "")
    if caption:
        out.append((caption, "caption"))
    return out


def _check_text(text: str, where: str, element, page: PageDesign,
                corpus: set[str], names: set[str],
                dates: set[str]) -> list[Finding]:
    from app.report import guard

    findings: list[Finding] = []
    authored_by_model = element.authored_by == "llm"
    # The user is allowed to know something the files do not; a model is not.
    severity = "block" if authored_by_model else "warn"
    action = "regenerate_page" if authored_by_model else "none"

    offending = guard.check_text(text, corpus)
    if offending:
        findings.append(finding(
            "grounding", severity,
            f"The {where} on this page states "
            f"{', '.join(offending[:3])}, which is not in the evidence."
            + ("" if authored_by_model else
               " This text was written by the user, so it is reported rather "
               "than removed."),
            page_id=page.page_id, element_id=element.element_id,
            action=action, detail=guard.describe(offending, text)))

    if authored_by_model:
        invented = _unknown_names(text, names)
        if invented:
            findings.append(finding(
                "grounding", "block",
                f"The {where} on this page names "
                f"{', '.join(sorted(invented)[:3])}, which appears in no source. "
                f"Somebody will go looking for them.",
                page_id=page.page_id, element_id=element.element_id,
                action="regenerate_page"))

        unknown_dates = _unknown_dates(text, dates)
        if unknown_dates:
            findings.append(finding(
                "grounding", "block",
                f"The {where} on this page states a date "
                f"({', '.join(sorted(unknown_dates)[:2])}) that is in no source.",
                page_id=page.page_id, element_id=element.element_id,
                action="regenerate_page"))
    return findings


def _unknown_names(text: str, known: set[str]) -> set[str]:
    unknown: set[str] = set()
    for match in _PROPER_NOUN.finditer(text or ""):
        phrase = match.group(1)
        if phrase.casefold() in known:
            continue
        words = [w for w in phrase.split() if w not in _NOT_NAMES]
        if not words:
            continue
        # Only flag when *no* word of the phrase is known: "the MedAxis Finance
        # workstream" is a legitimate construction from known parts.
        if all(word.casefold() not in known for word in words):
            unknown.add(phrase)
    return unknown


def _unknown_dates(text: str, known: set[str]) -> set[str]:
    unknown: set[str] = set()
    for raw in _DATE.findall(text or ""):
        if _normalize_date(raw) not in known:
            unknown.add(raw if isinstance(raw, str) else str(raw))
    return unknown


def _check_titles(page: PageDesign, corpus: set[str],
                  dates: set[str]) -> list[Finding]:
    from app.report import guard

    findings: list[Finding] = []
    for text, where in ((page.title, "title"), (page.subtitle, "subtitle")):
        if not text:
            continue
        offending = guard.check_text(text, corpus)
        if offending:
            findings.append(finding(
                "grounding", "block",
                f"The page {where} states {', '.join(offending[:2])}, which is "
                f"not in the evidence.",
                page_id=page.page_id, action="regenerate_page",
                detail=guard.describe(offending, text)))
    return findings


#: A quantity, as opposed to a term of art. "Day 1", "Q4", "phase 2" and
#: "wave 3" are PMI vocabulary that happen to contain a digit; a bare single
#: digit is almost never a figure a reader would act on.
_QUANTITY = re.compile(
    r"(?<![\w-])(?:"
    r"\d{2,}"                                   # 60, 1,220,000
    r"|\d+\s*%"                                 # 40%
    r"|\d+[.,]\d+"                              # 1.5
    r"|(?:EUR|USD|GBP|CHF|\$|€|£)\s*\d+"        # EUR 1
    r"|\d+\s*(?:EUR|USD|GBP|CHF|m|bn|k)\b"      # 3m
    r")")


def _check_binding(page: PageDesign) -> list[Finding]:
    """A model-authored element stating a quantity and citing nothing.

    Structurally this should be unreachable — the planning schemas have no field
    for a value, and evidence ids are validated. It is checked because if it ever
    does happen the symptom is a number on a slide with no provenance.

    It fires on *quantities*, not on digits. "Day 1", "Q4" and "phase 2" are
    domain vocabulary, and blocking a page for saying "before Day 1 approaches"
    is a false positive that costs a regeneration and rewrites accepted text.
    Whether the figure is *supported* is `_check_text`'s job; this one is about
    whether it is *linked*, which is weaker — hence a warning.
    """
    findings: list[Finding] = []
    for element in page.elements:
        if element.authored_by != "llm" or element.evidence_ids:
            continue
        for text, where in _texts(element):
            if _QUANTITY.search(text):
                findings.append(finding(
                    "grounding", "warn",
                    f"The {where} on this page states a figure without linking "
                    f"the evidence it came from, so the page cannot cite it.",
                    page_id=page.page_id, element_id=element.element_id,
                    action="add_citation", detail=text[:160]))
    return findings


def _check_specs(deliverable: Deliverable,
                 context: GenerationContext) -> list[Finding]:
    """Re-validate every chart against evidence at the artifact level.

    The chart planner already validated these. Doing it again here is not
    redundant: a repair pass may have edited a page since, and this is the last
    gate before delivery.
    """
    from app.visualizations import validator

    findings: list[Finding] = []
    pages_by_spec: dict[str, str] = {}
    for page in deliverable.pages:
        for element in page.elements:
            spec_id = getattr(element, "spec_id", "")
            if spec_id:
                pages_by_spec[spec_id] = page.page_id

    for spec_id, spec in deliverable.specs.charts.items():
        result = validator.validate_chart(spec, context.evidence)
        if not result.ok:
            findings.append(finding(
                "grounding", "block",
                f"A chart on this page no longer validates against the "
                f"evidence: {result.summary}",
                page_id=pages_by_spec.get(spec_id), action="regenerate_page"))

    for spec_id, spec in deliverable.specs.tables.items():
        result = validator.validate_table(spec, context.evidence)
        if not result.ok:
            findings.append(finding(
                "grounding", "fix",
                f"A table on this page no longer validates: {result.summary}",
                page_id=pages_by_spec.get(spec_id), action="regenerate_page"))
    return findings


def unsupported_claims(deliverable: Deliverable,
                       context: GenerationContext) -> list[str]:
    """The blocking grounding findings, as sentences. For an API response."""
    return [f.message for f in check(deliverable, context).blocking]
