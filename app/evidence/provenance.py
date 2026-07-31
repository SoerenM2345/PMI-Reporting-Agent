"""Turn the evidence a page used into the note printed at its foot.

Every page cites what it actually drew on. That is only possible because a
`PageDesign` carries `evidence_ids` and an `EvidenceItem` carries the real
`SourceReference` objects — so "which file said this" is answerable per page
rather than per document.

Disclosure is not optional here. A page built on a figure read out of a
screenshot says so, in the artifact, next to the figure. Burying that in a
data-quality appendix is how a 0.35-confidence number ends up quoted in a board
minute as fact.
"""
from __future__ import annotations

from typing import Literal, Sequence

from app.evidence.model import EvidenceItem

ConfidenceBand = Literal["high", "medium", "low", "none"]


def citation_for(items: Sequence[EvidenceItem], *, limit: int = 4) -> str:
    """The distinct sources behind these items: "tracker.xlsx (sheet 'Risks')"."""
    seen: list[str] = []
    for item in items:
        for ref in item.sources:
            where = ref.location
            text = f"{ref.file_name} ({where})" if where else ref.file_name
            if text not in seen:
                seen.append(text)
    if not seen:
        return ""
    if len(seen) > limit:
        return "; ".join(seen[:limit]) + f"; and {len(seen) - limit} more"
    return "; ".join(seen)


def confidence_band(items: Sequence[EvidenceItem]) -> ConfidenceBand:
    """The weakest link, not the average.

    A page is only as trustworthy as its shakiest figure; averaging lets four
    solid numbers launder one that came out of a photograph.
    """
    scored = [i for i in items if i.sources or i.is_computed_value]
    if not scored:
        return "none"
    from app.config import get_settings

    threshold = get_settings().low_confidence_threshold
    worst = min(i.confidence for i in scored)
    if worst < threshold:
        return "low"
    if any(i.needs_review for i in scored) or worst < 0.95:
        return "medium"
    return "high"


def review_flags(items: Sequence[EvidenceItem]) -> list[str]:
    """Human-readable warnings a page must display, most serious first."""
    flags: list[str] = []

    contested = [i for i in items if i.is_contested]
    if contested:
        labels = ", ".join(sorted({i.label for i in contested})[:3])
        flags.append(f"Sources disagree about {labels}; see the conflict note.")

    transcribed = [i for i in items if i.needs_review]
    if transcribed:
        files = ", ".join(sorted({f for i in transcribed for f in i.source_files})[:3])
        flags.append(f"Includes figures read from an image ({files}); confirm "
                     f"before circulation.")

    assumptions = [i for i in items if i.origin == "user_assumption"]
    if assumptions:
        flags.append(f"Rests on {len(assumptions)} stated assumption(s), not on "
                     f"source data.")

    absences = [i for i in items if i.is_absence]
    if absences:
        flags.append(f"{len(absences)} element(s) of this page could not be "
                     f"evidenced; the gap is stated rather than estimated.")

    return flags


def source_note(items: Sequence[EvidenceItem], *, limit: int = 4) -> str:
    """The full footnote: where it came from, and what to be careful about."""
    parts: list[str] = []
    citation = citation_for(items, limit=limit)
    if citation:
        parts.append(f"Source: {citation}.")
    elif any(i.is_computed_value for i in items):
        parts.append("Source: computed from the project's own data.")
    parts.extend(review_flags(items))
    return " ".join(parts)


def derivation_note(item: EvidenceItem) -> str:
    """How a computed figure was arrived at, for a methodology panel."""
    if not item.derivation:
        return ""
    formula = f" ({item.derivation.formula})" if item.derivation.formula else ""
    count = len(item.derivation.input_evidence_ids)
    basis = f" from {count} record(s)" if count else ""
    return f"{item.label} is computed as {item.derivation.operation}{formula}{basis}."
