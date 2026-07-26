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

from app.agent import answers, knowledge, nl_updates
from app.llm import LLMError, get_client
from app.models.pmi import Audience
from app.report import store as report_store
from app.report.render.markdown import render_blocks, render_markdown
from app.storage import json_store
from app.storage.chat_store import Chat, Kind

log = logging.getLogger("pmi.conversation")

Intent = Literal[
    "request_report", "set_audience", "revise_content", "render",
    "resolve_conflict", "question", "unclear",
]

#: What "generate it as X" can mean. Order matters — the first format whose
#: words appear wins, and "dashboard in excel" must reach Excel rather than the
#: HTML dashboard, so `excel` is checked before `html`.
FORMATS = {
    "powerpoint": ("powerpoint", "deck", "slides", "pptx", "presentation"),
    "word": ("word", "docx", "document"),
    "pdf": ("pdf",),
    "excel": ("excel", "xlsx", "workbook", "spreadsheet"),
    # A picture is a deliverable in its own right — "generate an image of the
    # milestones" used to fall through to a re-plan and hand back the
    # data-quality report labelled as the file the user asked for.
    "chart": ("chart", "charts", "image", "images", "picture", "graph", "graphs",
              "plot", "diagram", "visual", "visualisation", "visualization",
              "png"),
    "html": ("html", "web page", "webpage", "dashboard"),
}

#: Words that name the same renderer. `image` is what users type; `chart` is
#: what `generate_output` dispatches on.
FORMAT_ALIASES = {"image": "chart", "images": "chart", "picture": "chart",
                  "png": "chart", "graph": "chart", "diagram": "chart"}

#: Offered under every preview. One list, so the buttons and what the classifier
#: accepts cannot drift.
PREVIEW_FORMATS = ["powerpoint", "word", "pdf", "html", "excel", "chart"]


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
    """The replies for one user turn, scoped to this chat's provider + models.

    The whole turn runs inside `use_selection`, so file reading, summaries and
    generation resolve their backend through the chat's pick — not just the
    conversational classifier, which was all that honoured it before. Two chats
    can be on different providers at once; the context var keeps them from
    leaking into each other."""
    from app.config import get_settings
    from app.llm import use_selection

    selection = get_settings().models_for(chat.provider, chat.model)
    with use_selection(selection):
        return _respond_turn(chat, text)


