"""Turning a chat message into an action, and an action into replies.

The wizard asked for things in a fixed order. A conversation cannot: the user
may upload files and say nothing, ask for a deck before setting a reporting
date, or say "make it shorter" three turns after the report exists. So each turn
is classified, acted on, and answered — and where information is genuinely
missing the agent *asks* rather than guessing.

That last part matters more than it looks. §4 requires the audience to be asked
for when it cannot be inferred, because the audience reshapes the whole report;
a chat that guesses in order to sound fluent would quietly undo a deliberate
design decision. Fluency is not worth a document written for nobody.

Classification uses the LLM when one is configured and falls back to keywords
otherwise — the same discipline as the rest of the pipeline, and what keeps the
whole conversational path testable without an API key.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.llm import LLMError, get_client
from app.models.pmi import Audience
from app.report import store as report_store
from app.report.render.markdown import render_markdown
from app.storage import json_store
from app.storage.chat_store import Chat, Kind

log = logging.getLogger("pmi.conversation")

Intent = Literal[
    "request_report", "set_audience", "revise_content", "render",
    "resolve_conflict", "question", "unclear",
]

FORMATS = {
    "powerpoint": ("powerpoint", "deck", "slides", "pptx", "presentation"),
    "word": ("word", "docx", "document"),
    "pdf": ("pdf",),
    "html": ("html", "web page", "webpage"),
    "excel": ("excel", "xlsx", "workbook", "spreadsheet", "dashboard"),
}


class Reply(BaseModel):
    kind: Kind = "text"
    content: dict = Field(default_factory=dict)


class TurnIntent(BaseModel):
    """What the user's message is asking for."""

    intent: Intent = Field(description="What the user wants to happen next.")
    audience: Optional[Audience] = Field(
        default=None,
        description="Only when the message clearly names one. Never guess.",
    )
    output_format: Optional[str] = Field(
        default=None, description="powerpoint | word | pdf | html | excel"
    )


SYSTEM = """You classify a message in a Post-Merger Integration reporting chat.

Return the user's intent. Do not infer an audience unless the message clearly
names one — the audience changes the whole report, and asking is correct when it
is not stated."""


#: Intents that cannot be answered without having read the files.
NEEDS_ANALYSIS = frozenset(
    {"render", "revise_content", "request_report", "set_audience"}
)


def respond(chat: Chat, text: str) -> list[Reply]:
    """The replies for one user turn.

    Reading the files is a **precondition of routing**, not something each
    handler remembers to do. It used to live inside `_plan`, which meant the
    answer depended on which verb the user happened to type: "give me a SteerCo
    deck" was classified `request_report` and worked, while "generate a status
    deck" was classified `render` and hit a handler that had no idea how to
    read anything, replying "I haven't read the files yet" — advice the user
    could not act on, since there is no Analyse button to press.

    Hoisting it here fixes the class of bug rather than the instance: a new
    intent added to `NEEDS_ANALYSIS` cannot reintroduce it.
    """
    uploaded = _uploaded_files(chat)
    if not uploaded:
        return [_text(
            "Upload the week's files first — trackers, SteerCo decks, minutes, "
            "exports, or screenshots of dashboards. I'll read them and tell you "
            "what they say and where they disagree."
        )]

    turn = _classify(text, chat)
    analysis = json_store.load_analysis(chat.session_id)
    preamble: list[Reply] = []

    if turn.intent in NEEDS_ANALYSIS and not _analysis_covers(analysis, uploaded):
        prior = analysis
        added = _added_files(prior, uploaded) if prior else []

        analysis, blocked = _ensure_analysis(chat, text, turn, prior)
        if blocked:
            return blocked

        # Only worth saying when there was something to add *to*. On a first
        # read, every file is "new" and announcing that is noise.
        if prior is not None and added:
            preamble.append(_text(
                f"Re-read everything including the {len(added)} new file(s): "
                + ", ".join(added[:5])
                + ("…" if len(added) > 5 else "") + "."
            ))
        preamble.extend(_found(analysis))

    if turn.intent == "render":
        # "Generate a deck" before anything has been drafted means *draft it* —
        # the point of this tool is that you read the report before it is built,
        # and the preview carries a format button for the next step.
        if report_store.load(chat.session_id) is None:
            return preamble + _plan(chat, analysis, turn, text)
        return preamble + _render(chat, analysis, turn.output_format)

    if turn.intent == "revise_content":
        return preamble + _revise(chat, analysis, text)
    if turn.intent in ("request_report", "set_audience"):
        return preamble + _plan(chat, analysis, turn, text)
    if turn.intent == "resolve_conflict":
        return [_text(
            "Pick the value you trust on the conflict card above, or type the "
            "correct figure — both sources may be out of date."
        )]

    return _help(analysis)


