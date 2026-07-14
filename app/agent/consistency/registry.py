"""The check registry (spec §8).

Every check declares itself with a decorator and is run by `run_all`. Two kinds:

* `@conflict_check` — two or more sources disagree about the same value. There are
  competing candidates, so it can be *resolved* (§9).
* `@issue_check` — one source violates an invariant: progress above 100%, a due date
  before the start date, a critical risk with no mitigation owner. There is no second
  candidate to choose between, so "resolution" is meaningless. It is reported, and
  where the right answer is computable, corrected.

A check that raises is recorded and skipped. One malformed spreadsheet must not be
able to sink an entire Steering Committee report by taking a check down with it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Literal

from app.agent.matching import EntityGroups
from app.config import Settings
from app.models.pmi import Conflict, PMIDataModel, Severity, ValidationIssue

log = logging.getLogger("pmi.checks")

CheckKind = Literal["conflict", "issue"]
Family = Literal["cross_source", "mathematical", "temporal", "completeness"]


@dataclass
class CheckContext:
    """Everything a check may read. Built once per run and shared, so every check
    agrees with every other about what counts as 'the same task'."""

    model: PMIDataModel
    groups: EntityGroups
    settings: Settings
    warnings: list[str] = field(default_factory=list)

    @property
    def reporting_date(self):
        from datetime import date

        return self.model.project.reporting_date or date.today()


@dataclass
class CheckResults:
    conflicts: list[Conflict] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Check:
    id: str
    family: Family
    title: str
    kind: CheckKind
    default_severity: Severity
    fn: Callable[[CheckContext], list]


_REGISTRY: list[Check] = []


def conflict_check(id: str, family: Family, title: str, severity: Severity):
    def decorate(fn):
        _REGISTRY.append(Check(id=id, family=family, title=title, kind="conflict",
                               default_severity=severity, fn=fn))
        return fn
    return decorate


def issue_check(id: str, family: Family, title: str, severity: Severity):
    def decorate(fn):
        _REGISTRY.append(Check(id=id, family=family, title=title, kind="issue",
                               default_severity=severity, fn=fn))
        return fn
    return decorate


def registered() -> list[Check]:
    """All checks, for the docs and for the data-quality report's coverage table."""
    return sorted(_REGISTRY, key=lambda c: c.id)


def run_all(ctx: CheckContext) -> CheckResults:
    results = CheckResults()

    for check in registered():
        try:
            found = check.fn(ctx) or []
        except Exception as exc:
            # A broken check is a bug in us, not in the user's data. Say so, and
            # keep the other 37 running.
            message = f"consistency check {check.id} ({check.title}) failed: {exc}"
            log.exception(message)
            results.failed_checks.append(message)
            ctx.warnings.append(message)
            continue

        if check.kind == "conflict":
            results.conflicts.extend(found)
        else:
            results.issues.extend(found)

    log.info("ran %d checks: %d conflicts, %d issues, %d failures",
             len(_REGISTRY), len(results.conflicts), len(results.issues),
             len(results.failed_checks))
    return results
