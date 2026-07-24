"""Consistency checks and conflict resolution (spec §8, §9).

Public surface — unchanged from the single-module version, so existing callers and
tests keep working:

    detect_conflicts(model)   -> list[Conflict]
    run_checks(model)         -> CheckResults          (conflicts + validation issues)
    resolve_conflicts(...)    -> list[Conflict]
    apply_resolutions(model)  -> PMIDataModel

Importing this package registers every check via its decorator, which is why the
check modules are imported for their side effects below.
"""
from __future__ import annotations

from app.agent.consistency import (  # noqa: F401  (imported to register the checks)
    completeness,
    cross_source,
    mathematical,
    temporal,
)
from app.agent.consistency.registry import (
    Check,
    CheckContext,
    CheckResults,
    conflict_check,
    issue_check,
    registered,
    run_all,
)
from app.agent.consistency.resolution import (
    MODE_TO_STRATEGY,
    apply_resolutions,
    critical_unresolved,
    resolve_conflicts,
)
from app.agent.consistency.severity import (
    CRITICAL_TOPICS,
    critical_topic,
    escalate,
    relative_delta,
)
from app.agent.matching import match_entities
from app.config import get_settings
from app.models.pmi import Conflict, PMIDataModel


def run_checks(model: PMIDataModel) -> CheckResults:
    """Run every registered check (§8.1-8.4) against one matched data model."""
    ctx = CheckContext(
        model=model,
        groups=match_entities(model),
        settings=get_settings(),
    )
    results = run_all(ctx)
    model.warnings.extend(ctx.warnings)
    return results


def detect_conflicts(model: PMIDataModel) -> list[Conflict]:
    """Cross-source conflicts only (§8.1). Kept for callers that only want those."""
    return run_checks(model).conflicts


__all__ = [
    "Check", "CheckContext", "CheckResults",
    "CRITICAL_TOPICS", "MODE_TO_STRATEGY",
    "apply_resolutions", "conflict_check", "critical_topic", "critical_unresolved",
    "detect_conflicts", "escalate", "issue_check", "registered", "relative_delta",
    "resolve_conflicts", "run_all", "run_checks",
]