def _uploaded_files(chat: Chat) -> list[str]:
    """The file names currently in the session, however `meta` stored them."""
    meta = json_store.load_meta(chat.session_id) or {}
    names = [
        f if isinstance(f, str) else (f.get("name") or "")
        for f in meta.get("files", [])
    ]
    return sorted(name for name in names if name)


def _analysis_covers(analysis, uploaded: list[str]) -> bool:
    """Was this analysis produced from exactly the files that are here now?

    The bug this exists to stop: a user uploads five files, gets a report, then
    uploads six more and asks to include them. Nothing re-read anything —
    `respond` only analysed when there was *no* analysis at all — so the report
    stayed silently built from the original five while appearing to be current.
    A stale report that looks fresh is the worst output this system can produce.
    """
    if analysis is None:
        return False
    return sorted(analysis.data_model.source_files) == uploaded


def _added_files(analysis, uploaded: list[str]) -> list[str]:
    known = set(analysis.data_model.source_files) if analysis else set()
    return [name for name in uploaded if name not in known]


def _ensure_analysis(chat: Chat, text: str, turn: TurnIntent, prior=None):
    """`(analysis, blocking_replies)`. Non-empty replies mean stop and answer.

    `prior` is the analysis being replaced, when files were added to a session
    that already had one. What the user previously told us survives the re-read:
    asking "who is this for?" again — after they answered it two turns ago and
    only uploaded a file since — is the agent forgetting, not the agent being
    careful. §4 requires asking when the audience *cannot be inferred*; here it
    is already known.
    """
    audience = turn.audience or (prior.audience if prior else None)
    request_text = (prior.request_text if prior and prior.request_text else text)

    analysis, needs_audience = _analyse(chat, request_text, audience)

    if needs_audience:
        # §4: extraction stopped because the audience could not be inferred.
        return None, [Reply(kind="audience_choice", content={
            "text": "Before I read these — who is the report for? It changes "
                    "what goes in it.",
            "options": [a.value for a in Audience],
        })]

    if analysis is None:
        return None, [_text(
            "I could not read those files. Check the formats and try uploading "
            "again."
        )]

    return analysis, []


# ------------------------------------------------------------------ actions
def _analyse(chat: Chat, request_text: str, audience: Optional[Audience]):
    """Read the files. In a chat there is no "Analyse" button to press.

    The wizard made this an explicit step; a conversation cannot, because the
    user has already said what they want and being told to go and do something
    else is a dead end. So asking for a report is what triggers extraction.
    """
    from app.agent.graph import run_analysis
    from app.storage.json_store import SessionAnalysis

    meta = json_store.load_meta(chat.session_id) or {}
    paths = [
        str(json_store.uploads_dir(chat.session_id) / name)
        for name in (f if isinstance(f, str) else f.get("name")
                     for f in meta.get("files", []))
        if name
    ]

    result = run_analysis({
        "session_id": chat.session_id,
        "file_paths": paths,
        "request_text": request_text,
        "audience": audience,
        "project": json_store.load_project(chat.session_id),
        "conflict_strategy": None,
    })

    if result.get("needs_audience"):
        return None, True

    analysis = SessionAnalysis(
        session_id=chat.session_id,
        request_text=request_text,
        output_type=result.get("output_type", "powerpoint"),
        topic=result.get("topic", "status"),
        audience=result.get("audience"),
        data_model=result["data_model"],
        quality_report=result.get("quality_report"),
        errors=result.get("errors", []),
        warnings=result.get("warnings", []),
    )
    json_store.save_analysis(analysis)
    return analysis, False


