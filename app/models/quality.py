"""Conflicts and data quality (spec §8, §9, §13 sheet 10).

Two distinct kinds of finding, deliberately not merged into one type:

* A **Conflict** is two or more sources disagreeing about the same value. It has
  competing candidates, so it can be *resolved* — by source priority, or by asking
  the user which is right (§9).

* A **ValidationIssue** is a single source violating an invariant: progress above
  100%, a completion date before the start date, a critical risk with no mitigation
  owner. There is no second candidate to pick, so "resolution" is meaningless — it
  is reported and, where we can compute the right answer, corrected.

Forcing both into one model would make `resolve_conflicts()` incoherent.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from pydantic import BaseModel, Field, computed_field

from app.models.enums import Severity, SourceFormat
from app.models.source import SourceReference


class ConflictEvidence(BaseModel):
    """One source's claim in a disagreement."""

    source_reference: SourceReference
    value: str
    entity_id: Optional[str] = None

    @property
    def file_name(self) -> str:
        return self.source_reference.file_name

    @property
    def file_type(self) -> SourceFormat:
        return self.source_reference.file_type


class Conflict(BaseModel):
    """Sources disagree about one field of one entity (§8.1)."""

    conflict_id: str = ""
    #: Which check produced this, e.g. "PMI-002". Lets the UI and the report group
    #: findings, and lets us test one check in isolation.
    check_id: str = "PMI-000"
    family: str = "cross_source"

    entity_type: str            # "kpi" | "task" | "milestone" | ...
    entity_key: str             # what the conflicting values describe
    field: str

    evidence: list[ConflictEvidence] = Field(default_factory=list)

    severity: Severity = Severity.MEDIUM
    message: str = ""

    resolved_value: Optional[str] = None
    resolved_from: Optional[str] = None     # file the winning value came from
    resolution: Optional[str] = None        # "source_priority" | "user" | "user_value"
    resolution_note: Optional[str] = None

    def model_post_init(self, __context) -> None:
        if not self.conflict_id:
            seed = f"{self.check_id}|{self.entity_type}|{self.entity_key}|{self.field}"
            digest = hashlib.sha1(seed.encode()).hexdigest()[:10]
            object.__setattr__(self, "conflict_id", f"cf_{digest}")

    # -- back-compatible views ------------------------------------------------
    # The original model stored these as plain dicts. They are now derived from
    # `evidence`, which additionally carries the sheet/slide/page/region — so the
    # UI can show *where* each claim came from, not just which file.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def values(self) -> dict[str, str]:
        return {e.file_name: e.value for e in self.evidence}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def formats(self) -> dict[str, SourceFormat]:
        return {e.file_name: e.file_type for e in self.evidence}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def critical(self) -> bool:
        """§9 Mode C: high and critical conflicts go to the user, the rest resolve
        automatically."""
        return self.severity in (Severity.HIGH, Severity.CRITICAL)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def requires_user_input(self) -> bool:
        return self.critical and self.resolved_value is None

    @property
    def is_resolved(self) -> bool:
        return self.resolved_value is not None


class ValidationIssue(BaseModel):
    """An invariant violated within a single source (§8.2-8.4)."""

    issue_id: str = ""
    check_id: str
    family: str                 # "mathematical" | "temporal" | "completeness"
    severity: Severity = Severity.MEDIUM

    entity_type: str
    entity_id: Optional[str] = None
    entity_label: str = ""
    field: Optional[str] = None

    message: str
    #: Set when we could compute the right answer and did (§11). Left None for a
    #: completeness gap — a missing owner cannot be derived, only reported.
    corrected_value: Optional[str] = None
    reported_value: Optional[str] = None

    source_references: list[SourceReference] = Field(default_factory=list)

    def model_post_init(self, __context) -> None:
        if not self.issue_id:
            seed = f"{self.check_id}|{self.entity_type}|{self.entity_id}|{self.field}"
            digest = hashlib.sha1(seed.encode()).hexdigest()[:10]
            object.__setattr__(self, "issue_id", f"vi_{digest}")


class DataQualityReport(BaseModel):
    """The honesty artefact (§17, §18.19, §21.17).

    Deliberately reports what the run could *not* do — files that failed, values it
    refused to guess, image findings too blurry to trust, LLM tasks that fell back
    to templates — alongside what it did.
    """

    score: float = Field(default=0.0, ge=0.0, le=100.0)

    total_entities: int = 0
    entities_with_sources: int = 0
    low_confidence_entities: int = 0

    conflicts_total: int = 0
    conflicts_auto_resolved: int = 0
    conflicts_user_resolved: int = 0
    conflicts_unresolved: int = 0

    issues_by_family: dict[str, int] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)

    #: Files that could not be read at all.
    failed_files: list[str] = Field(default_factory=list)
    #: Soft caveats: LLM fallbacks, unparseable rows, uninterpretable images.
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_trustworthy(self) -> bool:
        return self.score >= 70 and self.conflicts_unresolved == 0
