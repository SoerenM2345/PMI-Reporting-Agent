"""Plan the entire consulting report in one structured model call.

The previous pipeline asked separately for a brief, storyline, page design,
visuals, page copy and titles. That made latency proportional to the number of
stages and slides, while each isolated call saw less context than the report
needed. This module gives one model the whole editorial problem. Python still
validates evidence ids, restores required sections, binds template layouts and
resolves every displayed value.
"""
from __future__ import annotations

from app.context.schemas import GenerationContext
from app.evidence.retrieval import pack, retrieve
from app.llm import prompts, reasoning_model, tasks
from app.planning import request_interpreter, storyline, visual_planner
from app.planning.schemas import (
    CompleteReportPlan,
    DocumentTitles,
    PageCopy,
    PageTitle,
)


def plan(context: GenerationContext) -> CompleteReportPlan:
    """One model request, or one completely deterministic fallback."""
    fallback = fallback_plan(context)
    return tasks.run_task(
        "plan.complete_report",
        system=prompts.compose("_grounding_rules", "plan_complete_report"),
        user=_payload(context, fallback),
        output_model=CompleteReportPlan,
        model=reasoning_model(),
        max_tokens=_max_tokens(),
        fallback=lambda: fallback,
    )


def fallback_plan(context: GenerationContext) -> CompleteReportPlan:
    brief = request_interpreter.fallback_brief(context)
    retrieval = storyline.retrieve_for(context, brief)
    story = storyline.fallback_storyline(context, brief, retrieval)
    design = visual_planner.fallback_design(context, brief, story)
    copies = [
        PageCopy(
            page_id=page.page_id,
            message_title=page.message_title,
            supporting_message=page.supporting_message,
        )
        for page in design.pages
    ]
    return CompleteReportPlan(
        brief=brief,
        storyline=story,
        design=design,
        page_copy=copies,
        titles=DocumentTitles(
            document_title=brief.title_proposal or context.display_name(),
            document_subtitle=context.subject_line(),
            titles=[
                PageTitle(page_id=p.page_id, title=p.message_title,
                          subtitle=p.supporting_message)
                for p in design.pages
            ],
        ),
    )


def _payload(context: GenerationContext,
             fallback: CompleteReportPlan) -> str:
    brief = fallback.brief
    query = " ".join([
        context.user_request,
        context.project_name,
        context.project_context,
        *context.requested_sections,
        *context.requested_visuals,
    ])
    found = retrieve(
        query, context.evidence, k=_top_k(brief),
        reporting_date=context.reporting_date,
        named_terms=[*context.company_names.known,
                     *context.requested_sections],
    )
    packed = pack(found, budget_chars=_evidence_budget())
    evidence = getattr(packed, "text", str(packed))

    compositions = (
        "single, two_column, three_column, four_column, hero_chart, "
        "chart_plus_commentary, matrix, table_full, kpi_banner, full_bleed, quote"
    )

    parts = [
        prompts.data_block("current_user_request", context.user_request),
        prompts.data_block("project_name", context.project_name),
        prompts.data_block("project_context", context.project_context),
        prompts.data_block(
            "confirmed_user_knowledge",
            context.project_knowledge.as_markdown()),
        prompts.data_block("recent_chat", _chat(context)),
        "Audience: " + (context.audience or "not explicitly named"),
        "Requested output: " + (context.requested_output_format or "not stated"),
        "Required sections: " + (
            " | ".join(context.requested_sections) or "none explicitly listed"),
        "Requested visuals: " + (
            ", ".join(context.requested_visuals) or "none explicitly listed"),
        "Available page compositions: " + compositions,
        prompts.data_block("validated_evidence", evidence, limit=_evidence_budget()),
    ]
    return "\n\n".join(part for part in parts if part)


def _chat(context: GenerationContext) -> str:
    lines = [context.chat_summary] if context.chat_summary else []
    lines.extend(
        f"{item.role}: {item.text}"
        for item in context.relevant_chat_messages
        if item.text
    )
    return "\n".join(lines)


def _top_k(brief) -> int:
    return {"tight": 40, "standard": 70, "thorough": 110}.get(
        brief.length_hint, 70)


def _evidence_budget() -> int:
    from app.config import get_settings

    return get_settings().planning_evidence_budget_chars


def _max_tokens() -> int:
    from app.config import get_settings

    return get_settings().llm_max_output_tokens_planning
