"""What a critic reports, and what the engine does about it.

A `Finding` names a page and, where it can, an element — because the repair loop
regenerates pages, not documents. A critic that can only say "something is wrong
with this deck" forces a full re-plan, which changes text the user has already
read in order to fix a layout problem.

`severity` is the contract with the engine:

* `block` — the artifact must not be delivered as it stands. An ungrounded
  figure, or a must-disclose conflict that appears nowhere.
* `fix` — regenerate the page and try again.
* `warn` — deliver, and say so in the artifact.
* `note` — record it; nobody needs to act.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

Critic = Literal["grounding", "completeness", "design", "overflow"]
Severity = Literal["block", "fix", "warn", "note"]
Action = Literal["regenerate_page", "shorten", "split_page", "drop_element",
                 "add_citation", "recompute", "relayout", "none"]
Verdict = Literal["ship", "fix_then_ship", "block"]

_ORDER = {"block": 0, "fix": 1, "warn": 2, "note": 3}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Finding(BaseModel):
    finding_id: str = ""
    critic: Critic
    severity: Severity = "warn"
    page_id: Optional[str] = None
    element_id: Optional[str] = None
    message: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    suggested_action: Action = "none"
    #: What the critic actually measured, for a developer reading a failure.
    detail: str = ""

    @property
    def rank(self) -> int:
        return _ORDER.get(self.severity, 9)


class ArtifactReview(BaseModel):
    review_id: str = ""
    at: str = Field(default_factory=_now)
    pass_number: int = 1
    format: str = ""
    findings: list[Finding] = Field(default_factory=list)

    # ------------------------------------------------------------- verdicts
    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "block"]

    @property
    def fixable(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "fix"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    @property
    def verdict(self) -> Verdict:
        if self.blocking:
            return "block"
        if self.fixable:
            return "fix_then_ship"
        return "ship"

    @property
    def passed(self) -> bool:
        return self.verdict == "ship"

    @property
    def pages_to_regenerate(self) -> list[str]:
        """Pages a repair pass should rebuild, most serious first."""
        seen: list[str] = []
        for finding in sorted(self.findings, key=lambda f: f.rank):
            if finding.severity not in ("block", "fix"):
                continue
            if finding.page_id and finding.page_id not in seen:
                seen.append(finding.page_id)
        return seen

    def by_critic(self, critic: str) -> list[Finding]:
        return [f for f in self.findings if f.critic == critic]

    def add(self, *findings: Finding) -> None:
        for finding in findings:
            if not finding.finding_id:
                finding.finding_id = (
                    f"{finding.critic[:4]}-{len(self.findings) + 1:03d}")
            self.findings.append(finding)

    def summary(self) -> str:
        if not self.findings:
            return "No findings."
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        parts = [f"{count} {severity}" for severity, count
                 in sorted(counts.items(), key=lambda kv: _ORDER.get(kv[0], 9))]
        return f"{self.verdict}: " + ", ".join(parts)

    def disclosures(self) -> list[str]:
        """Findings a reader should see, because they were not resolved.

        Includes `fix`: by the time this is read the repair loop has had its
        passes, so a surviving `fix` is a defect that is shipping. Only `note`
        is developer-facing.
        """
        return [f.message for f in self.findings if f.severity != "note"]


def finding(critic: str, severity: str, message: str, *,
            page_id: Optional[str] = None, element_id: Optional[str] = None,
            evidence_ids: Optional[list[str]] = None,
            action: str = "none", detail: str = "") -> Finding:
    """Terse constructor, because the critics build a lot of these."""
    return Finding(
        critic=critic,                                          # type: ignore[arg-type]
        severity=severity,                                      # type: ignore[arg-type]
        message=message, page_id=page_id, element_id=element_id,
        evidence_ids=evidence_ids or [],
        suggested_action=action,                                # type: ignore[arg-type]
        detail=detail)
