"""The conversation orchestrator (spec §"Conversation Orchestrator", Phase 3).

One entry point — `respond` — turns a chat message into an action and a natural
Markdown reply, replacing the fixed analyze → resolve → generate → download
sequence the frontend used to drive by hand. It decides what the message is
(a fact, a question, a request for a report, an edit, an export) and calls the
project-layer "tools" that already exist:

    ingest / rebuild        `files` + `rebuild`         (via the files endpoint)
    update knowledge         `facts.record_message`     (corrections, facts, scenarios)
    get project state        `_state` / `answer`        (questions, summaries)
    create / update draft    `drafting`                 (drafts, section regen)
    check conflicts          `conflict_impact.assess`   (the non-blocking gate)

Two rules from the spec shape the replies:

* **Natural text, not cards.** The reply is Markdown. Structured data rides in
  `actions`/`conflict_state` for the UI to render as it sees fit, but the answer a
  person reads is prose.
* **Answer first, block last.** A partial answer and a draft are always allowed;
  only a *final* export is held back when an unresolved critical conflict would be
  presented as fact.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from app.project import classify, conflict_impact
from app.project import drafts as drafts_mod
from app.project import facts as facts_mod
from app.project.drafting import DraftError
from app.project.json_repositories import Repositories, default_repositories

log = logging.getLogger("pmi.project.orchestrator")


class ChatResponse(BaseModel):
    message: str = ""
    knowledge_version: Optional[int] = None
    draft: Optional[dict] = None
    warnings: list[str] = Field(default_factory=list)
    actions: list[dict] = Field(default_factory=list)
    conflict_state: Optional[dict] = None
    intent: str = ""


_EXPORT = re.compile(r"\b(export|download|powerpoint|pptx|\.?deck as|word|docx|"
                     r"pdf|excel|xlsx|as a file|final version)\b", re.I)
_REPORT = re.compile(r"\b(report|draft|executive update|summary|prepare|write me|"
                     r"put together|create (?:a|an|the)|give me (?:a|an|the))\b", re.I)
_REVISE = re.compile(r"\b(rewrite|revise|regenerate|shorten|expand|improve|reword|"
                     r"redo|refresh|update the|change the)\b", re.I)


def respond(project_id: str, message: str, *, chat_id: Optional[str] = None,
            active_draft_id: Optional[str] = None,
            selected_text: Optional[str] = None,
            provider: Optional[str] = None, model: Optional[str] = None,
            repos: Optional[Repositories] = None) -> ChatResponse:
    repos = repos or default_repositories()
    from app.project.chat_context import save_rule, standing_rule

    rule = standing_rule(message)
    if rule:
        saved = save_rule(project_id, rule)
        return ChatResponse(
            intent="instruction",
            message=("## Project rule saved\n\n"
                     f"- {saved}\n\nThis rule now applies to every project chat "
                     "and generated report."),
        )
    knowledge = repos.knowledge.current(project_id)
    conflict_state = (conflict_impact.assess(knowledge).model_dump()
                      if knowledge is not None else None)

    if knowledge is None or knowledge.entity_count() == 0:
        return ChatResponse(
            intent="empty",
            message=("Add the project's files first — trackers, SteerCo decks, "
                     "minutes, exports, screenshots. I'll read them and tell you "
                     "what they say and where they disagree."),
            conflict_state=conflict_state)

    cls = classify.classify_message(message, provider=provider, model=model)
    intent = _route(message, cls, active_draft_id)

    if intent == "fact":
        return _handle_fact(project_id, message, chat_id, provider, model, repos,
                            conflict_state)
    if intent == "export":
        return _handle_export(project_id, active_draft_id, message, repos, knowledge,
                              conflict_state)
    if intent == "revise":
        return _handle_revise(project_id, active_draft_id, message, chat_id, repos,
                             conflict_state)
    if intent == "create_report":
        return _handle_create(project_id, message, chat_id, repos, knowledge,
                             conflict_state)
    return _handle_question(project_id, message, knowledge, conflict_state)


# ------------------------------------------------------------------ routing
def _route(message: str, cls, active_draft_id: Optional[str]) -> str:
    if cls.is_knowledge:                      # new_fact/correction/decision/assumption
        return "fact"
    if _EXPORT.search(message):
        return "export"
    if active_draft_id and _REVISE.search(message):
        return "revise"
    if _REPORT.search(message):
        return "create_report"
    return "question"


# ------------------------------------------------------------------ handlers
def _handle_fact(project_id, message, chat_id, provider, model, repos,
                 conflict_state) -> ChatResponse:
    result = facts_mod.record_message(project_id, message, chat_id=chat_id,
                                      provider=provider, model=model, repos=repos)
    actions: list[dict] = []
    warnings: list[str] = []

    if result.knowledge_changed:
        # New information may have staled existing drafts — flag, never rewrite.
        for draft in drafts_mod.mark_stale_if_affected(project_id, repos=repos):
            actions.append({"type": "draft_stale", "draft_id": draft.draft_id,
                            "status": draft.status})
            warnings.append(
                f"Draft “{draft.title}” may be out of date (now {draft.status}).")

    # A fresh assessment: a correction can resolve or introduce a conflict.
    knowledge = repos.knowledge.current(project_id)
    return ChatResponse(
        intent="fact", message=result.message,
        knowledge_version=result.version,
        actions=actions, warnings=warnings,
        conflict_state=(conflict_impact.assess(knowledge).model_dump()
                        if knowledge else conflict_state))


def _handle_create(project_id, message, chat_id, repos, knowledge,
                   conflict_state) -> ChatResponse:
    from app.project import drafting

    audience = _audience_hint(message)
    try:
        # The message *is* the brief. It used to be read for an audience hint and
        # then discarded, so every draft for a given audience was the same
        # document whatever the user had asked for.
        draft = drafting.create_draft(project_id, audience=audience,
                                      chat_id=chat_id, request_text=message,
                                      repos=repos)
    except DraftError as exc:
        return ChatResponse(intent="create_report", message=str(exc),
                            conflict_state=conflict_state)

    state = conflict_impact.assess(knowledge)
    body = [f"I've drafted **{draft.title}** — you can read and edit it directly, "
            f"and I'll keep it in step with the project as new information arrives."]
    body.extend(_planning_notes(draft))
    if state.blocking_conflicts:
        body.append("")
        body.append(state.explain())

    return ChatResponse(
        intent="create_report", message="\n".join(body),
        knowledge_version=knowledge.version,
        draft={"draft_id": draft.draft_id, "updated": True, "status": draft.status},
        actions=[{"type": "open_draft", "draft_id": draft.draft_id}],
        conflict_state=state.model_dump())


def _handle_revise(project_id, draft_id, message, chat_id, repos,
                   conflict_state) -> ChatResponse:
    from app.project import drafting

    draft = repos.drafts.get(project_id, draft_id)
    if draft is None:
        return ChatResponse(intent="revise",
                            message="I couldn't find that draft to revise.",
                            conflict_state=conflict_state)

    section = _match_section(draft, message)
    if section is None:
        names = ", ".join(f"“{s.heading or s.section_id}”" for s in draft.sections[:8])
        return ChatResponse(
            intent="revise",
            message=("Which section should I redo? This draft has: " + names + "."),
            draft={"draft_id": draft_id, "updated": False, "status": draft.status},
            conflict_state=conflict_state)

    try:
        updated = drafting.regenerate_section(project_id, draft_id,
                                              section.section_id, chat_id=chat_id,
                                              repos=repos)
    except DraftError as exc:
        return ChatResponse(intent="revise", message=str(exc),
                            conflict_state=conflict_state)

    return ChatResponse(
        intent="revise",
        message=f"Regenerated **{section.heading or section.section_id}** from the "
                f"current project data. The rest of the draft is unchanged.",
        draft={"draft_id": draft_id, "updated": True, "status": updated.status},
        actions=[{"type": "open_draft", "draft_id": draft_id}],
        conflict_state=conflict_state)


def _handle_export(project_id, draft_id, message, repos, knowledge,
                   conflict_state) -> ChatResponse:
    from app.project import exporting

    state = conflict_impact.assess(knowledge)
    if not draft_id:
        return ChatResponse(
            intent="export",
            message="Which draft should I export? Create or open one first.",
            conflict_state=state.model_dump())

    if not state.can_export_final:
        return ChatResponse(
            intent="export",
            message=("I can give you a working copy, but I'm holding back the "
                     "final approved export until the critical figures are agreed:\n\n"
                     + state.explain()),
            actions=[{"type": "export_blocked", "draft_id": draft_id,
                      "blocking": state.blocking_conflicts}],
            conflict_state=state.model_dump())

    fmt = _export_format(message)
    if fmt is None:
        return ChatResponse(
            intent="export",
            message="Ready to export the current saved draft. Which format — "
                    "PowerPoint, Word, PDF, or Excel?",
            actions=[{"type": "export_ready", "draft_id": draft_id}],
            conflict_state=state.model_dump())

    try:
        path = exporting.export_draft(project_id, draft_id, fmt, repos=repos)
    except exporting.ExportError as exc:
        return ChatResponse(intent="export", message=str(exc),
                            conflict_state=state.model_dump())

    return ChatResponse(
        intent="export",
        message=f"Exported the current saved draft as **{fmt}**: `{path.name}`. "
                f"It reflects exactly what's in the draft, including your edits.",
        draft={"draft_id": draft_id, "updated": False, "status": knowledge.version},
        actions=[{"type": "download", "draft_id": draft_id, "format": fmt,
                  "file": path.name}],
        conflict_state=state.model_dump())


def _handle_question(project_id, message, knowledge, conflict_state) -> ChatResponse:
    return ChatResponse(
        intent="question",
        message=answer(project_id, message, knowledge),
        knowledge_version=knowledge.version,
        conflict_state=conflict_state)


# ------------------------------------------------------------- state / answer
def answer(project_id: str, message: str, knowledge) -> str:
    """A natural-language answer from project knowledge — prose, never cards.

    Phase 3 answers the common "how are we doing / what are the concerns" question
    from the deterministic model; a richer NL Q&A is a later refinement, but the
    shape — Markdown, with sources available on request — is set here.
    """
    from app.report import messages

    model = knowledge.data_model
    lines = [messages.status_message(model), ""]

    criticals = [r for r in model.critical_risks() if r.status.is_open][:5]
    overdue = model.overdue_tasks()
    unresolved = model.unresolved_conflicts()
    decisions = [d for d in model.decisions if d.status.is_open]

    concerns: list[str] = []
    if criticals:
        concerns.append(
            f"**{len(criticals)} open critical risk(s)** — most pressing: "
            + "; ".join(r.title for r in criticals[:3]))
    if overdue:
        concerns.append(f"**{len(overdue)} overdue activity(ies)**")
    if decisions:
        concerns.append(f"**{len(decisions)} decision(s)** awaiting sign-off")
    if unresolved:
        concerns.append(
            f"**{len(unresolved)} unresolved source conflict(s)** — figures not yet "
            f"agreed (I can list them and you decide which source to trust)")

    if concerns:
        lines.append("Main things needing attention:")
        lines += [f"- {c}" for c in concerns]
    else:
        lines.append("Nothing critical is outstanding right now.")

    lines += ["", f"<sub>From {len(model.source_files)} source file(s), project "
              f"knowledge v{knowledge.version}. Ask “show sources” for citations.</sub>"]
    return "\n".join(lines)


# ------------------------------------------------------------------ helpers
def _audience_hint(message: str) -> Optional[str]:
    lowered = message.lower()
    if re.search(r"\b(steerco|steering|executive|board|exec)\b", lowered):
        return "executive"
    if re.search(r"\b(imo|pmo|operational)\b", lowered):
        return "pmo"
    if re.search(r"\b(finance|financial|budget|synerg)\b", lowered):
        return "finance"
    if re.search(r"\b(workstream|team)\b", lowered):
        return "workstream"
    return None


def _export_format(message: str) -> Optional[str]:
    lowered = message.lower()
    for pattern, fmt in (
        (r"powerpoint|pptx|deck|slides|presentation", "powerpoint"),
        (r"\bword\b|docx|document", "word"),
        (r"\bpdf\b", "pdf"),
        (r"excel|xlsx|workbook|spreadsheet", "excel"),
        (r"\bhtml\b|web ?page", "html"),
        (r"markdown|\.md\b", "markdown"),
    ):
        if re.search(pattern, lowered):
            return fmt
    return None


def _match_section(draft, message: str):
    """The draft section a revise instruction refers to, by heading/id word overlap."""
    words = set(re.findall(r"[a-z0-9]+", message.lower()))
    best, best_score = None, 0
    for section in draft.sections:
        label = f"{section.heading} {section.section_id}".lower()
        score = len(words & set(re.findall(r"[a-z0-9]+", label)))
        if score > best_score:
            best, best_score = section, score
    return best if best_score >= 1 else None


def _planning_notes(draft) -> list[str]:
    """Anything about *how* the draft was planned that the user should know.

    Chiefly whether a model shaped it. A draft assembled from the deterministic
    fallback reads like a considered document and is not one, and the chat reply
    is where a user is actually looking.
    """
    from app.deliverable import store

    notes: list[str] = []
    if not draft.deliverable_id:
        return notes
    deliverable = store.load(project_id=draft.project_id,
                             version=draft.deliverable_version)
    if deliverable is None:
        return notes

    if deliverable.planned_by == "fallback":
        notes.append("")
        notes.append("Note: no language model was available, so the sections "
                     "follow your request and the available evidence rather "
                     "than a reasoned argument. Every figure in it is validated.")
    uncovered = [topic for topic, sections in deliverable.covered_sections.items()
                 if not sections]
    if uncovered:
        notes.append("")
        notes.append("I could not cover: " + ", ".join(uncovered[:4])
                     + ". The draft says so where each belongs.")
    return notes
