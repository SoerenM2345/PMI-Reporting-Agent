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
        from app.llm import reasoning_model

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
            model=reasoning_model(),
            max_tokens=6000,
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
        from app.llm import reasoning_model

        def fallback_updated():
            """Fallback if LLM unavailable: return current content unchanged."""
            return current_content

        updated = tasks.run_task(
            "regenerate.document",
            system=_SYSTEM_PROMPT,
            user=prompt,
            output_model=GeneratedContent,
            model=reasoning_model(),
            max_tokens=6000,
            fallback=fallback_updated,
        )
        return updated, warnings
    except Exception as exc:
        log.exception("LLM regeneration failed: %s", exc)
        warnings.append(f"Content regeneration failed: {str(exc)}")
        return current_content, warnings


_SYSTEM_PROMPT = """You are a PMI business analyst generating executive reports.

MISSION: Create clear, actionable insight-driven reports for steering committees.

KEY RULES:
1. Analyze the data - extract patterns, identify risks, show business impact
2. Generate recommendations - what should leadership decide or do?
3. Show trade-offs - present alternatives when options exist in the data
4. Connect impacts - link decisions to synergies, costs, timelines, risks
5. Ground everything in the data - no invented numbers, but aggressive analysis
6. No empty sections - every section must have substantive content with real insights

CONTENT FOCUS:
- Financial: Costs, synergies, capex/opex, timeline impacts, financial risks
- Risks: Business impact, consequences, mitigation strategies, dependencies
- Recommendations: Evidence-based options with pros/cons for each
- Strategic: How tactical decisions affect business outcomes
- Decisions: What needs to be decided, by when, and why

STYLE: Professional, clear POV, evidence-backed, actionable. Executives should know what to do after reading.

Return only valid JSON. Include 5-8 substantive sections. NO EMPTY SECTIONS."""


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
        "Analyze these files for patterns, decisions, risks, impacts, and strategic implications:",
        "",
        file_text[:50000],  # Optimized token size
        "",
        "## What to Generate",
        """Generate 5-8 sections: key insights, financial analysis, risks & mitigations, recommendations, dependencies, decisions, next steps.

KEY RULES:
✓ NO EMPTY SECTIONS - every section must have substantive content
✓ Use real data from files (numbers, dates, quotes)
✓ Show business impact - why this matters to leadership
✓ Present alternatives with trade-offs and reasoning
✓ Professional prose, evidence-backed, actionable

SECTION TYPES:
- Insights: What does the data mean? Business implications?
- Financial: Costs, synergies, capex/opex, timeline impacts
- Risks: Business consequences, mitigation strategies
- Recommendations: What should leadership decide? Why?
- Dependencies: What must happen first? Sequence and bottlenecks?
- Decisions: What needs approval? Timeline?
- Next Steps: Concrete actions, owners, deadlines from the files
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
        file_text[:80000],  # Increased from 30k for better analysis
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
