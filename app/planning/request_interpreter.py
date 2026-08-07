"""Turn a request into an `OutputBrief`, preserving what the user actually said.

The old pipeline collapsed a request into three values — an output type, a topic
slug and one of four audiences — and then looked the sections up in a table. So
"a one-pager for the CFO on whether we can hold the Day 1 date" and "the full
SteerCo pack" produced the same seven sections in the same order.

Two rules here:

* **Explicit requirements are carried, not inferred.** Sections the context
  builder already extracted verbatim are merged into `scope_topics` *after* the
  model runs, so a model that overlooks one cannot lose it.
* **The keyless path is honest.** With no provider the brief comes from
  deterministic heuristics, which is enough to produce a usable document and not
  enough to pretend it was analysed. `run_task` records that, once.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.context.schemas import GenerationContext
from app.llm import fast_model, prompts, tasks
from app.planning.schemas import OutputBrief

log = logging.getLogger("pmi.planning.interpreter")

_BUDGET_CHARS = 6_000


def interpret(context: GenerationContext) -> OutputBrief:
    """The user's ask, in a shape the storyline planner can work from."""
    brief = tasks.run_task(
        "plan.request_brief",
        system=prompts.compose("_grounding_rules", "plan_request_brief"),
        user=_payload(context),
        output_model=OutputBrief,
        model=fast_model(),
        max_tokens=2048,
        fallback=lambda: fallback_brief(context),
    )
    return reconcile(brief, context)


def reconcile(brief: OutputBrief, context: GenerationContext) -> OutputBrief:
    """Force the brief to honour what the user explicitly stated.

    A model asked to summarise eleven named sections will sometimes return nine
    good ones. That is a reasonable editorial instinct and the wrong answer: the
    planner may retitle and regroup later, but the topic list it plans *from*
    has to be complete, or coverage cannot be checked at the end.
    """
    topics = list(brief.scope_topics)
    lowered = {t.casefold() for t in topics}
    for requested in context.requested_sections:
        if requested.casefold() not in lowered:
            topics.append(requested)
            lowered.add(requested.casefold())
    brief.scope_topics = topics

    if context.requested_output_format:
        brief.primary_format = context.requested_output_format   # type: ignore[assignment]
    if context.audience and not brief.audience_label:
        brief.audience_label = context.audience

    for constraint in context.user_constraints:
        if constraint.kind == "max_pages" and constraint.value.isdigit():
            limit = int(constraint.value)
            if brief.target_page_count is None or brief.target_page_count > limit:
                brief.target_page_count = limit
        elif constraint.kind == "exclude_topic":
            if constraint.value not in brief.excluded_topics:
                brief.excluded_topics.append(constraint.value)
        elif constraint.kind == "tone" and constraint.value in (
                "direct", "neutral", "diplomatic"):
            brief.tone = constraint.value                        # type: ignore[assignment]

    # Exclusion is a hard user instruction, not merely advice to the storyline
    # model. Remove a matching topic here as well so the keyless planner and the
    # coverage repair cannot put it back into the document.
    excluded_words = [_topic_words(value) for value in brief.excluded_topics]
    brief.scope_topics = [
        topic for topic in brief.scope_topics
        if not any(words and words <= _topic_words(topic)
                   for words in excluded_words)
    ]

    if not brief.title_proposal:
        brief.title_proposal = context.display_name()
    return brief


def _topic_words(value: str) -> set[str]:
    return {word for word in re.split(r"[^a-z0-9]+", (value or "").casefold())
            if len(word) > 2 and word not in {"slide", "section", "page", "the"}}


def _payload(context: GenerationContext) -> str:
    parts = [
        prompts.data_block("user_request", context.user_request),
        prompts.data_block("project_context", context.project_context),
    ]
    if context.request_history[:-1]:
        parts.append(prompts.data_block(
            "earlier_requests", "\n".join(context.request_history[:-1])))
    if context.requested_sections:
        parts.append("The user explicitly named these sections, in this order:\n"
                     + "\n".join(f"- {s}" for s in context.requested_sections))
    if context.audience:
        parts.append(f"The user named this reader: {context.audience}")
    if context.requested_visuals:
        parts.append("Visuals the user asked for: "
                     + ", ".join(context.requested_visuals))
    if context.company_names.as_sentence():
        parts.append(context.company_names.as_sentence())
    if context.reporting_period:
        parts.append(f"Reporting period: {context.reporting_period}")

    parts.append("Evidence available, by kind: "
                 + ", ".join(f"{count} {kind}"
                             for kind, count in context.evidence.kinds.items()))
    text = "\n\n".join(p for p in parts if p)
    return text[:_BUDGET_CHARS]


