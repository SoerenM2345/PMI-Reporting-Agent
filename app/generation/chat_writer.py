"""Write the assistant's side of a conversation.

Every chat reply in this codebase used to be a template. `agent/answers.py` is
467 lines of regex routing with no model call in it, which is why the assistant
could report and could not explain: ask it something the routes did not
anticipate and the best it could do was list its capabilities.

So the model writes the answer, and Python keeps it honest. `guard.check_text`
is the same §11 backstop the revision loop and the page writer use: a figure the
evidence does not hold is refused. The difference here is what happens next —
the model is told which figure was wrong and asked once more, because in a
conversation a single unsupported number should cost that number, not the whole
answer.

If it fails twice, the deterministic answer is used **and the run says so**.
Silently serving a template while sounding conversational is precisely the
failure this module exists to end.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from app.agent.replies import ChatAnswer
from app.context.schemas import GenerationContext
from app.evidence.retrieval import pack, retrieve
from app.llm import prompts, reasoning_model, tasks

log = logging.getLogger("pmi.generation.chat")

#: Enough evidence to answer a question well, far less than a document needs.
EVIDENCE_BUDGET_CHARS = 12_000
TOP_K = 40

#: A conversational answer that runs past this is a report, and the user asked a
#: question. The prompt says so; this is the backstop.
MAX_ANSWER_CHARS = 6_000


class ChatReplyDraft(BaseModel):
    """What the model writes for one turn."""

    content: str = Field(default="", description="The answer, as Markdown.")


def answer(question: str, *, context: GenerationContext, analysis=None,
           use_model: bool = True) -> ChatAnswer:
    """The assistant's reply to one message.

    The conversation comes off the context, which already carries a recap and
    the turns most relevant to this one — the chat transcript is not the source
    of truth for anything (that is `analysis.json`), so it is read here as
    background, never as a record of decisions.
    """
    if not use_model:
        return deterministic(question, context, analysis)

    corpus = context.evidence.numeric_corpus()
    payload = _payload(question, context)

    draft = _ask(payload, question, context, analysis)
    offending = _unsupported(draft.content, corpus)
    if not offending:
        return _finish(draft.content)

    # One correction, naming the figures. A model that quoted a number it half
    # remembered will usually drop it when told; a model that cannot is not
    # going to be fixed by asking a third time.
    log.info("chat answer stated unsupported figure(s) %s; asking again",
             offending[:3])
    retry = _ask(_corrected(payload, offending), question, context, analysis)
    if not _unsupported(retry.content, corpus):
        return _finish(retry.content)

    from app.report import guard

    log.warning("chat answer refused twice: %s",
                guard.describe(offending, draft.content))
    fallback = deterministic(question, context, analysis)
    return ChatAnswer(
        content=fallback.content + "\n\n" + _REFUSAL_NOTE,
        actions=fallback.actions, artifacts=fallback.artifacts,
    )


_REFUSAL_NOTE = (
    "*(I drafted a fuller answer but it stated a figure none of the sources "
    "support, so I did not use it. The above comes straight from the files.)*"
)


def _ask(payload: str, question: str, context: GenerationContext,
         analysis) -> ChatReplyDraft:
    return tasks.run_task(
        "chat.answer",
        system=prompts.compose("_grounding_rules", "chat_answer"),
        user=payload,
        output_model=ChatReplyDraft,
        model=reasoning_model(),
        max_tokens=2048,
        fallback=lambda: ChatReplyDraft(
            content=deterministic(question, context, analysis).content),
    )


def _unsupported(text: str, corpus: set[str]) -> list[str]:
    from app.report import guard

    return guard.check_text(text, corpus)


#: `ev:risk:R001` in every wrapper a model reaches for when it wants to cite:
#: bare, in parentheses or brackets, backticked, or all three at once.
_BRACKETED_ID = re.compile(
    r"\s*[\(\[]\s*`?ev:[a-z_]+:[A-Za-z0-9_.\-]+`?\s*[\)\]]")
_BARE_ID = re.compile(r"`?\bev:[a-z_]+:[A-Za-z0-9_.\-]+`?")


def _strip_ids(text: str) -> str:
    """Take the record keys back out of the answer.

    The shared `_grounding_rules` preamble tells the model to reference evidence
    by `evidence_id`, which is exactly right when it is *planning a document* —
    Python resolves the id and places the value. In a chat the model is writing
    the words the reader sees, so an id is leaked plumbing: it means nothing to
    the reader and it makes the assistant sound like a database.
    `chat_answer.md` says so; this is the backstop, because a prompt is not a
    guarantee.

    A bracketed citation goes entirely, including the space before it. A bare
    one leaves a space behind, or "the migration ev:task:T002 and the rest"
    closes up into "the migrationand the rest".
    """
    cleaned = _BRACKETED_ID.sub("", text or "")
    cleaned = _BARE_ID.sub(" ", cleaned)
    # Tidy what the removal can strand.
    cleaned = re.sub(r"\(\s*,", "(", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return re.sub(r"[ \t]+([,.;:)])", r"\1", cleaned)


def _finish(content: str) -> ChatAnswer:
    return ChatAnswer(content=_clip(_strip_ids(content)))


def _clip(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_ANSWER_CHARS:
        return text
    cut = text[:MAX_ANSWER_CHARS]
    boundary = max(cut.rfind("\n\n"), cut.rfind(". "))
    return (cut[:boundary + 1] if boundary > MAX_ANSWER_CHARS * 0.6
            else cut).rstrip()


# ------------------------------------------------------------------ payload
def _payload(question: str, context: GenerationContext) -> str:
    hits = retrieve(question, context.evidence, k=TOP_K,
                    reporting_date=context.reporting_date,
                    named_terms=list(context.company_names.known))
    packed = pack(hits, budget_chars=EVIDENCE_BUDGET_CHARS)

    parts = ["## The message\n" + prompts.data_block("user_message", question)]

    history = _history(context)
    if history:
        parts.append("## Earlier in this conversation\n"
                     + prompts.data_block("chat_history", history))

    project = _project_lines(context)
    if project:
        parts.append("## The project\n" + "\n".join(project))

    parts.append("## Evidence\n" + packed.disclosure)
    parts.append(prompts.data_block("evidence", packed.text, limit=200_000))

    contested = context.unresolved_critical_conflicts
    if contested:
        parts.append(f"{len(contested)} unresolved critical conflict(s) affect "
                     f"figures you may be asked about. Give both values and "
                     f"their files; do not present either as settled.")
    return "\n\n".join(part for part in parts if part)


def _history(context: GenerationContext, *, limit: int = 8) -> str:
    """The recap plus the turns this message most likely refers back to.

    Both are needed: the recap keeps a long conversation affordable, and the
    excerpts are what make "make that shorter" or "what about the second one?"
    resolvable at all.
    """
    parts = [context.chat_summary.strip()] if context.chat_summary else []
    excerpts = context.relevant_chat_messages[-limit:]
    if excerpts:
        parts.append("\n".join(
            f"{excerpt.role}: {excerpt.text.strip()[:400]}"
            for excerpt in excerpts if excerpt.text.strip()))
    return "\n\n".join(part for part in parts if part)


def _project_lines(context: GenerationContext) -> list[str]:
    lines: list[str] = []
    if context.company_names.as_sentence():
        lines.append(context.company_names.as_sentence())
    if context.reporting_period:
        lines.append(f"Reporting period: {context.reporting_period}.")
    if context.transaction.days_to_day_1 is not None:
        lines.append(f"Day 1 is {context.transaction.days_to_day_1} days away "
                     f"(computed — you may refer to it).")
    if context.audience:
        lines.append(f"This project's reports are written for: {context.audience}.")
    if context.project_context:
        lines.append(prompts.data_block("project_context",
                                        context.project_context))
    knowledge = context.project_knowledge.as_markdown()
    if knowledge:
        lines.append(prompts.data_block("project_knowledge", knowledge))
    return lines


def _corrected(payload: str, offending: Sequence[str]) -> str:
    return payload + (
        "\n\n## Correction\n"
        "Your previous answer stated " + ", ".join(offending[:4]) + ", which "
        "no source supports. Write the answer again without those figures — "
        "either use a value that is in the evidence above, or say that the "
        "figure is not recorded. Do not restate them in any form."
    )


# ------------------------------------------------------- the deterministic path
def deterministic(question: str, context: GenerationContext,
                  analysis=None) -> ChatAnswer:
    """The answer with no model: honest, plain, and never invented.

    `agent/answers.py` already routes the thirteen questions it recognises to
    the collection that can answer them. What it cannot do is answer anything
    else, and its old reply for that case was a list of features. Saying what is
    actually here is more useful than advertising.
    """
    from app.agent import answers

    if analysis is not None:
        kind = answers.classify(question)
        if kind:
            return ChatAnswer(content=answers.answer(kind, analysis))

    return ChatAnswer(content=_state_of_play(context))


def _state_of_play(context: GenerationContext) -> str:
    """What is known, in one short passage, with no figure that is not counted.

    `has_evidence` rather than "are there items": projection always emits the
    computed-fact scaffold, so an empty project still yields two dozen facts —
    arithmetic over nothing. Counting those would tell the user this project
    holds 26 things when nothing has been read at all.
    """
    evidence = context.evidence
    if not context.has_evidence:
        return ("Nothing has been read for this project yet, so there is nothing "
                "I can tell you about it. Upload the trackers, status decks or "
                "exports you want it built from.")

    substantive = {kind: count for kind, count in evidence.kinds.items()
                   if kind not in ("fact", "absence")}
    counted = ", ".join(f"{count} {kind}{'s' if count != 1 else ''}"
                        for kind, count in sorted(substantive.items(),
                                                  key=lambda kv: -kv[1])[:6])
    lines = [f"I can answer from what the files hold: {counted}."
             if counted else "I have read the files for this project."]

    contested = evidence.contested()
    if contested:
        lines.append(f"{len(contested)} figure(s) are disputed between sources — "
                     f"worth settling before anything is circulated.")
    must = evidence.must_include()
    if must:
        lines.append(f"{len(must)} item(s) need a decision or have no mitigation.")

    lines.append("Ask me about the risks, the milestones, the budget or where "
                 "the sources disagree — or tell me what document you need.")
    return " ".join(lines)


def summarize_plan(deliverable, *, limit: int = 8) -> str:
    """Say what a drafted report contains, in prose rather than as a card."""
    titles = [page.title for page in deliverable.pages
              if page.purpose not in ("cover", "divider") and page.title]
    lines = []
    if deliverable.governing_message:
        lines.append(deliverable.governing_message)
    if titles:
        shown = titles[:limit]
        lines.append("It covers:\n"
                     + "\n".join(f"- {title}" for title in shown)
                     + (f"\n- …and {len(titles) - limit} more"
                        if len(titles) > limit else ""))
    return "\n\n".join(lines)
