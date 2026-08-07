"""Generate document content using LLM directly from file text."""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.generation.content_schema import GeneratedContent
from app.llm import tasks

log = logging.getLogger("pmi.generation.llm_generator")


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
        draft = tasks.run_task(
            "generate.document",
            system=_SYSTEM_PROMPT,
            user=prompt,
            output_model=GeneratedContent,
            model=reasoning_model(),
            max_tokens=4096,
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
        updated = tasks.run_task(
            "regenerate.document",
            system=_SYSTEM_PROMPT,
            user=prompt,
            output_model=GeneratedContent,
            model=reasoning_model(),
            max_tokens=4096,
        )
        return updated, warnings
    except Exception as exc:
        log.exception("LLM regeneration failed: %s", exc)
        warnings.append(f"Content regeneration failed: {str(exc)}")
        return current_content, warnings


_SYSTEM_PROMPT = """You are a professional report generator for post-merger integration projects.

Your job is to create clear, actionable reports from uploaded PMI data.

IMPORTANT RULES:
1. Only cite data that appears in the uploaded files
2. If a number is not in the files, do not include it
3. If data is missing, note it naturally in the text (e.g., "Timeline details are not provided in current files")
4. Create natural, flowing prose - not templated or generic
5. Adapt content style and depth for the audience
6. Output only valid JSON matching the GeneratedContent schema
7. Do not add commentary outside the JSON response

Generate reports that reflect the actual data, not normalized or standardized versions."""


def _build_prompt(
    file_text: str,
    request: str,
    output_format: str,
    audience: Optional[str],
    project_context: Optional[str],
) -> str:
    """Build the generation prompt."""
    parts = [
        "## Task",
        f"Generate a {output_format} report based on uploaded files.",
        f"User request: {request}",
        "",
    ]

    if audience:
        parts.append(f"Target audience: {audience}")

    if project_context:
        parts.append(f"Project context: {project_context}")

    parts.extend([
        "",
        "## Uploaded Files",
        file_text[:50000],  # Limit to first 50k chars
        "",
        "## Output Format",
        """Return ONLY valid JSON matching this structure:
{
  "title": "string - main document title",
  "subtitle": "string - optional subtitle",
  "sections": [
    {
      "id": "unique_id",
      "title": "section title",
      "type": "text|bullets|table|chart",
      "content": "string for text, array of strings for bullets, array of arrays for table",
      "metadata": {"audience": "string", "emphasis": "high|medium|low"}
    }
  ],
  "metadata": {
    "audience": "string",
    "reporting_date": "YYYY-MM-DD",
    "document_type": "string"
  }
}

Requirements:
- Include 4-8 sections
- Use actual data from files only
- Make content natural and contextual (not templated)
- Sections should address key PMI topics: status, risks, milestones, decisions, next steps
""",
    ])

    return "\n".join(parts)


def _build_revision_prompt(
    file_text: str,
    current_content: GeneratedContent,
    revision: str,
    output_format: str,
    audience: Optional[str],
) -> str:
    """Build the revision prompt."""
    parts = [
        "## Current Report",
        json.dumps(current_content.model_dump(), indent=2),
        "",
        f"## Revision Request",
        revision,
        "",
        "## Source Data",
        file_text[:30000],  # Limit to first 30k chars
        "",
        "## Instructions",
        """Update the report based on the revision request.
Return the complete updated report in JSON format.
Keep the same structure but modify content as requested.
Only use data from the source files.""",
    ]

    if audience:
        parts.append(f"\nTarget audience: {audience}")

    return "\n".join(parts)