def _found(analysis) -> list[Reply]:
    """What the files actually said, before any report is drafted.

    §5.6: "low-confidence findings should be shown to the user for review." A
    sentence saying *three* findings need checking is not that — the user cannot
    act on a count. They are listed individually, with what was read and how
    confident the reading was, because the only person who can confirm a figure
    scraped off a whiteboard photo is the one who was in the room.
    """
    model = analysis.data_model
    unresolved = model.unresolved_conflicts()
    low = model.low_confidence_items()
    score = getattr(analysis.quality_report, "score", None)

    parts = [f"Read {len(model.source_files)} file(s): {model.entity_count()} items."]
    if unresolved:
        parts.append(f"{len(unresolved)} source conflict(s) still open.")
    if score is not None:
        parts.append(f"Data quality {score:.0f}/100.")

    replies = [_text(" ".join(parts))]

    from app.agent.corrections import fillable

    gaps = fillable(model.validation_issues)
    if gaps:
        # §8.2. These are the findings the user is the *only* one who can
        # answer — nothing in the files disagrees, the value was never written
        # down. Counting them and moving on left the one actionable category
        # with no way to act.
        replies.append(Reply(kind="issues", content={
            "text": (f"{len(gaps)} gap(s) I could not fill from the files. "
                     f"You can supply the missing values here."),
            "issues": [
                {
                    "issue_id": issue.issue_id,
                    "entity_type": issue.entity_type,
                    "entity_label": issue.entity_label or issue.entity_id,
                    "field": issue.field,
                    "message": issue.message,
                    "severity": issue.severity.value,
                }
                for issue in gaps[:12]
            ],
            "total": len(gaps),
            "session_id": analysis.session_id,
        }))

    if low:
        replies.append(Reply(kind="low_confidence", content={
            "text": (f"{len(low)} finding(s) were read from an image or scan. "
                     f"They are in the report — check them before you rely on them."),
            "items": [
                {"type": kind, "label": label, "confidence": confidence}
                for kind, label, confidence in
                sorted(low, key=lambda item: item[2])
            ],
        }))

    return replies


def _plan(chat: Chat, analysis, turn: TurnIntent, text: str) -> list[Reply]:
    """Draft the report. `respond` guarantees `analysis` is not None."""
    audience = turn.audience or analysis.audience
    if audience is None:
        # §4: ask, do not guess.
        return [Reply(kind="audience_choice", content={
            "text": "Who is this report for? It changes what goes in it — a "
                    "Steering Committee wants decisions, an IMO wants overdue "
                    "work.",
            "options": [a.value for a in Audience],
        })]

    blocking = [c for c in analysis.data_model.unresolved_conflicts() if c.critical]
    replies: list[Reply] = []
    if blocking:
        # The 409 gate, in conversational form. Never quietly skipped.
        replies.append(Reply(kind="conflict", content={
            "text": f"{len(blocking)} critical conflict(s) need a decision "
                    f"before I can stand behind these figures.",
            "conflicts": [c.model_dump(mode="json") for c in blocking],
        }))

    from app.llm import tasks
    from app.report.planner import plan as plan_report

    # The graph path calls this in `plan_content`; the chat path did not, so
    # every chat-drafted report had an empty executive summary — and then blamed
    # the model for it. `write_summary` falls back to template prose with no key
    # rather than returning nothing, so this is populated either way.
    bullets = tasks.write_summary(analysis.data_model, audience,
                                  analysis.request_text or text)

    content = plan_report(
        analysis.data_model, audience,
        session_id=chat.session_id, topic=analysis.topic,
        bullets=bullets,
        quality=analysis.quality_report,
        fingerprint=report_store.fingerprint(analysis.data_model,
                                             analysis.quality_report),
    )
    stored = report_store.save(content)

    replies.append(Reply(kind="preview", content={
        "text": "Here's what I'll put in the report. Tell me what to change, "
                "or pick a format to generate.",
        "version": stored.version,
        "markdown": render_markdown(stored),
        "formats": ["powerpoint", "word", "pdf", "html", "excel"],
    }))
    return replies


def _revise(chat: Chat, analysis, text: str) -> list[Reply]:
    from app.report.revise import revise

    content = report_store.load(chat.session_id)
    if content is None:
        return [_text("There's nothing planned yet — ask me for a report first.")]

    result, warnings = revise(content, text,
                              provider=chat.provider, model=chat.model)

    if result.content is None:
        reasons = [r.reason for r in result.rejected] or warnings
        return [Reply(kind="notice", content={
            "text": "I didn't change anything.",
            "reasons": reasons,
        })]

    stored = report_store.save(result.content)
    return [Reply(kind="preview", content={
        "text": "Updated: " + "; ".join(result.applied) + ".",
        "version": stored.version,
        "markdown": render_markdown(stored),
        "rejected": [r.reason for r in result.rejected],
        "warnings": warnings,
        "formats": ["powerpoint", "word", "pdf", "html", "excel"],
    })]