def _respond_turn(chat: Chat, text: str) -> list[Reply]:
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
    # "What can you do?" is answerable before anything is uploaded — a first-time
    # user asking what this is should get a real answer, not "upload files first".
    if _is_capability_question(text):
        return _capabilities(json_store.load_analysis(chat.session_id))

    uploaded = _uploaded_files(chat)
    if not uploaded:
        return [_text(
            "Upload the week's files first — trackers, SteerCo decks, minutes, "
            "exports, or screenshots of dashboards. I'll read them and tell you "
            "what they say and where they disagree."
        )]

    analysis = json_store.load_analysis(chat.session_id)

    # Mid-exchange turns: answering a one-at-a-time gap question, or confirming a
    # "regenerate?" prompt. `_handle_pending` returns replies when it consumed the
    # turn, or None when the user issued an instruction that abandons the exchange.
    pending = json_store.load_pending(chat.session_id)
    if pending and analysis is not None:
        handled = _handle_pending(chat, analysis, pending, text)
        if handled is not None:
            return handled

    turn = _classify(text, chat)
    preamble: list[Reply] = []

    # Content questions and value corrections both need the model in memory, so
    # they join `NEEDS_ANALYSIS` in deciding whether to read the files first.
    update = nl_updates.parse(text)
    # A pasted block of "<title> — <owner> · due <date>" lines is a value edit
    # too, just many at once — recognised only when a single "X is Y" sentence
    # was not, so a normal correction is never re-read as a one-line paste.
    bulk = nl_updates.parse_bulk(text) if update is None else []
    question = answers.classify(text)
    wants_fill = _is_fill_gaps(text)

    if (turn.intent in NEEDS_ANALYSIS or question or wants_fill
            or update is not None or bulk) and not _analysis_covers(analysis, uploaded):
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
        preamble.extend(_found(chat, analysis))

    # "What are the gaps?" / "Why is the score 98/100?" — answer the section that
    # was actually asked about, from that section's own source of truth.
    if question and analysis is not None:
        return preamble + [_text(answers.answer(question, analysis))]

    # "Fill the gaps" — (re)start the one-at-a-time collection on request.
    if wants_fill and analysis is not None:
        return preamble + _ask_next_gap(chat, analysis, [])

    # "Reporting date is 17-09-2026." / "The deadline is 12-08-2026." — a
    # value-bearing sentence. Attempted **before** `revise_content`, so it never
    # reaches `guard.check_text`: that guard is the §11 backstop for authored
    # prose, and refusing a figure the user just supplied as "not a figure this
    # report states" is exactly backwards.
    if update is not None and analysis is not None:
        applied = nl_updates.apply(analysis, text,
                                   focus=knowledge.load(chat.session_id).focus)
        if applied is not None:
            return preamble + _after_update(chat, analysis, applied)

    # A pasted list of items — "deliver X — Marco Rossi · due — 01-11-2026" per
    # line — fills many gaps at once. Same engine as the single sentence above,
    # so it never reaches `guard.check_text` and writes with the same "supplied
    # by the user" provenance.
    if bulk and analysis is not None:
        result = nl_updates.apply_bulk(
            analysis, text, focus=knowledge.load(chat.session_id).focus)
        if result is not None and result.applied:
            return preamble + _after_bulk(chat, analysis, result)

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

    The check itself lives in `agent.analysis` so every entry point shares it.
    """
    from app.agent.analysis import covers

    return covers(analysis, uploaded)


def _added_files(analysis, uploaded: list[str]) -> list[str]:
    from app.agent.analysis import added_files

    return added_files(analysis, uploaded)


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
    label = _audience_label(text) or (prior.audience_label if prior else "")

    analysis, needs_audience = _analyse(chat, request_text, audience, label)

    if needs_audience:
        # §4: extraction stopped because the audience could not be inferred.
        return None, [_ask_audience(
            "Before I read these — who is the report for? It changes what goes "
            "in it."
        )]

    if analysis is None:
        return None, [_text(
            "I could not read those files. Check the formats and try uploading "
            "again."
        )]

    return analysis, []


# ------------------------------------------------------------------ actions
def _analyse(chat: Chat, request_text: str, audience: Optional[Audience],
             audience_label: str = ""):
    """Read the files. In a chat there is no "Analyse" button to press.

    A thin adapter over `agent.analysis.ensure_analysis`, which every entry
    point now shares. The wizard made this an explicit step; a conversation
    cannot, because the user has already said what they want and being told to
    go and do something else is a dead end. So asking for a report is what
    triggers extraction.
    """
    from app.agent.analysis import ensure_analysis

    analysis, needs_audience = ensure_analysis(
        chat.session_id,
        request_text=request_text,
        audience=audience,
        audience_label=audience_label,
        force=True,
    )
    return analysis, needs_audience


def _found(chat: Chat, analysis) -> list[Reply]:
    """What the files actually said, before any report is drafted.

    §5.6: "low-confidence findings should be shown to the user for review." A
    sentence saying *three* findings need checking is not that — the user cannot
    act on a count. They are listed individually, with what was read and how
    confident the reading was, because the only person who can confirm a figure
    scraped off a whiteboard photo is the one who was in the room.

    Completeness gaps used to be surfaced here as a batch form card. They are now
    collected one question at a time (§8.2), started at the end of `_plan` once a
    report is actually being drafted — see `_maybe_start_gaps`.
    """
    model = analysis.data_model
    unresolved = model.unresolved_conflicts()
    low = model.low_confidence_items()
    score = getattr(analysis.quality_report, "score", None)

    from app.agent.corrections import fillable

    parts = [f"Read {len(model.source_files)} file(s): {model.entity_count()} items."]
    if unresolved:
        parts.append(f"{len(unresolved)} source conflict(s) still open.")
    gaps = fillable(model.validation_issues)
    if gaps:
        parts.append(f"{len(gaps)} value(s) missing that only you can fill.")
    if score is not None:
        parts.append(f"Data quality {score:.0f}/100.")

    replies = [_text(" ".join(parts))]

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


def _plan(chat: Chat, analysis, turn: TurnIntent, text: str,
         *, collect_gaps: bool = True) -> list[Reply]:
    """Draft the report. `respond` guarantees `analysis` is not None."""
    audience = turn.audience or analysis.audience
    if audience is None:
        # §4: ask, do not guess.
        return [_ask_audience(
            "Who is this report for? It changes what goes in it — a Steering "
            "Committee wants decisions, an IMO wants overdue work."
        )]

    _remember_structure(chat, text)

    blocking = [c for c in analysis.data_model.unresolved_conflicts() if c.critical]
    replies: list[Reply] = []
    if blocking:
        # The 409 gate, in conversational form. Never quietly skipped.
        replies.append(Reply(kind="conflict", content={
            "text": f"{len(blocking)} critical conflict(s) need a decision "
                    f"before I can stand behind these figures.",
            "conflicts": [c.model_dump(mode="json") for c in blocking],
        }))

    from app.report.pipeline import plan_for_session

    # One planning pipeline, shared with `/api/content` and the graph. Three
    # copies of this used to assemble the bullets, the quality report and the
    # fingerprint slightly differently, so the same session produced different
    # reports depending on which entry point drafted it.
    stored = plan_for_session(
        chat.session_id, analysis,
        audience=audience,
        audience_label=_audience_label(text) or analysis.audience_label,
        request_text=analysis.request_text or text,
    )

    replies.append(Reply(kind="preview", content={
        "text": "Here's what I'll put in the report. Tell me what to change, "
                "or pick a format to generate.",
        "version": stored.version,
        "markdown": render_markdown(stored),
        # The same content, structured — the preview can only offer to edit a
        # cell it can identify, and markdown flattens that identity away.
        "sections": render_blocks(stored),
        "session_id": chat.session_id,
        "formats": PREVIEW_FORMATS,
    }))
    # Now that a draft exists (and the audience is settled), start filling the
    # gaps the files left behind — one question at a time, in chat. Skipped on a
    # regenerate, which is already the tail of a correction exchange.
    if collect_gaps:
        replies.extend(_maybe_start_gaps(chat, analysis))
    return replies


def _remember_structure(chat: Chat, text: str) -> None:
    """A structure the user described becomes the template for every format.

    Stored in the KB rather than used once, so it survives later turns: someone
    who laid out their sections in turn one and asks for Excel in turn four gets
    the workbook they described, not the house template. `DECKS` remains the
    default when no structure was given.
    """
    from app.report import structure as structure_mod

    spec = structure_mod.detect(text, provider=chat.provider or "",
                                model=chat.model or "")
    if not spec:
        return

    kb = knowledge.load(chat.session_id)
    kb.structure = spec.model_dump(mode="json")
    # Structure changes what the report says, so it counts towards the content
    # revision and leaves any existing draft stale.
    kb.content_revision += 1
    knowledge.save(kb)
    log.info("structure requested for %s: %s", chat.session_id,
             [s.title for s in spec.sections])


def _revise(chat: Chat, analysis, text: str) -> list[Reply]:
    from app.report.revise import revise

    content = report_store.load(chat.session_id)
    if content is None:
        return [_text("There's nothing planned yet — ask me for a report first.")]

    result, warnings = revise(content, text,
                              provider=chat.provider, model=chat.model)

    if result.content is None:
        # Not "I didn't change anything." — that says nothing about what was
        # looked for, so the user's only move is to guess differently. Name the
        # sections the instruction could have meant instead.
        reasons = [r.reason for r in result.rejected] or warnings
        sections = ", ".join(s.label for s in content.narrative()[:8])
        return [Reply(kind="notice", content={
            "text": (f"I read that as a wording change but couldn't match it to "
                     f"anything in the report. The sections are: {sections}."),
            "reasons": reasons,
        })]

    stored = report_store.save(result.content)
    return [Reply(kind="preview", content={
        "text": "Updated: " + "; ".join(result.applied) + ".",
        "version": stored.version,
        "markdown": render_markdown(stored),
        "rejected": [r.reason for r in result.rejected],
        "warnings": warnings,
        "formats": PREVIEW_FORMATS,
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

    try:
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
    except Exception as exc:                                  # noqa: BLE001
        # A renderer that blows up is a failed file, not a failed conversation.
        # The reason travels with the notice so the user can say something
        # useful about it rather than retrying blind.
        log.exception("generation failed for %s (%s)", chat.session_id, fmt)
        return [Reply(kind="notice", content={
            "text": f"I could not produce the {fmt} file.",
            "reasons": [f"{type(exc).__name__}: {exc}"],
        })]

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

    audience = _match_audience(lowered)

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


def _match_audience(lowered: str) -> Optional[Audience]:
    """One audience map, shared with the request parser.

    The chat classifier and `llm.fallbacks.heuristic_parse` used to keep separate
    keyword lists, so "management" set the audience on one path and not the other
    — the same prompt behaved differently depending on which entry point it hit.
    Reading the fallback hints here keeps the two in step (§9/§4).
    """
    from app.llm.fallbacks import _AUDIENCE_HINTS

    for aud, keywords in _AUDIENCE_HINTS.items():
        if any(re.search(rf"\b{re.escape(k)}\b", lowered) for k in keywords):
            return aud
    return None


# ------------------------------------------------------------- capabilities (§9)
def _is_capability_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if t in {"help", "capabilities", "?", "what now", "what next"}:
        return True
    return bool(re.search(
        r"\b(what can you do|what do you do|what are you able to|"
        r"what can you help( me)? with|how (can|do) you help|"
        r"your capabilities|what features|what can this do)\b", t
    ))


def _capabilities(analysis) -> list[Reply]:
    return [_text(
        "I turn fragmented PMI files into an audience-specific report. What I can do:\n\n"
        "• Read Excel, PowerPoint, PDF, Word, HTML and image files and consolidate "
        "milestones, workstream status, risks, issues, dependencies, synergies, "
        "budget, KPIs, decisions, owners and due dates into one PMI data model.\n"
        "• Detect inconsistencies between documents — different completion %, "
        "conflicting milestone dates, different budget values, missing owners — and "
        "trace every figure back to the file it came from.\n"
        "• Draft the report as text first, so you can read and revise it before "
        "anything is generated.\n"
        "• Fill missing values one question at a time, and apply your corrections "
        "straight into the data.\n"
        "• Generate PowerPoint, Word, PDF, HTML or Excel — for a Steering Committee "
        "(SteerCo), an IMO/PMO, Finance, or a single workstream.\n\n"
        "Try: “Create an Executive SteerCo deck”, “What are the gaps?”, "
        "“Day-1 legal close should be 02-06-2026”, or “generate it as Word”."
    )]


# ---------------------------------------------- one-at-a-time gap collection (§5)
_SKIP_WORDS = {"next", "skip", "skip it", "pass", "n/a", "na"}
_STOP_WORDS = {"cancel", "stop", "done", "that's all", "thats all", "nevermind",
               "never mind", "no more", "no thanks", "leave it", "enough"}
_AFFIRM = {"yes", "y", "yeah", "yep", "sure", "ok", "okay", "please", "please do",
           "go ahead", "do it", "regenerate", "yes please", "rebuild", "go"}


def _is_fill_gaps(text: str) -> bool:
    t = (text or "").strip().lower()
    if t in {"fill them", "fill it in", "fill them in", "fill in the gaps",
             "fill the gaps"}:
        return True
    return bool(re.search(
        r"\b(fill|provide|enter|complete|collect|supply)\b.{0,20}?"
        r"\b(gap|gaps|missing|value|values|blank|blanks|field|fields)\b", t
    ))


def _gap_key(issue) -> str:
    """Stable across re-checks: derived from the entity, not the issue_id (which
    is re-hashed every time `run_checks` rebuilds the issue list)."""
    return f"{issue.entity_type}|{issue.entity_id}|{issue.field}"


def _gap_prompt(issue) -> str:
    label = issue.entity_label or issue.entity_id or "this item"
    field = (issue.field or "value").replace("_", " ")
    return (f"Please provide the {field} for “{label}”, "
            "or type 'next' to skip.")


def _open_gaps(model, session_id: str, skipped: list[str]):
    """Gaps still worth asking about.

    Anything the user already answered or explicitly declined is excluded via
    the knowledge base, not just the in-flight `skipped` list — that list lived
    in `pending.json` and died with the exchange, so a gap the user had already
    passed on came back the next time collection started.
    """
    from app.agent.corrections import fillable

    kb = knowledge.load(session_id)
    seen = set(skipped) | set(kb.declined_gaps) | set(kb.answered_gaps)
    return [g for g in fillable(model.validation_issues) if _gap_key(g) not in seen]


def _gap_by_key(model, key: Optional[str]):
    from app.agent.corrections import fillable

    return next((g for g in fillable(model.validation_issues)
                 if _gap_key(g) == key), None)


def _ask_next_gap(chat: Chat, analysis, skipped: list[str]) -> list[Reply]:
    gaps = _open_gaps(analysis.data_model, chat.session_id, skipped)
    if not gaps:
        json_store.clear_pending(chat.session_id)
        return [_text("That's every value I can take from you. Ask me to build the "
                      "report when you're ready, or tell me what else to change.")]
    nxt = gaps[0]
    json_store.save_pending(chat.session_id, {
        "mode": "collecting_missing",
        "current_key": _gap_key(nxt),
        "skipped": skipped,
    })
    # The asked-about entity becomes the conversational focus, so a bare answer
    # in normal English ("the realization date is 30-09-2026") resolves against
    # it instead of referring to nothing.
    kb = knowledge.load(chat.session_id)
    kb.set_focus(knowledge.EntityRef(
        entity_type=nxt.entity_type, entity_id=nxt.entity_id,
        label=nxt.entity_label or "", field=nxt.field,
    ))
    knowledge.save(kb)
    return [_text(_gap_prompt(nxt))]


def _maybe_start_gaps(chat: Chat, analysis) -> list[Reply]:
    """Kick off gap collection after a draft exists. One question, then the
    `collecting_missing` pending state carries the rest across turns."""
    from app.agent.corrections import fillable

    gaps = _open_gaps(analysis.data_model, chat.session_id, [])
    if not gaps:
        return []
    intro = (f"{len(gaps)} value(s) weren't in the files — let's fill them in "
             "(type 'next' to skip one, or 'stop' to leave the rest).\n")
    asked = _ask_next_gap(chat, analysis, [])
    first = asked[0]
    first.content["text"] = intro + first.content["text"]
    return asked


def _interrupts_collection(text: str, model) -> bool:
    """Does this turn abandon the gap loop rather than answer it?

    A bare value ("Anna Schmidt", "02-06-2026") is the answer, and so is a whole
    sentence ("the realization date is 30-09-2026") — that one used to abandon
    the loop, so answering the agent's own question in normal English broke it.
    Sentences are handled by `nl_updates` inside the loop instead. Only a
    question or a command genuinely interrupts.
    """
    if answers.classify(text) or _is_fill_gaps(text):
        return True
    # A pasted multi-item block answers many gaps at once rather than the one
    # being asked, so it abandons the one-at-a-time loop and is applied in full
    # by normal routing.
    if nl_updates.parse(text) is None and nl_updates.parse_bulk(text):
        return True
    return _classify_by_keyword(text).intent in (
        "render", "request_report", "revise_content", "set_audience",
        "resolve_conflict")


def _handle_pending(chat: Chat, analysis, pending: dict, text: str):
    """Consume a turn that belongs to an ongoing exchange.

    Returns replies when the turn was an answer/skip/confirmation, or ``None`` to
    let normal routing take over — an instruction like "generate it as Word" must
    interrupt the collection loop rather than be swallowed as a value.
    """
    mode = pending.get("mode")
    lowered = (text or "").strip().lower()

    if mode == "await_regen":
        json_store.clear_pending(chat.session_id)
        if lowered in _AFFIRM:
            return _regenerate(chat, analysis, pending.get("format"))
        return None  # not now — carry on with normal routing

    if mode != "collecting_missing":
        return None

    model = analysis.data_model
    skipped = list(pending.get("skipped", []))
    current_key = pending.get("current_key")

    if lowered in _STOP_WORDS:
        json_store.clear_pending(chat.session_id)
        return [_text("Okay — I'll leave the rest blank (they'll show as \"Not "
                      "Reported\"). Ask me to build the report whenever you're ready.")]

    if lowered in _SKIP_WORDS:
        if current_key and current_key not in skipped:
            skipped.append(current_key)
        # Recorded durably, so the same question is not re-asked in a later
        # collection run after this exchange has ended.
        knowledge.save(knowledge.load(chat.session_id).decline_gap(current_key))
        return _ask_next_gap(chat, analysis, skipped)

    # A question, command, or correction interrupts collection instead of being
    # read as the answer to the current gap. The loop is abandoned cleanly; the
    # user can resume it with "fill the gaps".
    if _interrupts_collection(text, model):
        json_store.clear_pending(chat.session_id)
        return None

    issue = _gap_by_key(model, current_key)
    if issue is None:
        # The gap is gone (already filled, or the files were re-read). Move on.
        return _ask_next_gap(chat, analysis, skipped)

    # An answer given as a whole sentence — "the realization date is 30-09-2026"
    # — is still an answer to the question that was asked. It used to be
    # classified as an interruption and abandon the loop, so replying to the
    # agent's own question in normal English broke the thing that asked it.
    #
    # A sentence naming a *different* entity is a different matter: it is a
    # correction the user wants applied on its own terms, with its own offer to
    # regenerate, so it interrupts and is routed normally.
    update = nl_updates.parse(text)
    if update is not None:
        focus = knowledge.EntityRef(
            entity_type=issue.entity_type, entity_id=issue.entity_id,
            label=issue.entity_label or "", field=issue.field,
        )
        located = nl_updates.locate(model, update.target, update.value, focus=focus)
        if located is None or located.entity_id != issue.entity_id:
            json_store.clear_pending(chat.session_id)
            return None

        applied = nl_updates.apply(analysis, text, focus=focus)
        if applied is not None and applied.applied:
            knowledge.save(knowledge.load(chat.session_id).answer_gap(current_key))
            return ([_text(applied.message)]
                    + _ask_next_gap(chat, analysis, skipped))

    from app.agent.corrections import apply_and_persist

    result = apply_and_persist(analysis, issue, text.strip())
    if not result.applied:
        # Re-ask the same field with the reason it was rejected.
        return [_text(result.message + " " + _gap_prompt(issue))]

    knowledge.save(knowledge.load(chat.session_id).answer_gap(current_key))
    # The filled gap drops out of `fillable`, so the next question advances.
    return [_text(result.message)] + _ask_next_gap(chat, analysis, skipped)


# ------------------------------------------------- value corrections (§6/§7)
def _after_update(chat: Chat, analysis, applied) -> list[Reply]:
    """The reply for a natural-language data update.

    Says which field changed and offers the one next step that follows from it.
    An update that resolved to nothing names the candidates it looked at — "I
    didn't change anything." told the user nothing about what to try instead.
    """
    from app.report import chat_format as fmt_chat

    if not applied.applied:
        body = []
        if applied.candidates:
            body = ["Did you mean one of these?"] + fmt_chat.bullets(applied.candidates)
        return [_text(fmt_chat.reply(
            applied.message,
            body=body,
            action=("Name the item and the field — “the due date for Payroll "
                    "cutover is 12-08-2026”."),
        ))]

    # What the agent just wrote about is what a bare follow-up refers to.
    if applied.scope == "entity":
        kb = knowledge.load(chat.session_id)
        kb.set_focus(knowledge.EntityRef(
            entity_type=applied.entity_type, entity_id=applied.entity_id,
            label=applied.label, field=applied.field,
        ))
        knowledge.save(kb)

    replies = [_text(fmt_chat.reply(
        applied.message,
        body=(["That gap is closed — the report will state your value and record "
               "it as coming from you."] if applied.scope == "entity" else
              ["Overdue flags and milestone delays have been re-derived from the "
               "new date."]),
        action="",
    ))]

    # A report already exists → offer to rebuild it with the corrected data
    # rather than making the user start over (§7).
    if report_store.load(chat.session_id) is not None:
        json_store.save_pending(chat.session_id, {
            "mode": "await_regen",
            "format": _last_generated_format(chat.session_id),
        })
        replies.append(_text(
            "Want me to regenerate the report with the updated data? (yes / no)"
        ))
    return replies


def _after_bulk(chat: Chat, analysis, result) -> list[Reply]:
    """The reply for a pasted, multi-item update.

    Says how many values landed and — just as importantly — names the lines it
    could not place, because a paste that silently drops two of ten items looks
    exactly like one that saved all ten.
    """
    from app.report import chat_format as fmt_chat

    body = list(fmt_chat.bullets(result.applied, limit=12))
    if result.skipped:
        body.append("")
        body.append(f"**{len(result.skipped)} line(s) I couldn't place:**")
        body += fmt_chat.bullets(result.skipped, limit=8)

    replies = [_text(fmt_chat.reply(
        f"Saved {len(result.applied)} value(s) from {result.count} item(s)",
        body=body,
        action=("Those gaps are closed — the report will state your values and "
                "record them as coming from you."),
    ))]

    if report_store.load(chat.session_id) is not None:
        json_store.save_pending(chat.session_id, {
            "mode": "await_regen",
            "format": _last_generated_format(chat.session_id),
        })
        replies.append(_text(
            "Want me to regenerate the report with the updated data? (yes / no)"
        ))
    return replies


_EXT_TO_FORMAT = {".pptx": "powerpoint", ".docx": "word", ".pdf": "pdf",
                  ".html": "html", ".htm": "html", ".xlsx": "excel"}


def _last_generated_format(session_id: str) -> Optional[str]:
    meta = json_store.load_meta(session_id) or {}
    for run in reversed(meta.get("runs", [])):
        for name in run.get("outputs", []):
            for ext, fmt in _EXT_TO_FORMAT.items():
                if str(name).lower().endswith(ext):
                    return fmt
    return None


def _regenerate(chat: Chat, analysis, output_format: Optional[str]) -> list[Reply]:
    """Re-plan from the corrected model, then render — the "yes, rebuild it" path.

    Re-planning refreshes the draft so it reflects the corrected value and clears
    the staleness the correction introduced; rendering then produces the file in
    whatever format was last generated (default PowerPoint)."""
    fresh = json_store.load_analysis(chat.session_id) or analysis
    turn = TurnIntent(intent="request_report", audience=fresh.audience)
    replies = _plan(chat, fresh, turn, fresh.request_text or "", collect_gaps=False)

    if any(r.kind == "preview" for r in replies):
        latest = json_store.load_analysis(chat.session_id) or fresh
        replies += _render(chat, latest, output_format or "powerpoint")
    return replies


def _ask_audience(text: str) -> Reply:
    """§4's question, asked openly rather than as a closed list.

    The four `Audience` values are the planning keys — there are four report
    shapes and no more — but they are not the vocabulary the user thinks in.
    Offering only "executive / pmo / finance / workstream" forced somebody who
    wanted a pack for the Integration Director to pick the closest-looking chip,
    and the label they chose then went on the title page. The chips are examples
    now; anything typed is matched to a shape by `_match_audience` and kept
    verbatim as `ReportContent.audience_label`.
    """
    return Reply(kind="audience_choice", content={
        "text": text,
        "options": [a.value for a in Audience],
        "free_text": True,
        "placeholder": "e.g. Integration Director, Steering Committee, HR "
                       "workstream leads…",
    })


def _audience_label(text: str) -> str:
    """The words the user used for their reader, when the turn was about that.

    Only when the message is short enough to *be* a label — "Steering Committee"
    is one, "give me a deck on the Day 1 risks for the steering committee" is a
    request that happens to contain one, and putting that whole sentence on a
    title page would be worse than the canonical label.
    """
    stripped = (text or "").strip().strip(".?!").strip()
    if not stripped or len(stripped) > 40 or len(stripped.split()) > 5:
        return ""
    if _match_audience(stripped.lower()) is None:
        return ""
    return stripped


def _text(message: str) -> Reply:
    return Reply(kind="text", content={"text": message})
