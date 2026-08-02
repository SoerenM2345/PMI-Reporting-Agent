"""Make a filed chat part of project context, not merely part of the sidebar.

The transcript remains an audit/retrieval source.  Only durable, typed chat
knowledge (uploaded files, confirmed values, conflict choices and report
structure) is promoted into canonical project knowledge.  This preserves the
project layer's core rule that an ordinary question is not a fact.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from app.agent import knowledge as session_knowledge
from app.project.models import AuditEvent, ConfirmedFact, UserDecision
from app.storage import chat_store, json_store


_RULE = re.compile(
    r"^\s*(?:from now on[, ]+|standing (?:rule|instruction)[: ]+)?"
    r"(?P<rule>(?:always|never)\b.+)$", re.I | re.S)


def standing_rule(text: str) -> Optional[str]:
    """A durable agent rule, normalized so the context builder recognizes it."""
    match = _RULE.match((text or "").strip())
    if not match:
        return None
    rule = " ".join(match.group("rule").split()).strip(" .")
    if rule:
        rule = rule[0].upper() + rule[1:]
    return rule[:1000] if rule else None


def save_rule(project_id: str, text: str) -> str:
    """Append a unique standing rule to the project's explicit context."""
    rule = standing_rule(text) or " ".join((text or "").split()).strip(" .")
    if not rule:
        raise ValueError("A project rule cannot be empty.")
    if not re.match(r"^(?:always|never)\b", rule, re.I):
        rule = "Always " + rule[0].lower() + rule[1:]
    project = chat_store.get_project(project_id)
    if project is None:
        raise ValueError("No such project.")
    lines = [line.strip() for line in (project.knowledge or "").splitlines()
             if line.strip()]
    if rule.casefold() not in {line.casefold() for line in lines}:
        lines.append(rule)
        chat_store.update_project(project_id, knowledge="\n".join(lines))
    return rule


def attach(chat_id: str, project_id: str, *, repos=None):
    """Import one existing chat's durable context and return project knowledge."""
    from app.project import files as project_files
    from app.project.json_repositories import default_repositories
    from app.project.rebuild import rebuild

    repos = repos or default_repositories()
    chat = chat_store.get_chat(chat_id)
    if chat is None or chat_store.get_project(project_id) is None:
        raise ValueError("The chat or project does not exist.")

    for path in sorted(json_store.uploads_dir(chat.session_id).iterdir()):
        if path.is_file():
            project_files.ingest_file(project_id, path, repos=repos)

    kb = session_knowledge.load(chat.session_id)
    current = repos.knowledge.current(project_id)
    known_decisions = {d.decision_id for d in current.user_decisions} if current else set()
    known_facts = {f.fact_id for f in current.confirmed_user_facts} if current else set()
    decisions: list[UserDecision] = []
    facts: list[ConfirmedFact] = []

    for index, value in enumerate(kb.user_values):
        uid = f"chat_{chat_id}_value_{index}"
        if uid not in known_decisions:
            decisions.append(UserDecision(
                decision_id=uid, kind="confirmed_value",
                detail={"entity_type": value.entity_type,
                        "entity_label": value.label, "field": value.field,
                        "raw": value.raw or str(value.value),
                        "value": value.value, "old_value": value.old_value,
                        "source": f"chat:{chat_id}"},
            ))
        if uid not in known_facts:
            facts.append(ConfirmedFact(
                fact_id=uid,
                text=(f"{value.label or value.entity_type} "
                      f"{value.field.replace('_', ' ')} = "
                      f"{value.raw or value.value}"),
                field=value.field, value=value.value, source_id=f"chat:{chat_id}",
            ))

    analysis = json_store.load_analysis(chat.session_id)
    if analysis is not None:
        for conflict in analysis.data_model.conflicts:
            if not conflict.is_resolved or conflict.resolution not in ("user", "user_value"):
                continue
            uid = f"chat_{chat_id}_{conflict.conflict_id}"
            if uid in known_decisions:
                continue
            choice = ({"value": conflict.resolved_value}
                      if conflict.resolution == "user_value"
                      else conflict.resolved_from)
            decisions.append(UserDecision(
                decision_id=uid, kind="conflict_resolution",
                detail={"conflict_id": conflict.conflict_id, "choice": choice,
                        "value": conflict.resolved_value,
                        "source": conflict.resolved_from},
            ))

    structure = []
    if isinstance(kb.structure, dict):
        structure = [str(item.get("title", "")).strip()
                     for item in kb.structure.get("sections", [])
                     if isinstance(item, dict) and str(item.get("title", "")).strip()]

    saved = rebuild(
        project_id, repos=repos, trigger=f"attach_chat:{chat_id}",
        add_decisions=decisions, add_facts=facts,
        set_project_fields={k: str(v) for k, v in kb.project_fields.items()},
        set_requested_structure=structure or None,
    )

    existing_audit = {event.event_id for event in repos.audit.list(project_id)}
    for message in chat_store.list_messages(chat_id):
        event_id = f"chat_{message.message_id}"
        if event_id in existing_audit:
            continue
        content = message.content.get("text") or message.content.get("content") or ""
        repos.audit.append(AuditEvent(
            event_id=event_id, project_id=project_id, chat_id=chat_id,
            type="user_message" if message.role == "user" else "generated_draft",
            content=str(content),
            metadata={"imported_from_chat": True, "original_role": message.role},
        ))
        if message.role == "user":
            rule = standing_rule(str(content))
            if rule:
                save_rule(project_id, rule)

    chat_store.set_chat_project(chat_id, project_id)
    return saved