def _render(chat: Chat, analysis, output_format: Optional[str]) -> list[Reply]:
    """Build the file. `respond` guarantees analysis exists and content is drafted."""
    content = report_store.load(chat.session_id)
    if content is None:
        return [_text("Let me plan the report first — what do you need?")]

    if report_store.is_stale(content, analysis.data_model, analysis.quality_report):
        return [Reply(kind="notice", content={
            "text": "The data changed after I planned this — probably a conflict "
                    "you resolved. Ask me to re-plan so the report matches.",
        })]

    # Actually render it. Saying "generating…" and returning nothing would be a
    # reply that claims work it did not do — the one thing a status tool must
    # never do about its own behaviour.
    from app.agent.graph import run_generation

    fmt = output_format or "powerpoint"
    blocking = [c for c in analysis.data_model.unresolved_conflicts() if c.critical]

    result = run_generation({
        "session_id": chat.session_id,
        "request_text": analysis.request_text,
        "output_type": fmt,
        "topic": analysis.topic,
        "audience": analysis.audience,
        "data_model": analysis.data_model,
        "quality_report": analysis.quality_report,
        "errors": analysis.errors,
        "warnings": analysis.warnings,
        "conflict_strategy": "hybrid",
        "report_content": content,
    })

    outputs = [Path(p).name for p in result.get("output_files", [])]
    if not outputs:
        return [Reply(kind="notice", content={
            "text": "I could not produce that file.",
            "reasons": result.get("errors", []) or ["no output was written"],
        })]

    return [Reply(kind="downloads", content={
        "text": (f"Here is the {fmt}."
                 + (f" It carries {len(blocking)} unresolved critical conflict(s), "
                    f"and says so." if blocking else "")),
        "format": fmt,
        "session_id": chat.session_id,
        "content_version": content.version,
        "outputs": outputs,
        "summary": result.get("summary_bullets", []),
        "unresolved": [c.conflict_id for c in blocking],
    })]


def _help(analysis) -> list[Reply]:
    ready = analysis is not None
    return [_text(
        "I can plan a report and show you the text before generating anything. "
        + ("Try “a SteerCo deck on current status”, “drop the dependencies "
           "section”, or “generate it as Word”."
           if ready else
           "Tell me what you need and I'll read the files first.")
    )]


# ------------------------------------------------------------ classification
def _classify(text: str, chat: Chat) -> TurnIntent:
    # The chat's provider, not the process default — two chats may be on
    # different backends at the same time.
    client = get_client(chat.provider)
    if client.name != "none":
        try:
            return client.structured(
                system=SYSTEM, user=text, output_model=TurnIntent,
                model=chat.model,
            )
        except LLMError as exc:
            log.warning("intent classification failed (%s); using keywords", exc)
    return _classify_by_keyword(text)


def _classify_by_keyword(text: str) -> TurnIntent:
    """Deterministic fallback. Recognises the common phrasings and admits it
    when it does not understand, rather than picking something plausible."""
    lowered = (text or "").strip().lower()
    if not lowered:
        return TurnIntent(intent="unclear")

    audience = next(
        (a for a in Audience
         if a.value.lower() in lowered
         or (a is Audience.EXECUTIVE and "steerco" in lowered)
         or (a is Audience.PMO and "imo" in lowered)),
        None,
    )

    output_format = next(
        (name for name, words in FORMATS.items()
         if any(word in lowered for word in words)),
        None,
    )

    if re.search(r"\b(generate|export|download|create|make|render|build|produce)\b",
                 lowered) and output_format:
        return TurnIntent(intent="render", output_format=output_format,
                          audience=audience)

    if re.search(r"\b(remove|drop|delete|add|move|reorder|shorten|rename|"
                 r"put .* first|show \d+)\b", lowered):
        return TurnIntent(intent="revise_content", audience=audience)

    if re.search(r"\b(report|deck|presentation|status|summary|update|dashboard)\b",
                 lowered):
        return TurnIntent(intent="request_report", audience=audience,
                          output_format=output_format)

    if audience is not None:
        return TurnIntent(intent="set_audience", audience=audience)

    return TurnIntent(intent="unclear")


def _text(message: str) -> Reply:
    return Reply(kind="text", content={"text": message})
