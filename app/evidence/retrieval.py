"""Select the evidence a planning call should see, and say what it did not.

Two rules make this safe to put in front of a model.

**Bad news is not rankable.** An unresolved critical disagreement and an
unmitigated critical risk are always included, whatever they score. Retrieval
exists to fit a corpus into a prompt, and it must never become the mechanism by
which the finding a Steering Committee needed quietly failed to make the cut.
`force_include` carries `EvidenceIndex.must_include()` on every call.

**Truncation is disclosed.** A `RetrievalResult` reports what it dropped and of
what kind, and `pack()` writes that into the prompt in words. A model told it is
seeing everything will write "there are three open risks"; a model told it is
seeing 40 of 137 records will not.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.evidence.model import EvidenceIndex, EvidenceItem
from app.evidence.scoring import InvertedIndex, build_index, expand, tokenize

log = logging.getLogger("pmi.evidence.retrieval")

#: Deterministic boosts, applied on top of BM25. Tuned so that a topical match
#: still outranks an off-topic critical risk, while an on-topic critical risk
#: comfortably outranks an on-topic closed one.
BOOST_CONTESTED = 0.8
BOOST_SEVERE = 0.6
BOOST_OPEN = 0.5
BOOST_IN_PERIOD = 0.4
BOOST_KIND_NAMED = 0.4
BOOST_NAMED_VERBATIM = 0.3
PENALTY_LOW_CONFIDENCE = 0.5
PENALTY_ASSUMPTION = 0.3
#: `EvidenceOrigin` calls `user_confirmed` authoritative and nothing enforced it:
#: the only origin-aware line here was the assumption *penalty*. A correction is
#: one short sentence, so it lost on BM25 length normalisation to an entity item
#: whose search text concatenates half a dozen fields — the user's own value
#: ranked below the figure they had just overruled.
BOOST_USER_CONFIRMED = 0.7

_SEVERE = frozenset({"critical", "high"})
_OPEN = frozenset({"open", "not_started", "in_progress", "at_risk", "blocked",
                   "unknown"})


class ScoredEvidence(BaseModel):
    model_config = ConfigDict(revalidate_instances="never")

    item: EvidenceItem
    score: float
    forced: bool = False
    reasons: list[str] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(revalidate_instances="never")

    query: str = ""
    included: list[EvidenceItem] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    omitted_count: int = 0
    omitted_kinds: dict[str, int] = Field(default_factory=dict)
    forced_ids: list[str] = Field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        return [item.evidence_id for item in self.included]

    @property
    def truncated(self) -> bool:
        return self.omitted_count > 0

    def disclosure(self) -> str:
        """One honest sentence about what was withheld, for the prompt."""
        if not self.truncated:
            return "You are seeing every record in this project."
        kinds = ", ".join(f"{count} {kind}" for kind, count
                          in sorted(self.omitted_kinds.items(),
                                    key=lambda kv: -kv[1])[:6])
        return (f"You are seeing {len(self.included)} of "
                f"{len(self.included) + self.omitted_count} records. Not shown: "
                f"{kinds}. Do not state totals or counts over the whole project "
                f"from this list; cite the computed facts instead.")


class PackedEvidence(BaseModel):
    text: str
    included_ids: list[str] = Field(default_factory=list)
    disclosure: str = ""
    char_count: int = 0


def retrieve(query: str, evidence: EvidenceIndex, *,
             kinds: Optional[Sequence[str]] = None,
             k: int = 60,
             force_include: Sequence[str] = (),
             include_mandatory: bool = True,
             reporting_date: Optional[date] = None,
             named_terms: Sequence[str] = ()) -> RetrievalResult:
    """The `k` most relevant items, plus everything that may never be dropped."""
    pool = [i for i in evidence.items.values()
            if not kinds or i.kind in set(kinds)]
    if not pool:
        return RetrievalResult(query=query)

    index = build_index((i.evidence_id, i.search_text) for i in pool)
    tokens = expand(tokenize(query))
    named = {t for term in named_terms for t in tokenize(term)}
    kind_tokens = {t for t in tokens}

    forced = set(force_include)
    if include_mandatory:
        forced |= set(evidence.must_include())
    # A kind-restricted retrieval cannot return an item outside its pool. Do not
    # report that deliberate scope boundary as an accidental dropped finding;
    # whole-document retrieval remains responsible for mandatory disclosures.
    forced &= {item.evidence_id for item in pool}
    scored = [_score(item, index, tokens, kind_tokens, named, reporting_date,
                     forced) for item in pool]
    scored.sort(key=lambda s: (not s.forced, -s.score, s.item.evidence_id))

    included = scored[:max(k, len(forced))]
    omitted = scored[len(included):]
    omitted_kinds: dict[str, int] = {}
    for entry in omitted:
        omitted_kinds[entry.item.kind] = omitted_kinds.get(entry.item.kind, 0) + 1

    result = RetrievalResult(
        query=query,
        included=[s.item for s in included],
        scores={s.item.evidence_id: round(s.score, 4) for s in included},
        omitted_count=len(omitted),
        omitted_kinds=omitted_kinds,
        forced_ids=sorted(forced & {s.item.evidence_id for s in included}),
    )
    missing = forced - set(result.ids)
    if missing:
        # Should be unreachable: forced items sort first and `k` is widened to
        # fit them. Loud rather than silent, because the failure mode is a board
        # pack that omits the thing it existed to disclose.
        log.error("retrieval dropped %d must-include items: %s",
                  len(missing), sorted(missing))
    return result


def _score(item: EvidenceItem, index: InvertedIndex, tokens: Sequence[str],
           kind_tokens: set[str], named: set[str],
           reporting_date: Optional[date], forced: set[str]) -> ScoredEvidence:
    score = index.bm25(item.evidence_id, tokens)
    reasons: list[str] = []

    if item.is_contested:
        score += BOOST_CONTESTED
        reasons.append("contested")
    if (item.severity or "") in _SEVERE:
        score += BOOST_SEVERE
        reasons.append("severe")
    if (item.status or "") in _OPEN and item.kind in ("risk", "issue", "task",
                                                      "decision", "dependency"):
        score += BOOST_OPEN
        reasons.append("open")
    if reporting_date and item.due and abs((item.due - reporting_date).days) <= 45:
        score += BOOST_IN_PERIOD
        reasons.append("in period")
    if item.kind in kind_tokens:
        score += BOOST_KIND_NAMED
        reasons.append("kind named")
    if named and named & set(tokenize(item.label)):
        score += BOOST_NAMED_VERBATIM
        reasons.append("named verbatim")

    # Ranked down, never hidden: a low-confidence read still belongs in the
    # document, carrying its disclosure.
    if item.confidence and item.confidence < _threshold():
        score -= PENALTY_LOW_CONFIDENCE
        reasons.append("low confidence")
    if item.origin == "user_assumption":
        score -= PENALTY_ASSUMPTION
        reasons.append("assumption")
    elif item.origin == "user_confirmed":
        score += BOOST_USER_CONFIRMED
        reasons.append("user-confirmed")

    return ScoredEvidence(item=item, score=score,
                          forced=item.evidence_id in forced, reasons=reasons)


def _threshold() -> float:
    from app.config import get_settings

    return get_settings().low_confidence_threshold


def pack(result: RetrievalResult, *, budget_chars: int = 40_000) -> PackedEvidence:
    """Render retrieved evidence as dense lines that fit a prompt budget.

    One line per item rather than JSON: roughly four times the evidence per
    token, and a model scans it more reliably than nested objects. Items are
    emitted in rank order and the budget is enforced by dropping the tail, so
    what survives is always the most relevant — never a truncated final record,
    which would present a half-read figure as a whole one.
    """
    lines: list[str] = []
    included: list[str] = []
    used = 0
    dropped = 0

    for item in result.included:
        line = item.one_line()
        if used + len(line) + 1 > budget_chars and included:
            dropped += 1
            continue
        lines.append(line)
        included.append(item.evidence_id)
        used += len(line) + 1

    disclosure = result.disclosure()
    if dropped:
        disclosure += (f" A further {dropped} record(s) were trimmed to fit the "
                       f"context budget.")

    return PackedEvidence(
        text="\n".join(lines),
        included_ids=included,
        disclosure=disclosure,
        char_count=used,
    )
