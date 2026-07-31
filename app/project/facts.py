"""Turn a chat message into the right kind of project knowledge — or none.

This is where corrections #1–#5 meet: a message is classified, always written to
the audit trail, and only *then*, if it is fact-bearing, allowed to change
knowledge — gated by its authority and scope.

    instruction / question        → audit only, knowledge untouched
    assumption                    → assumptions store (never a fact)
    scenario-scoped               → recorded, but canonical entities untouched
    proposed / uncertain value    → open question, kept *beside* the current value
    confirmed correction (value)  → superseded via the deterministic pipeline,
                                     old value preserved and re-applied on rebuild
    confirmed fact (no value)      → confirmed-facts store

Every knowledge change goes through `rebuild`, which folds the addition into a
single new version atomically. A confirmed value correction is recorded as a
`UserDecision`, so `rebuild` replays it on top of every future re-read — the files
never win back a value the user corrected.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from pydantic import BaseModel

from app.agent import nl_updates
from app.project import classify
from app.project import rebuild as rebuild_mod
from app.project.json_repositories import Repositories, default_repositories
from app.project.models import (
    Assumption,
    AuditEvent,
    ConfirmedFact,
    KnowledgeScope,
    KnowledgeSourceType,
    OpenQuestion,
    SourceEvent,
    UserDecision,
    UserInputAuthority,
    _now,
)

log = logging.getLogger("pmi.project.facts")

#: contribution → the knowledge source type it is logged as.
_SOURCE_TYPE: dict[str, KnowledgeSourceType] = {
    "correction": "user_correction",
    "new_fact": "manual_entry",
    "decision": "confirmed_user_fact",
}


class MessageResult(BaseModel):
    """What `record_message` did, for the caller to turn into a reply."""

    contribution: str
    authority: UserInputAuthority
    scope: KnowledgeScope
    #: Did the knowledge base change at all (including metadata-only additions)?
    knowledge_changed: bool = False
    #: Did a canonical entity/fact value actually change (a supersession)?
    applied: bool = False
    message: str = ""
    version: Optional[int] = None
    source_id: Optional[str] = None
    superseded_old_value: Optional[str] = None


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def record_message(project_id: str, text: str, *, chat_id: Optional[str] = None,
                   scope_override: Optional[KnowledgeScope] = None,
                   provider: Optional[str] = None, model: Optional[str] = None,
                   repos: Optional[Repositories] = None) -> MessageResult:
    """Classify a message, always audit it, and update knowledge only if warranted."""
    repos = repos or default_repositories()
    cls = classify.classify_message(text, provider=provider, model=model)
    scope: KnowledgeScope = scope_override or cls.scope

    # Correction #1: every message is recorded in the audit trail, whatever it is.
    repos.audit.append(AuditEvent(
        event_id=_uid("aud"), project_id=project_id, chat_id=chat_id,
        type="user_message", content=text, contribution=cls.contribution,
    ))

    base = MessageResult(contribution=cls.contribution, authority=cls.authority,
                         scope=scope)

    if not cls.is_knowledge:
        base.message = "Noted — no project fact to record."
        return base

    # --- scenario: recorded, but canonical knowledge is never modified (corr #4)
    if scope == "scenario":
        fact = ConfirmedFact(fact_id=_uid("fact"), text=text,
                             authority=cls.authority, scope="scenario",
                             source_id=_log_source(repos, project_id, chat_id,
                                                   cls, "manual_entry", text,
                                                   scope))
        saved = rebuild_mod.rebuild(project_id, repos=repos,
                                    trigger="scenario", add_facts=[fact])
        base.knowledge_changed = True
        base.version = saved.version
        base.source_id = fact.source_id
        base.message = "Recorded as a scenario — canonical project knowledge is unchanged."
        return base

    # --- assumption: its own store, never conflated with a fact (correction #3)
    if cls.contribution == "assumption":
        assumption = Assumption(assumption_id=_uid("asm"), text=text, scope=scope)
        saved = rebuild_mod.rebuild(project_id, repos=repos,
                                    trigger="assumption",
                                    add_assumptions=[assumption])
        base.knowledge_changed = True
        base.version = saved.version
        base.message = "Recorded as an assumption (not a confirmed fact)."
        return base

    # --- proposed / uncertain: flagged, kept beside the current value (corr #5)
    if cls.authority in ("proposed", "uncertain"):
        return _record_open_question(project_id, text, chat_id, cls, base, repos)

    # --- confirmed: apply as a supersession where we can, else store as a fact
    return _record_confirmed(project_id, text, chat_id, cls, base, repos)


# ------------------------------------------------------------------ branches
def _record_open_question(project_id, text, chat_id, cls, base,
                          repos) -> MessageResult:
    current = repos.knowledge.current(project_id)
    update = nl_updates.parse(text)
    current_value = None
    field = None
    if update is not None and current is not None:
        issue = nl_updates.locate(current.data_model, update.target, update.value)
        if issue is not None:
            field = issue.field
            current_value = _entity_value(current, issue.entity_type,
                                          issue.entity_id, issue.field)

    source_id = _log_source(repos, project_id, chat_id, cls, "user_correction",
                            text, base.scope)
    question = OpenQuestion(
        question_id=_uid("oq"), text=text, field=field,
        proposed_value=(update.value if update else None),
        current_value=current_value, authority=cls.authority, source_id=source_id,
    )
    saved = rebuild_mod.rebuild(project_id, repos=repos, trigger="open_question",
                               add_questions=[question])
    base.knowledge_changed = True
    base.version = saved.version
    base.source_id = source_id
    base.message = ("Noted as a proposed value and flagged for review — the "
                    "current value stands until you confirm.")
    return base


def _record_confirmed(project_id, text, chat_id, cls, base,
                      repos) -> MessageResult:
    update = nl_updates.parse(text)
    source_type = _SOURCE_TYPE.get(cls.contribution, "confirmed_user_fact")

    # A confirmed value-shaped correction → supersede through the pipeline.
    if update is not None and cls.contribution in ("correction", "new_fact"):
        field = nl_updates.match_project_field(update.target)
        if field is not None:
            return _apply_project_field(project_id, text, chat_id, cls, base,
                                        repos, field, update.value, source_type)
        return _apply_entity_correction(project_id, text, chat_id, cls, base,
                                        repos, update, source_type)

    # A confirmed fact/decision with no directly-writable value → store as a fact.
    source_id = _log_source(repos, project_id, chat_id, cls, source_type, text,
                            base.scope)
    fact = ConfirmedFact(fact_id=_uid("fact"), text=text, authority="confirmed",
                         scope=base.scope, source_id=source_id)
    saved = rebuild_mod.rebuild(project_id, repos=repos, trigger="confirmed_fact",
                               add_facts=[fact])
    base.knowledge_changed = True
    base.version = saved.version
    base.source_id = source_id
    base.message = "Recorded as a confirmed project fact."
    return base


def _apply_project_field(project_id, text, chat_id, cls, base, repos,
                         field, raw_value, source_type) -> MessageResult:
    source_id = _log_source(repos, project_id, chat_id, cls, source_type, text,
                            base.scope, metadata={"project_field": field})
    fact = ConfirmedFact(fact_id=_uid("fact"), text=text, field=field,
                         value=raw_value, source_id=source_id)
    saved = rebuild_mod.rebuild(project_id, repos=repos, trigger="correction",
                               set_project_fields={field: raw_value},
                               add_facts=[fact])
    base.knowledge_changed = True
    base.applied = True
    base.version = saved.version
    base.source_id = source_id
    base.message = f"Set the {field.replace('_', ' ')} — the report re-derives from it."
    return base


def _apply_entity_correction(project_id, text, chat_id, cls, base, repos,
                             update, source_type) -> MessageResult:
    current = repos.knowledge.current(project_id)
    if current is None:
        base.message = "Nothing has been read yet — upload the files first."
        return base

    issue = nl_updates.locate(current.data_model, update.target, update.value)
    if issue is None:
        # A confirmed statement we cannot place is still knowledge — keep it as a
        # fact rather than dropping it, and say we could not map it to a field.
        source_id = _log_source(repos, project_id, chat_id, cls, source_type,
                                text, base.scope)
        fact = ConfirmedFact(fact_id=_uid("fact"), text=text, source_id=source_id)
        saved = rebuild_mod.rebuild(project_id, repos=repos,
                                   trigger="confirmed_fact", add_facts=[fact])
        base.knowledge_changed = True
        base.version = saved.version
        base.source_id = source_id
        base.message = ("Recorded as a confirmed fact — I couldn't match it to a "
                        "specific field to update.")
        return base

    old_value = _entity_value(current, issue.entity_type, issue.entity_id,
                              issue.field)

    # Normalise a spelled-out number ("3.5 million") the same way the session path
    # does, so the stored raw re-coerces to the right magnitude on every rebuild.
    raw = update.value
    if nl_updates.is_number(raw) and not nl_updates.is_date(raw):
        expanded = nl_updates.expand_number(raw)
        if expanded is not None:
            raw = f"{expanded:g}"

    source_id = _log_source(
        repos, project_id, chat_id, cls, source_type, text, base.scope,
        metadata={"entity_type": issue.entity_type,
                  "entity_label": issue.entity_label, "field": issue.field,
                  "old_value": _as_text(old_value)})
    decision = UserDecision(
        decision_id=_uid("dec"), kind="confirmed_value",
        detail={"entity_type": issue.entity_type,
                "entity_label": issue.entity_label, "field": issue.field,
                "raw": raw, "old_value": _as_text(old_value),
                "source_id": source_id})
    fact = ConfirmedFact(fact_id=_uid("fact"), text=text, field=issue.field,
                         value=raw, source_id=source_id)

    saved = rebuild_mod.rebuild(project_id, repos=repos, trigger="correction",
                               add_decisions=[decision], add_facts=[fact])
    new_value = _entity_value(saved, issue.entity_type, None, issue.field,
                              label=issue.entity_label)
    base.knowledge_changed = True
    base.applied = True
    base.version = saved.version
    base.source_id = source_id
    base.superseded_old_value = _as_text(old_value)
    base.message = (
        f"Updated {issue.entity_label or issue.entity_type} "
        f"{(issue.field or '').replace('_', ' ')} to {_as_text(new_value)} "
        f"(was {_as_text(old_value)}); recorded as coming from you and kept on "
        f"every re-read. The previous value stays traceable.")
    return base


# ------------------------------------------------------------------ helpers
def _log_source(repos, project_id, chat_id, cls, source_type, text, scope,
                metadata=None) -> str:
    source_id = _uid("src")
    repos.sources.append(SourceEvent(
        source_id=source_id, project_id=project_id, chat_id=chat_id,
        type=source_type, content=text, authority=cls.authority, scope=scope,
        contribution=cls.contribution, metadata=metadata or {}))
    return source_id


def _entity_value(knowledge, entity_type, entity_id, field, *, label=None):
    """Read one entity's field value from a knowledge snapshot, by id or label."""
    from app.agent.nl_updates import LABELS

    entry = LABELS.get(entity_type or "")
    if entry is None or not field:
        return None
    coll, id_attr, label_attr = entry
    for entity in getattr(knowledge.data_model, coll, []) or []:
        if entity_id is not None and getattr(entity, id_attr, None) == entity_id:
            return getattr(entity, field, None)
        if label is not None and str(getattr(entity, label_attr, "")) == label:
            return getattr(entity, field, None)
    return None


def _as_text(value) -> str:
    if value is None:
        return "Not Reported"
    from datetime import date
    if isinstance(value, date):
        return f"{value:%d-%m-%Y}"
    return str(value)
