
"""Generate document content using LLM directly from file text."""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.generation.content_schema import GeneratedContent
from app.llm import tasks

log = logging.getLogger("pmi.generation.llm_generator")


def _detect_content_themes(file_text: str) -> list[str]:
    """Detect themes/topics in the uploaded files to guide analysis."""
    themes = []
    text_lower = file_text.lower()

    # Financial/Cost themes
    if any(word in text_lower for word in ["cost", "capex", "opex", "budget", "synerg", "savings", "million", "euro"]):
        themes.append("financial_analysis")

    # Risk themes
    if any(word in text_lower for word in ["risk", "issue", "mitigation", "escalation", "raid", "exposure"]):
        themes.append("risk_management")

    # Timeline/Milestone themes
    if any(word in text_lower for word in ["milestone", "timeline", "schedule", "gate", "week", "month", "deadline"]):
        themes.append("schedule_planning")

    # Technical/IT themes
    if any(word in text_lower for word in ["system", "erp", "it", "technical", "migration", "application"]):
        themes.append("technical_analysis")

    # Organizational/HR themes
    if any(word in text_lower for word in ["team", "role", "organization", "resource", "governance", "raci"]):
        themes.append("organizational_change")

    # Supply Chain themes
    if any(word in text_lower for word in ["supply chain", "procurement", "vendor", "logistics", "order"]):
        themes.append("supply_chain")

    # Decision/Strategy themes
    if any(word in text_lower for word in ["recommend", "option", "decision", "approve", "strategy", "approval"]):
        themes.append("decision_analysis")

    return themes


def generate_document(
    file_text: str,
    request: str,
    *,
    output_format: str = "PowerPoint",
    audience: Optional[str] = None,
    project_context: Optional[str] = None,
) -> tuple[GeneratedContent, list[str]]:
    """Generate document content from uploaded files using LLM.

    Args:
        file_text: Concatenated text from all uploaded files
        request: User's request (e.g., "Create a risk report for steering committee")
        output_format: Target format (PowerPoint, Excel, PDF, Word, etc.)
        audience: Target audience (Steering Committee, PMO, etc.)
        project_context: Additional context about the project

    Returns:
        (GeneratedContent, warnings)
    """
    warnings: list[str] = []

    if not file_text.strip():
        log.warning("generate_document called with empty file text")
        return GeneratedContent(
            title="No Data",
            subtitle="No files were provided",
            sections=[]
        ), ["No files were uploaded"]

    prompt = _build_prompt(
        file_text=file_text,
        request=request,
        output_format=output_format,
        audience=audience,
        project_context=project_context,
    )

    try:
        # Use fast model for multi-file analysis - prevents timeouts with large context
        from app.llm import fast_model

        def fallback_content():
            """Fallback if LLM unavailable: return structured placeholder."""
            return GeneratedContent(
                title="Content Generation Unavailable",
                subtitle="LLM service temporarily unavailable",
                sections=[]
            )

        draft = tasks.run_task(
            "generate.document",
            system=_SYSTEM_PROMPT,
            user=prompt,
            output_model=GeneratedContent,
            model=fast_model(),  # Fast model for better performance with large inputs
            max_tokens=10000,    # Comprehensive project overview
            fallback=fallback_content,
        )
        return draft, warnings
    except Exception as exc:
        log.exception("LLM generation failed: %s", exc)
        warnings.append(f"Content generation failed: {str(exc)}")
        return GeneratedContent(
            title="Generation Failed",
            subtitle=str(exc),
            sections=[]
        ), warnings


def regenerate_document(
    file_text: str,
    current_content: GeneratedContent,
    revision: str,
    *,
    output_format: str = "PowerPoint",
    audience: Optional[str] = None,
) -> tuple[GeneratedContent, list[str]]:
    """Regenerate document content based on user revision.

    Args:
        file_text: Original file text
        current_content: Current document content
        revision: User's revision request
        output_format: Target format
        audience: Target audience

    Returns:
        (Updated GeneratedContent, warnings)
    """
    warnings: list[str] = []

    prompt = _build_revision_prompt(
        file_text=file_text,
        current_content=current_content,
        revision=revision,
        output_format=output_format,
        audience=audience,
    )

    try:
        # Use fast model for revisions - prevents timeouts with large context
        from app.llm import fast_model

        def fallback_updated():
            """Fallback if LLM unavailable: return current content unchanged."""
            return current_content

        updated = tasks.run_task(
            "regenerate.document",
            system=_SYSTEM_PROMPT,
            user=prompt,
            output_model=GeneratedContent,
            model=fast_model(),  # Fast model for better performance with large inputs
            max_tokens=10000,    # Comprehensive project overview
            fallback=fallback_updated,
        )
        return updated, warnings
    except Exception as exc:
        log.exception("LLM regeneration failed: %s", exc)
        warnings.append(f"Content regeneration failed: {str(exc)}")
        return current_content, warnings


