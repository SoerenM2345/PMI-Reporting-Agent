"""What the report is allowed to say, and where each claim came from.

`PMIDataModel` is the right shape for *validating* a PMI programme and the wrong
shape for *writing* about one. It is organised by entity type, so a planner
reading it can only ever ask "what risks are there" — which is precisely how the
old planner ended up with one fixed section per collection.

An `EvidenceItem` is one addressable, quotable claim: a risk, a computed
variance, a disagreement between two files, a fact the user stated, or the
considered absence of any of those. The planning model selects evidence by id
and never restates a figure; Python resolves ids to values at render time. That
is what makes an invented number structurally impossible rather than merely
discouraged.

Three properties are load-bearing:

* **`sources` holds the real `SourceReference` objects**, not a flattened copy.
  `cite()`, `image_region`, `extraction_confidence` and `needs_review` all
  survive projection, so a figure on a slide can still say which cell of which
  sheet it came from.

* **Absence is evidence.** "No source covers TSA exit readiness" is a first-class
  item with an id a page can cite. Without it, a requested topic with no data
  can only vanish, and a report that quietly drops a section is worse than one
  that says it has nothing to say.

* **A conflict is evidence too.** Sources disagreeing is a finding a Steering
  Committee needs, not an error to resolve away before writing.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from app.models.source import SourceReference

log = logging.getLogger("pmi.evidence")

#: The only statuses that close something. Mirrors `Status.is_open`, which every
#: other layer already uses; see `EvidenceIndex.must_include` for why a positive
#: list of "open-sounding" statuses is the wrong shape.
CLOSED_STATUSES = frozenset({"completed", "cancelled", "done", "closed",
                             "resolved", "mitigated"})


def is_open_status(status: Optional[str]) -> bool:
    """Whether an item still needs attention. Unknown counts as open."""
    return (status or "").casefold() not in CLOSED_STATUSES

EvidenceOrigin = Literal[
    "direct_source_value",   # read from a file, verbatim
    "normalized_value",      # read, then standardized (status, date, currency)
    "computed_value",        # calculations.py, or a validated CalculationRequest
    "conflict",              # sources disagree; the disagreement is the finding
    "quality_issue",         # a ValidationIssue
    "user_confirmed",        # the user stated it and it is authoritative
    "user_assumption",       # the user assumed it — never presented as fact
    "absence",               # nothing covers this; stated, never silent
]

#: Origins whose numbers may be quoted without further qualification.
FACTUAL_ORIGINS = frozenset({
    "direct_source_value", "normalized_value", "computed_value", "user_confirmed",
})


class Derivation(BaseModel):
    """How a computed value came to be. Never free text from a model."""

    operation: str                                   # "budget_variance", "sum"
    input_evidence_ids: list[str] = Field(default_factory=list)
    formula: str = ""                                # "budget − forecast"
    calculation_id: str = ""


class EvidenceItem(BaseModel):
    """One quotable claim, with its provenance attached."""

    # `revalidate_instances="never"` is the default, and it is what keeps the
    # `SourceReference` objects below identical rather than reconstructed.
    model_config = ConfigDict(revalidate_instances="never")

    evidence_id: str
    kind: str                                        # "risk", "fact", "conflict", …
    origin: EvidenceOrigin
    label: str
    #: One honest sentence, authored by Python. The planner may quote it; it may
    #: not invent a replacement that states a different figure.
    statement: str = ""

    value: Optional[Union[float, int, str]] = None
    #: Already formatted for display. Renderers never re-derive a figure.
    display: str = ""
    unit: Optional[str] = None
    currency: Optional[str] = None
    period: Optional[str] = None
    as_of: Optional[date] = None

    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    workstream: Optional[str] = None
    owner: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    due: Optional[date] = None

    sources: list[SourceReference] = Field(default_factory=list)
    derivation: Optional[Derivation] = None
    conflict_ids: list[str] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)

    #: The originating entity, for renderers that need a field the projection
    #: did not promote (a mitigation action, a list of options).
    payload: dict[str, Any] = Field(default_factory=dict)
    #: Built once at projection time; the retrieval index reads only this.
    search_text: str = ""

    # ------------------------------------------------------------ predicates
    @property
    def is_direct_source_value(self) -> bool:
        return self.origin in ("direct_source_value", "normalized_value")

    @property
    def is_computed_value(self) -> bool:
        return self.origin == "computed_value"

    @property
    def is_quotable_fact(self) -> bool:
        """Whether a page may state this without hedging it."""
        return self.origin in FACTUAL_ORIGINS

    @property
    def is_absence(self) -> bool:
        return self.origin == "absence"

    @property
    def is_contested(self) -> bool:
        return bool(self.conflict_ids)

    @property
    def confidence(self) -> float:
        """Best confidence across corroborating sources.

        A figure in a tracker *and* a screenshot is as good as the tracker; the
        screenshot does not drag it down. Computed values inherit the confidence
        of their weakest input, because arithmetic cannot be surer than its
        operands — but that is resolved by the caller, which has the inputs.
        """
        if self.origin in ("computed_value", "user_confirmed"):
            return 1.0
        if not self.sources:
            return 0.0
        return max(ref.extraction_confidence for ref in self.sources)

    @property
    def needs_review(self) -> bool:
        """True when nothing but a transcription backs this."""
        return bool(self.sources) and all(ref.needs_review for ref in self.sources)

    @property
    def source_files(self) -> list[str]:
        seen: list[str] = []
        for ref in self.sources:
            if ref.file_name not in seen:
                seen.append(ref.file_name)
        return seen

    def cite(self) -> str:
        if not self.sources:
            return {"computed_value": "computed from source data",
                    "user_confirmed": "stated by the user",
                    "user_assumption": "user assumption",
                    "absence": "no source"}.get(self.origin, "unattributed")
        return "; ".join(ref.cite() for ref in self.sources[:3])

    def one_line(self) -> str:
        """A dense line for the planning prompt. Never JSON — roughly four times
        the evidence per token, and easier for a model to scan."""
        facets = [f"{k}={v}" for k, v in (
            ("severity", self.severity), ("status", self.status),
            ("owner", self.owner or "?"), ("ws", self.workstream),
            ("due", self.due), ("period", self.period),
        ) if v]
        parts = [self.evidence_id, self.kind, self.label]
        if self.display:
            parts.append(self.display)
        line = " | ".join(str(p) for p in parts)
        if facets:
            line += " | " + " ".join(facets)
        flags = []
        if self.confidence < 1.0:
            flags.append(f"conf={self.confidence:.2f}")
        if self.is_contested:
            flags.append("CONTESTED(" + ",".join(self.conflict_ids) + ")")
        if self.origin == "user_assumption":
            flags.append("ASSUMPTION")
        if self.is_absence:
            flags.append("ABSENT")
        if flags:
            line += " | " + " ".join(flags)
        if self.sources:
            line += " | src=" + ", ".join(
                f"{r.file_name}{f' ({r.location})' if r.location else ''}"
                for r in self.sources[:2])
        return line


class EvidenceIndex(BaseModel):
    """Every claim available to a deliverable, addressable by id."""

    model_config = ConfigDict(revalidate_instances="never")

    items: dict[str, EvidenceItem] = Field(default_factory=dict)
    #: Recorded at projection time so a prompt can say what it is not seeing.
    projected_from_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------- mutation
    def add(self, item: EvidenceItem) -> EvidenceItem:
        if item.evidence_id in self.items:
            log.debug("duplicate evidence id %s; keeping the first",
                      item.evidence_id)
            return self.items[item.evidence_id]
        self.items[item.evidence_id] = item
        return item

    def extend(self, items: Iterable[EvidenceItem]) -> None:
        for item in items:
            self.add(item)

    # ------------------------------------------------------------- accessors
    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):                                  # type: ignore[override]
        return iter(self.items.values())

    def get(self, evidence_id: str) -> Optional[EvidenceItem]:
        return self.items.get(evidence_id)

    def resolve(self, ids: Iterable[str]) -> list[EvidenceItem]:
        """Known items, in the order asked. Unknown ids are dropped silently
        here — callers that need to *report* an unknown id use `unknown()`."""
        return [self.items[i] for i in ids if i in self.items]

    def unknown(self, ids: Iterable[str]) -> list[str]:
        return [i for i in ids if i not in self.items]

    def of_kind(self, *kinds: str) -> list[EvidenceItem]:
        wanted = set(kinds)
        return [i for i in self.items.values() if i.kind in wanted]

    def by_origin(self, *origins: str) -> list[EvidenceItem]:
        wanted = set(origins)
        return [i for i in self.items.values() if i.origin in wanted]

    @property
    def kinds(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items.values():
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return dict(sorted(counts.items()))

    # --------------------------------------------------------------- policy
    def numeric_corpus(self) -> set[str]:
        """Every number the deliverable is entitled to state.

        Feeds `app/report/guard.py`, which rejects model-authored prose
        containing anything outside it. Absence items contribute nothing: "no
        source covers this" must not license quoting a figure.

        Three sources, and all three are needed:

        * the item's own `value` and `display`;
        * **every numeric field in `payload`** — a chart series reads `forecast`
          or `target_value` straight out of the payload, so a corpus without
          them would reject prose about a figure the chart beside it is drawing;
        * the numbers inside `statement`, which Python authored from the evidence
          and which therefore includes its dates. Without this the guard rejects
          its own deterministic wording, because `15-09-2026` tokenises into
          `-09` and `-2026`.
        """
        from app.report import guard

        corpus: set[str] = set()
        for item in self.items.values():
            if item.is_absence:
                continue
            corpus |= guard.numbers_in(item.display)
            corpus |= guard.numbers_in(item.statement)
            if item.value is not None:
                corpus |= guard.numbers_in(str(item.value))
            for raw in item.payload.values():
                if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    corpus |= guard.numbers_in(str(raw))
                elif isinstance(raw, str) and any(c.isdigit() for c in raw):
                    # Dates and pre-formatted figures the source stated.
                    corpus |= guard.numbers_in(raw)
        return corpus

    def must_include(self) -> list[str]:
        """Evidence a deliverable may never omit, whatever it is about.

        Retrieval ranks; it must not be the mechanism by which bad news
        disappears from a board pack. An unresolved critical disagreement and an
        unmitigated critical risk go in the document or the completeness critic
        blocks it.

        "Open" is `Status.is_open`'s definition — anything not completed or
        cancelled — and not a list of the statuses that sound open. Normalization
        maps the *word* "open" to `not_started`, so a membership test naming
        `"open"` matches almost no risk in practice, and the case it misses most
        reliably is the worst one there is: a critical risk nobody has started
        mitigating. An unknown status counts as open for the same reason; the
        safe direction to be wrong in is disclosure.
        """
        required: list[str] = []
        for item in self.items.values():
            if item.origin == "conflict" and item.payload.get("requires_user_input"):
                required.append(item.evidence_id)
            elif (item.severity in ("critical", "high")
                  and is_open_status(item.status)
                  and item.kind in ("risk", "issue")
                  and not item.payload.get("mitigation_action")):
                required.append(item.evidence_id)
            elif item.kind == "user_value":
                # A figure the user personally corrected. Ranking their own
                # value out of the document they asked for is the same class of
                # failure as dropping a critical risk: retrieval decides what is
                # relevant, never what is allowed to be true.
                required.append(item.evidence_id)
        return sorted(required)

    def contested(self) -> list[EvidenceItem]:
        return [i for i in self.items.values() if i.is_contested]

    def needing_review(self) -> list[EvidenceItem]:
        return [i for i in self.items.values() if i.needs_review]
