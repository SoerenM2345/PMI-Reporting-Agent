"""The evidence layer: what a deliverable may say, and where it came from.

`projection.project(model)` turns the validated `PMIDataModel` into an
`EvidenceIndex` of addressable claims. `retrieval.retrieve()` ranks them against
a request; `retrieval.pack()` renders the winners into a prompt budget and says
what it left out. `provenance` turns the evidence a page used into its footnote.

The normalized PMI model stays the authority for validation. It is no longer the
shape of the report.
"""
from __future__ import annotations

from app.evidence.model import Derivation, EvidenceIndex, EvidenceItem, EvidenceOrigin
from app.evidence.projection import COLLECTIONS, project
from app.evidence.provenance import (
    citation_for,
    confidence_band,
    review_flags,
    source_note,
)
from app.evidence.retrieval import PackedEvidence, RetrievalResult, pack, retrieve

__all__ = [
    "COLLECTIONS",
    "Derivation",
    "EvidenceIndex",
    "EvidenceItem",
    "EvidenceOrigin",
    "PackedEvidence",
    "RetrievalResult",
    "citation_for",
    "confidence_band",
    "pack",
    "project",
    "retrieve",
    "review_flags",
    "source_note",
]