_SYSTEM_PROMPT = """You are a senior PMI analyst generating comprehensive strategic reports for steering committees.

MISSION: Transform PMI files into comprehensive, insightful reports covering full project scope with all workstreams.

KEY PRINCIPLES:
1. Analyze all workstreams/functions mentioned in the files (IT, Finance, Supply Chain, HR, Operations, etc.)
2. Quantify financial impacts: costs, synergies, capex/opex, timeline implications
3. Present decision frameworks: options with trade-offs and recommended path
4. Connect risks to business consequences and mitigation strategies
5. Show dependencies, critical path, and bottlenecks
6. No empty sections - every section substantive and insightful

CONTENT FOCUS: Executive summary, project status by workstream, financial overview, key decisions, risks, dependencies, recommendations, next steps, strategic implications.

STYLE: Strategic, evidence-backed, actionable. Leadership should grasp full project picture and know what to decide.

Return only valid JSON. Reports should have 10-15 substantive sections with significant content depth."""


def _build_prompt(
    file_text: str,
    request: str,
    output_format: str,
    audience: Optional[str],
    project_context: Optional[str],
) -> str:
    """Build the generation prompt with rich guidance for insight generation."""
    themes = _detect_content_themes(file_text)

    parts = [
        "## Your Assignment",
        f"Generate a comprehensive {output_format} report based on uploaded PMI files.",
        f"User request: {request}",
        "",
    ]

    if audience:
        parts.append(f"Target audience: {audience}")
        parts.append("(Tailor insights and language for this audience's priorities)")

    if project_context:
        parts.append(f"Project context: {project_context}")

    if themes:
        parts.append("")
        parts.append(f"Detected content areas: {', '.join(themes)}")
        parts.append("(Generate analysis for these areas)")

    parts.extend([
        "",
        "## Source Documents",
        "Analyze these files for all workstreams, decisions, financial impacts, risks, and strategic implications:",
        "",
        file_text[:70000],  # Optimized for comprehensive analysis without timeouts
        "",
        "## Generate Comprehensive Report",
        """Create 10-15 substantive sections covering the full project:

1. Executive Summary: 3-5 critical insights
2. Project Status by Workstream: all mentioned workstreams with RAG status
3. Financial Overview: costs, synergies, capex/opex, budget impact
4. Key Decisions: what needs approval and timeline
5. Decision Options: alternatives with trade-offs
6. Risk Assessment: risks with business consequences and mitigation
7. Critical Dependencies: sequencing and critical path
8. Stakeholder/Workstream Impact: effects on each area
9. Factors Influencing Key Financial Decisions: constraints and trade-offs
10. Synergy Realization: value creation path
11. Next Steps: actions, owners, deadlines
12. Timeline & Milestones: critical dates
13. Recommendations: path forward

CRITICAL: Every section must be substantive. Use real numbers/dates from files.
Cover ALL workstreams/functions mentioned. Show business impact and implications.
""",
        "",
        "## JSON Output",
        """Return ONLY this JSON structure (no other text):
{
  "title": "Main insight or recommendation",
  "subtitle": "Key message",
  "sections": [{
    "id": "sec1",
    "title": "Section title (specific, not generic)",
    "type": "text",
    "content": "Substantive content - analysis, insights, recommendations with business impact",
    "metadata": {"audience": "%s", "emphasis": "high"}
  }],
  "metadata": {
    "audience": "%s",
    "reporting_date": "2024-01-01",
    "document_type": "Analysis"
  }
}

Remember: NO EMPTY CONTENT. Every section must have real, substantive text based on the files.
""" % (audience or "Leadership", audience or "Leadership"),
    ])

    return "\n".join(parts)


def _build_revision_prompt(
    file_text: str,
    current_content: GeneratedContent,
    revision: str,
    output_format: str,
    audience: Optional[str],
) -> str:
    """Build the revision prompt with guidance for deeper analysis."""
    parts = [
        "## Current Report",
        json.dumps(current_content.model_dump(), indent=2),
        "",
        f"## Revision Request",
        revision,
        "",
        "## Source Data (Full Context)",
        file_text[:70000],  # Optimized context for comprehensive analysis
        "",
        "## Your Task",
        """Update the report based on the revision request while maintaining quality standards.

REVISION GUIDELINES:
1. Keep substantive content - don't just shorten, add depth
2. If asked for "more detail" or "more insights":
   - Dig deeper into trade-offs, implications, risks
   - Add specific numbers and timelines from files
   - Show cause-and-effect relationships
   - Connect to business outcomes (costs, synergies, timeline impact)

3. If asked for "financial insights" or "impact":
   - Analyze costs, capex/opex, synergy impacts
   - Show timeline and resource implications
   - Connect to decisions and recommendations
   - Never leave this empty

4. Maintain evidence-based analysis:
   - All claims trace to source files
   - Show numbers, dates, specific references
   - Present trade-offs and alternatives when relevant

5. Keep structure consistent but enhance content quality

Return complete updated report in JSON format.""",
    ]

    if audience:
        parts.append(f"\nTarget audience: {audience}")
        parts.append("Ensure insights are relevant to this audience's priorities.")

    return "\n".join(parts)