# ------------------------------------------------------------ keyless path
#: Matched in order, and the order carries the rule: **a form the user named
#: outranks the reader they named it for.** "A KPI dashboard for SteerCo" is a
#: dashboard; reading it as a `steerco_pack` because the word "SteerCo" appears
#: is how a three-tile request became the eight-section house pack — the kind
#: reaches the storyline prompt as "Document: steerco pack", and a model told it
#: is writing a SteerCo pack writes what a SteerCo pack conventionally contains.
#: An audience is an audience; only "the SteerCo pack" names the document.
_KIND_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bone[- ]pager\b", re.I), "one_pager"),
    (re.compile(r"\b(dashboard|scorecard|kpi)\b", re.I), "custom"),
    (re.compile(r"\b(deep[- ]dive|detailed analysis)\b", re.I), "deep_dive"),
    (re.compile(r"\b(steerco|steering committee)\b", re.I), "steerco_pack"),
    (re.compile(r"\bboard\b", re.I), "board_update"),
    (re.compile(r"\b(budget|financial|finance|synerg|cost|cash)\w*\b", re.I),
     "financial_review"),
    (re.compile(r"\brisk\w*\b", re.I), "risk_review"),
    (re.compile(r"\b(day ?1|cutover|go[- ]live|readiness)\b", re.I),
     "readiness_assessment"),
    (re.compile(r"\b(decision|approval|approve)\w*\b", re.I), "decision_paper"),
    (re.compile(r"\bworkstream\b", re.I), "workstream_review"),
)

_SENIORITY = (
    (re.compile(r"\b(board|supervisory)\b", re.I), "board"),
    (re.compile(r"\b(steerco|steering committee|exco|cfo|ceo|cio|coo|"
                r"executive)\b", re.I), "executive"),
    (re.compile(r"\b(imo|pmo|workstream lead|manager)\b", re.I), "management"),
)


def fallback_brief(context: GenerationContext) -> OutputBrief:
    """A usable brief with no model. Deliberately plain, never dressed up."""
    request = context.user_request or ""

    kind = "status_report"
    for pattern, candidate in _KIND_PATTERNS:
        if pattern.search(request):
            kind = candidate
            break

    seniority = "executive"
    for pattern, candidate in _SENIORITY:
        if pattern.search(request):
            seniority = candidate
            break

    audience = context.audience or _default_audience(seniority)
    length = "tight" if re.search(r"\b(short|brief|quick|one[- ]pager)\b",
                                  request, re.I) else "standard"

    brief = OutputBrief(
        document_kind=kind,                                      # type: ignore[arg-type]
        primary_format=(context.requested_output_format or "pptx"),  # type: ignore[arg-type]
        audience_label=audience,
        audience_seniority=seniority,                            # type: ignore[arg-type]
        reader_goal=(f"Understand the current state of "
                     f"{context.display_name()} and what needs deciding."),
        scope_topics=list(context.requested_sections),
        length_hint=length,                                      # type: ignore[arg-type]
        title_proposal=context.display_name(),
    )
    if not brief.scope_topics:
        brief.scope_topics = (_CONVENTIONAL_TOPICS.get(kind)
                              or _topics_from_evidence(context))
    return brief


def _default_audience(seniority: str) -> str:
    return {"board": "Board", "executive": "Steering Committee",
            "management": "Integration Management Office",
            "operational": "Workstream leads"}.get(seniority, "Steering Committee")


#: Evidence kinds that are worth a section when nobody said what to cover, in
#: the order a reader would want them. Not a report template — a last resort
#: that applies only when there is no request to plan from.
_FALLBACK_TOPIC_ORDER = (
    ("risk", "Open risks"),
    ("issue", "Open issues"),
    ("milestone", "Milestones and dates"),
    ("task", "Activity status"),
    ("budget", "Budget position"),
    ("synergy", "Synergy realisation"),
    ("decision", "Decisions required"),
    ("dependency", "Cross-workstream dependencies"),
    ("workstream", "Workstream status"),
    ("kpi", "Key indicators"),
)


#: What a document of this kind conventionally contains when the user named no
#: sections. This is *not* `DECKS` returning: it is a property of the brief, it
#: applies only where the request itself was silent, and any planner — model or
#: not — may retitle, reorder and group these afterwards. The SteerCo list is
#: §20.12, which is a statement about what a Steering Committee is owed rather
#: than a preference of this engine's.
_CONVENTIONAL_TOPICS: dict[str, list[str]] = {
    "steerco_pack": [
        "Executive Summary",
        "Overall Integration Status",
        "Workstream Status",
        "Key Milestones",
        "Critical Risks and Issues",
        "Financial Status: synergies and budget",
        "Decisions Required",
        "Recommended Next Steps",
    ],
}


def _topics_from_evidence(context: GenerationContext) -> list[str]:
    kinds = context.evidence.kinds
    return [label for kind, label in _FALLBACK_TOPIC_ORDER if kinds.get(kind)]


def summarize(brief: OutputBrief) -> str:
    """One line for a log or a chat reply."""
    pages = f", ~{brief.target_page_count} pages" if brief.target_page_count else ""
    return (f"{brief.document_kind.replace('_', ' ')} as {brief.primary_format} "
            f"for {brief.audience_label or 'an unnamed reader'}"
            f"{pages}; {len(brief.scope_topics)} topics")
