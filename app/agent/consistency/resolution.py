"""§9 — conflict resolution.

Mode A ("ask")      — every conflict goes to the user.
Mode B ("priority") — source priority decides everything: Excel/CSV > Word/PDF >
                      PowerPoint > HTML > Image.
Mode C ("hybrid")   — auto-resolve low and medium, ask on high and critical.
                      The spec's recommended default, and ours.

The user's answer may be a *file* ("the masterplan is right") or a *value* ("both are
stale, it's 80%"). §9's Mode A example asks "Which value should be used?", not "which
file do you prefer" — so the user can state the truth rather than pick the least-wrong
source. Only the second form is genuinely useful when both files are out of date.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import get_settings
from app.models.pmi import Conflict, PMIDataModel, Severity, source_priority

log = logging.getLogger("pmi.conflicts")

MODE_TO_STRATEGY = {"A": "ask", "B": "priority", "C": "hybrid"}


def resolve_conflicts(
    conflicts: list[Conflict],
    strategy: Optional[str] = None,
    user_choices: Optional[dict[str, Any]] = None,
) -> list[Conflict]:
    """Apply §9. `strategy` is "ask" | "priority" | "hybrid"; omit to use the config.

    `user_choices` is keyed by `conflict_id` (or, for older callers, by
    "<entity_key>|<field>") and each value is either:
        - a source file name, or
        - `{"value": "80"}` to supply the correct figure directly.
    """
    strategy = strategy or MODE_TO_STRATEGY.get(get_settings().conflict_mode, "hybrid")
    choices = user_choices or {}
    priority = source_priority()

    for conflict in conflicts:
        decision = choices.get(conflict.conflict_id)
        if decision is None:
            decision = choices.get(f"{conflict.entity_key}|{conflict.field}")

        # Resolution must be idempotent. This function runs again on the generation
        # pass, which carries no user choices — without this guard it would re-evaluate
        # a conflict the user already settled, and overwrite "the user selected the
        # masterplan" with "a person must decide", so the conflict report would tell
        # the reader to decide something they had already decided.
        if decision is None and conflict.is_resolved:
            continue

        # 1. The user typed the right answer.
        if isinstance(decision, dict) and "value" in decision:
            conflict.resolved_value = str(decision["value"])
            conflict.resolved_from = "user"
            conflict.resolution = "user_value"
            conflict.resolution_note = "Value supplied directly by the user."
            continue

        # 2. The user picked a source.
        if isinstance(decision, str) and decision in conflict.values:
            conflict.resolved_value = conflict.values[decision]
            conflict.resolved_from = decision
            conflict.resolution = "user"
            conflict.resolution_note = f"The user selected {decision}."
            continue

        # 3. Does this one have to go to a human?
        if _must_ask(strategy, conflict):
            conflict.resolution_note = (
                f"{conflict.severity.value.title()}-severity conflict — a person must "
                f"decide (§9 Mode {get_settings().conflict_mode})."
            )
            continue

        # 4. Source priority decides.
        winner = min(conflict.values, key=lambda f: priority.get(conflict.formats[f], 99))
        loser_formats = ", ".join(
            sorted({conflict.formats[f].value for f in conflict.values if f != winner})
        )
        conflict.resolved_value = conflict.values[winner]
        conflict.resolved_from = winner
        conflict.resolution = "source_priority"
        conflict.resolution_note = (
            f"{conflict.formats[winner].value} outranks {loser_formats} (§9)."
        )

    unresolved = sum(1 for c in conflicts if not c.is_resolved)
    log.info("resolved %d/%d conflicts (%s); %d await the user",
             len(conflicts) - unresolved, len(conflicts), strategy, unresolved)
    return conflicts


def _must_ask(strategy: str, conflict: Conflict) -> bool:
    if strategy == "priority":
        return False
    if strategy == "ask":
        return True
    return conflict.critical  # hybrid: high + critical only


def apply_resolutions(model: PMIDataModel) -> PMIDataModel:
    """Write winning values back so every generator renders one agreed number.

    Without this, a resolved conflict is only resolved on the conflicts slide — the
    body of the deck still shows whichever value happened to be extracted first.
    """
    from app.extractors.base import normalize_status, parse_date, parse_number

    for conflict in model.conflicts:
        if conflict.resolved_value is None:
            continue

        targets = _targets(model, conflict)
        for entity in targets:
            value = _coerce(
                conflict.field, conflict.resolved_value,
                normalize_status, parse_date, parse_number,
            )
            if value is None:
                continue
            try:
                setattr(entity, conflict.field, value)
            except (AttributeError, ValueError) as exc:
                log.warning("could not apply %s to %s: %s",
                            conflict.conflict_id, conflict.entity_key, exc)

    return model


def _targets(model: PMIDataModel, conflict: Conflict) -> list:
    """Every entity the conflict speaks for — matching is by the label the conflict
    was raised against."""
    collections = {
        "task": (model.tasks, "title"),
        "milestone": (model.milestones, "name"),
        "risk": (model.risks, "title"),
        "issue": (model.issues, "title"),
        "budget": (model.budget, "category"),
        "synergy": (model.synergies, "title"),
        "kpi": (model.kpis, "name"),
        "dependency": (model.dependencies, "description"),
        "decision": (model.decisions, "title"),
        "workstream": (model.workstreams, "name"),
    }
    entry = collections.get(conflict.entity_type)
    if entry is None:
        return []

    items, label_attr = entry
    key = conflict.entity_key.casefold().strip()
    return [i for i in items if str(getattr(i, label_attr, "")).casefold().strip() == key]


def _coerce(field: str, raw: str, normalize_status, parse_date, parse_number):
    if field == "status":
        return normalize_status(raw)
    if field.endswith("_date"):
        return parse_date(raw)
    number = parse_number(raw)
    if number is not None:
        # Ints where the model wants ints (probability, impact, risk_score).
        if field in ("probability", "impact", "risk_score", "delay_days"):
            return int(round(number))
        return number
    return raw


def critical_unresolved(model: PMIDataModel) -> list[Conflict]:
    """The conflicts that must be answered before a report can honestly be produced."""
    return [
        c for c in model.conflicts
        if c.severity in (Severity.HIGH, Severity.CRITICAL) and not c.is_resolved
    ]
