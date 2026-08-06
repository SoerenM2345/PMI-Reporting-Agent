"""Develop the argument before anyone thinks about pages.

This is the call the product lives or dies on. Everything downstream — titles,
composition, charts, review — is execution; if the arc is weak, the result is
polished mediocrity. So it gets the reasoning model, a generous output budget,
and the most carefully written prompt in the system.

The output is an argument, not a table of contents. `DECKS[audience]` used to
answer "what sections does this reader get" with a seven-element list; this
answers "what is the one thing they must take away, and what establishes it",
and the sections fall out of that.

Coverage is enforced afterwards in Python. A model that drops a requested topic
is not overruled on editorial grounds — it is simply given the topic back as a
section it must place, because the user asked for it and the planner's licence
is to reorganise, never to remove.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

from app.context.schemas import GenerationContext
from app.evidence.model import EvidenceIndex
from app.evidence.retrieval import PackedEvidence, RetrievalResult, pack, retrieve
from app.llm import prompts, reasoning_model, tasks
from app.planning import messages
from app.planning.schemas import OutputBrief, SectionIntent, StorylinePlan

log = logging.getLogger("pmi.planning.storyline")


def develop(context: GenerationContext, brief: OutputBrief, *,
            retrieval: Optional[RetrievalResult] = None) -> StorylinePlan:
    """The governing message, the arguments under it, and the sections."""
    retrieval = retrieval or retrieve_for(context, brief)
    packed = pack(retrieval, budget_chars=_budget())

    plan = tasks.run_task(
        "plan.storyline",
        system=prompts.compose("_grounding_rules", "plan_storyline"),
        user=_payload(context, brief, packed),
        output_model=StorylinePlan,
        model=reasoning_model(),
        max_tokens=8192,
        fallback=lambda: fallback_storyline(context, brief, retrieval),
    )
    return plan


def retrieve_for(context: GenerationContext,
                 brief: OutputBrief) -> RetrievalResult:
    """Evidence for the whole document, ranked against the request."""
    query = " ".join([
        context.user_request,
        brief.reader_goal,
        *brief.scope_topics,
        *brief.decisions_sought,
    ])
    return retrieve(
        query, context.evidence,
        k=_top_k(brief),
        reporting_date=context.reporting_date,
        named_terms=[*context.company_names.known, *brief.scope_topics],
    )


def _top_k(brief: OutputBrief) -> int:
    return {"tight": 40, "standard": 70, "thorough": 110}.get(brief.length_hint, 70)


def _budget() -> int:
    from app.config import get_settings

    return getattr(get_settings(), "planning_evidence_budget_chars", 40_000)


def _payload(context: GenerationContext, brief: OutputBrief,
             packed: PackedEvidence) -> str:
    parts = [
        "## The ask",
        prompts.data_block("user_request", context.user_request),
        f"Document: {brief.document_kind.replace('_', ' ')} as "
        f"{brief.primary_format}, for {brief.audience_label or 'an unnamed reader'} "
        f"({brief.audience_seniority}).",
        f"What this reader must be able to do: {brief.reader_goal}"
        if brief.reader_goal else "",
    ]

    if brief.scope_topics:
        parts.append("Topics the document must cover, in the user's own words. "
                     "You may retitle, reorder or group them, and you may add "
                     "sections. You may not drop one:\n"
                     + "\n".join(f"- {t}" for t in brief.scope_topics))
    if brief.decisions_sought:
        parts.append("Decisions the reader is being asked to take:\n"
                     + "\n".join(f"- {d}" for d in brief.decisions_sought))
    if brief.excluded_topics:
        parts.append("The user asked you NOT to cover: "
                     + ", ".join(brief.excluded_topics))
    if brief.target_page_count:
        parts.append(f"Length: about {brief.target_page_count} pages. "
                     f"Plan sections that fit.")

    parts.append("## The project")
    if context.company_names.as_sentence():
        parts.append(context.company_names.as_sentence())
    if context.reporting_period:
        parts.append(f"Reporting period: {context.reporting_period}.")
    if context.transaction.days_to_day_1 is not None:
        parts.append(f"Day 1 is {context.transaction.days_to_day_1} days away "
                     f"(computed; you may refer to it, and cite no figure).")
    if context.project_context:
        parts.append(prompts.data_block("project_context", context.project_context))
    knowledge = context.project_knowledge.as_markdown()
    if knowledge:
        parts.append(prompts.data_block("project_knowledge", knowledge))
    if context.chat_summary:
        parts.append(prompts.data_block("chat_history", context.chat_summary))

    parts.append("## Evidence")
    parts.append(packed.disclosure)
    parts.append(prompts.data_block("evidence", packed.text, limit=200_000))

    conflicts = context.unresolved_critical_conflicts
    if conflicts:
        parts.append(f"{len(conflicts)} unresolved critical conflict(s) affect "
                     f"figures this document will state. The disagreement must "
                     f"appear in the document; do not present either value as "
                     f"settled.")
    return "\n\n".join(p for p in parts if p)


# ============================================================= keyless path
def fallback_storyline(context: GenerationContext, brief: OutputBrief,
                       retrieval: RetrievalResult) -> StorylinePlan:
    """A defensible arc with no model — and one that admits what it is.

    It orders sections by what the evidence says is urgent rather than by a
    fixed template, so two different projects still get different documents.
    What it cannot do is find a governing message, so it does not pretend to:
    the takeaway states the document's own provenance instead of inventing a
    conclusion nobody reasoned to.
    """
    sections: list[SectionIntent] = []
    evidence = context.evidence
    used: set[str] = set()

    for order, topic in enumerate(brief.scope_topics, start=1):
        ids = _evidence_for_topic(topic, evidence, retrieval)
        used.update(ids)
        sections.append(SectionIntent(
            section_id=_slug(topic) or f"section-{order}",
            working_title=topic,
            management_question=f"What is the position on {topic.lower()}?",
            # §12.5 does not stop applying because there is no model. The finding
            # is arithmetic over the evidence, which is Python's job anyway.
            intended_message=messages.for_section(topic, evidence.resolve(ids)),
            purpose=_purpose_for(topic),
            evidence_ids=ids,
            depth="summary",
            recommended_expression=_expression_for(topic, ids, evidence),
            covers_requested=[topic],
        ))

    required = [i for i in evidence.must_include() if i not in used]
    if required:
        sections.append(SectionIntent(
            section_id="must-disclose",
            working_title="Unresolved items requiring attention",
            management_question="What is disputed or unmitigated?",
            purpose="risk",
            evidence_ids=required,
            depth="detailed",
            recommended_expression="table",
            visual_priority="high",
        ))

    return StorylinePlan(
        governing_message=(f"Status of {context.display_name()}"
                           + (f" for {context.reporting_period}"
                              if context.reporting_period else "")),
        executive_takeaway="",
        situation="", complication="", question="",
        supporting_arguments=[],
        narrative_flow="by_severity",
        sections=sections,
    )


def _evidence_for_topic(topic: str, evidence: EvidenceIndex,
                        retrieval: RetrievalResult) -> list[str]:
    from app.evidence.retrieval import retrieve as _retrieve

    kinds = _topic_kinds(topic)
    hits = _retrieve(topic, evidence, kinds=kinds or None, k=24,
                     include_mandatory=False)
    # Project background belongs in the planning context and on the cover. It
    # is not a row in a topical status table. When a topic has no explicit kind
    # hint, BM25 otherwise ranks repeated words such as "integration" highly
    # and fills Infrastructure Migration or Application Landscape with the deal
    # description instead of operational evidence.
    from app.evidence.scoring import expand, tokenize

    topic_tokens = set(expand(tokenize(topic)))
    topical = [item for item in hits.included
               if item.kind not in ("context", "assumption")
               and topic_tokens & set(tokenize(item.search_text))]
    absence = evidence.get(f"ev:absence:{_slug(topic)}")
    if absence is not None and not topical:
        topical.append(absence)
    return [i.evidence_id for i in topical][:12]


_TOPIC_KIND_HINTS = (
    (re.compile(r"\b(infrastructure|migration|cutover|cloud|hosting|"
                r"data[ -]?cent(?:er|re))\b", re.I),
     ("task", "milestone", "dependency", "workstream", "status_update",
      "budget")),
    (re.compile(r"\b(application|landscape|system|interface|erp|crm)\b", re.I),
     ("task", "milestone", "dependency", "workstream", "status_update",
      "kpi")),
    (re.compile(r"\bmilestone|date|timeline|roadmap\b", re.I), ("milestone",)),
    (re.compile(r"\brisk|issue|concern\b", re.I), ("risk", "issue")),
    (re.compile(r"\bbudget|cost|spend|financial\b", re.I), ("budget",)),
    (re.compile(r"\bsynerg|saving|benefit\b", re.I), ("synergy",)),
    (re.compile(r"\bdecision|approval\b", re.I), ("decision",)),
    (re.compile(r"\bdependenc|cross-workstream\b", re.I), ("dependency",)),
    (re.compile(r"\bworkstream\b", re.I), ("workstream",)),
    (re.compile(r"\btask|activit|action\b", re.I), ("task",)),
)


def _topic_kinds(topic: str) -> tuple[str, ...]:
    for pattern, kinds in _TOPIC_KIND_HINTS:
        if pattern.search(topic or ""):
            return kinds
    return ()


_PURPOSE_HINTS = (
    (re.compile(r"\b(summary|overview|highlight)\b", re.I), "frame"),
    (re.compile(r"\b(risk|issue|concern)\w*\b", re.I), "risk"),
    (re.compile(r"\b(decision|approval|steerco)\w*\b", re.I), "decision"),
    (re.compile(r"\b(next step|action|recommend|plan|roadmap)\w*\b", re.I), "plan"),
    (re.compile(r"\b(analysis|variance|comparison|vs\.?)\b", re.I), "analysis"),
    (re.compile(r"\b(appendix|detail|backup)\b", re.I), "appendix"),
)


def _purpose_for(topic: str) -> str:
    for pattern, purpose in _PURPOSE_HINTS:
        if pattern.search(topic):
            return purpose
    return "evidence"


def _expression_for(topic: str, ids: Sequence[str],
                    evidence: EvidenceIndex) -> str:
    """Pick an expression from the shape of the evidence, not from the topic.

    Enough comparable numbers is a chart; a set of records with facets is a
    table; anything else is prose. Crude, and still better than "every section
    gets a table", which is what the old planner did.
    """
    items = evidence.resolve(ids)
    numeric = [i for i in items if isinstance(i.value, (int, float))]
    if re.search(r"\b(timeline|roadmap|milestone|schedule)\b", topic, re.I):
        return "sequence"
    if re.search(r"\b(matrix|heat ?map)\b", topic, re.I):
        return "matrix"
    if len(numeric) >= 3 and len({i.unit for i in numeric}) == 1:
        return "comparison"
    if len(items) >= 4:
        return "table"
    return "none"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").casefold()).strip("-")[:48]
