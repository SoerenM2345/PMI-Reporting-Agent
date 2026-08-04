"""Rank evidence against a request, deterministically and without a model.

BM25 over the evidence's own `search_text`, plus domain boosts. No embeddings,
no new dependency, no network call: retrieval runs on every plan and every page,
and a semantic index that had to be built and warmed would dominate the cost of
generating a report for no measurable gain over a corpus of a few hundred short
records.

The thesaurus is the part that earns its keep. A user asking about "cost savings"
is asking about synergies; one asking about "go-live" is asking about Day 1.
Lexical matching alone fails both, and failing them is not a ranking nuisance —
it means the finance section of a finance report retrieves nothing.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Sequence

#: Standard BM25 parameters. b=0.75 matters here: evidence lengths vary by an
#: order of magnitude (a KPI line versus a status update), and without length
#: normalization the verbose records would dominate every query.
BM25_K1 = 1.2
BM25_B = 0.75

_STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have
how i if in into is it its me my no nor not of on or our out over own please
should show so some such than that the their them then there these they this
those to too us was we were what when where which while who why will with would
you your give get make need want tell about
""".split())

#: PMI vocabulary a user and a tracker rarely spell the same way. Each key
#: expands to its synonyms at query time only, never at index time — expanding
#: the index would blur the documents into each other.
PMI_THESAURUS: dict[str, tuple[str, ...]] = {
    "synergy": ("saving", "savings", "benefit", "benefits", "run-rate", "realisation",
                "realization", "value"),
    "saving": ("synergy", "synergies", "benefit", "cost"),
    "cost": ("spend", "expense", "budget", "actual", "one-off", "one-time"),
    "budget": ("cost", "spend", "actual", "forecast", "variance", "financial"),
    "variance": ("overrun", "over-budget", "underspend", "deviation", "budget"),
    "overrun": ("variance", "over-budget", "exceed", "overspend"),
    "finance": ("financial", "budget", "cost", "cash", "synergy", "kpi"),
    "cash": ("cashflow", "cash-flow", "liquidity", "working-capital"),
    "day": ("day-1", "day1", "cutover", "go-live", "golive", "close", "closing"),
    "cutover": ("day-1", "day1", "go-live", "golive", "transition"),
    "risk": ("exposure", "threat", "concern", "issue"),
    "issue": ("problem", "blocker", "escalation", "risk"),
    "overdue": ("late", "slipped", "delayed", "behind", "missed"),
    "delay": ("slip", "slipped", "late", "overdue", "postponed"),
    "milestone": ("deadline", "gate", "checkpoint", "date", "go-live"),
    "decision": ("approval", "approve", "steerco", "steering", "sign-off", "mandate"),
    "steerco": ("steering", "committee", "board", "decision", "governance"),
    "workstream": ("stream", "function", "team", "track"),
    "dependency": ("interlock", "handover", "blocker", "prerequisite"),
    "progress": ("status", "completion", "percent", "tracking"),
    "readiness": ("prepared", "ready", "day-1", "cutover"),
    "integration": ("pmi", "merger", "post-merger", "combination"),
    "erp": ("system", "sap", "migration", "it", "technology"),
    "migration": ("cutover", "transition", "erp", "system", "cloud",
                  "infrastructure"),
    "infrastructure": ("system", "hosting", "cloud", "network", "vpn",
                       "datacenter", "data-center"),
    "headcount": ("fte", "people", "hr", "staff", "organisation", "organization"),
    "tsa": ("transitional", "service", "agreement", "exit", "separation"),
    "quality": ("confidence", "conflict", "gap", "completeness", "reliability"),
    "conflict": ("disagree", "disagreement", "discrepancy", "mismatch"),
    "next": ("upcoming", "forward", "plan", "action", "step"),
    "summary": ("overview", "executive", "headline", "key"),
}


def tokenize(text: str) -> list[str]:
    """Casefold, split on non-alphanumerics, drop stopwords, de-pluralise.

    Only plural suffixes are stripped. A real stemmer would collapse "planning"
    and "planned" onto "plan", which reads like an improvement and in practice
    also collapses "closing" onto "close" — and "closing date" and "close" mean
    different things to a deal team.
    """
    out: list[str] = []
    for word in re.split(r"[^a-z0-9]+", text.casefold()):
        if not word or word in _STOPWORDS:
            continue
        # Single letters are noise; single digits are not. "Day 1" is the term
        # of art in this domain, and dropping the 1 makes it identical to Day 2.
        if len(word) < 2 and not word.isdigit():
            continue
        out.append(_singular(word))
    return out


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def expand(tokens: Sequence[str]) -> list[str]:
    """Query tokens plus their PMI synonyms, de-duplicated, order preserved."""
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        for candidate in (token, *PMI_THESAURUS.get(token, ())):
            key = _singular(candidate.casefold())
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


@dataclass
class InvertedIndex:
    """Term statistics over a fixed set of documents."""

    frequencies: dict[str, Counter] = field(default_factory=dict)
    lengths: dict[str, int] = field(default_factory=dict)
    document_frequency: Counter = field(default_factory=Counter)
    average_length: float = 0.0

    @property
    def size(self) -> int:
        return len(self.lengths)

    def bm25(self, doc_id: str, query_tokens: Sequence[str]) -> float:
        counts = self.frequencies.get(doc_id)
        if not counts:
            return 0.0
        length = self.lengths.get(doc_id, 0) or 1
        norm = BM25_K1 * (1 - BM25_B + BM25_B * length / (self.average_length or 1))
        score = 0.0
        for token in query_tokens:
            frequency = counts.get(token, 0)
            if not frequency:
                continue
            df = self.document_frequency.get(token, 0)
            idf = math.log(1 + (self.size - df + 0.5) / (df + 0.5))
            score += idf * (frequency * (BM25_K1 + 1)) / (frequency + norm)
        return score


def build_index(documents: Iterable[tuple[str, str]]) -> InvertedIndex:
    """`(doc_id, text)` pairs -> term statistics."""
    index = InvertedIndex()
    total = 0
    for doc_id, text in documents:
        tokens = tokenize(text)
        counts = Counter(tokens)
        index.frequencies[doc_id] = counts
        index.lengths[doc_id] = len(tokens)
        total += len(tokens)
        for token in counts:
            index.document_frequency[token] += 1
    index.average_length = (total / index.size) if index.size else 0.0
    return index
