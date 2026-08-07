"""Generate PMI report content from uploaded source documents.

The generator intentionally separates:
1. source facts (must be traceable to uploaded material),
2. derived insights (reasoned implications from those facts), and
3. consultant recommendations (professional judgment, clearly labelled).

This allows the agent to behave like a senior PMI consultant without inventing
project facts that are not present in the files.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.generation.content_schema import GeneratedContent
from app.llm import tasks

log = logging.getLogger("pmi.generation.llm_generator")

# Large source packs should be analyzed in chunks instead of silently cutting off
# everything after a fixed character limit.
_SOURCE_CHUNK_CHARS = 42_000
_SOURCE_CHUNK_OVERLAP = 2_000


class SourceAnalysis(BaseModel):
    """Structured evidence extracted from one source chunk."""

    source_scope: str = ""
    factual_evidence: list[str] = Field(default_factory=list)
    workstreams: list[str] = Field(default_factory=list)
    milestones: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    risks_and_issues: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    financials: list[str] = Field(default_factory=list)
    synergies: list[str] = Field(default_factory=list)
    people_and_change: list[str] = Field(default_factory=list)
    data_quality_concerns: list[str] = Field(default_factory=list)
    potential_insights: list[str] = Field(default_factory=list)


class EvidenceSynthesis(BaseModel):
    """Cross-document synthesis used as the evidence base for report generation."""

    project_picture: list[str] = Field(default_factory=list)
    workstreams: list[str] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    milestones: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    risks_and_issues: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    financials: list[str] = Field(default_factory=list)
    synergy_evidence: list[str] = Field(default_factory=list)
    synergy_insights: list[str] = Field(default_factory=list)
    management_insights: list[str] = Field(default_factory=list)
    possible_recommendations: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)


def _detect_content_themes(file_text: str) -> list[str]:
    """Detect high-level PMI themes to guide, not constrain, the analysis."""
    themes: list[str] = []
    text_lower = file_text.lower()

    theme_keywords = {
        "financial_analysis": [
            "cost", "capex", "opex", "budget", "saving", "million", "euro", "usd",
            "run-rate", "one-off", "investment", "business case",
        ],
        "synergy_management": [
            "synergy", "synergies", "value creation", "benefit", "revenue uplift",
            "cost takeout", "baseline", "target", "actual", "realization",
        ],
        "risk_management": [
            "risk", "issue", "mitigation", "escalation", "raid", "exposure", "blocker",
        ],
        "schedule_planning": [
            "milestone", "timeline", "schedule", "gate", "week", "month", "deadline",
            "day 1", "day-1", "100-day", "go-live", "tsa exit",
        ],
        "technical_analysis": [
            "system", "erp", "it", "technical", "migration", "application", "data",
            "infrastructure", "cyber", "architecture",
        ],
        "organizational_change": [
            "team", "role", "organization", "resource", "governance", "raci", "talent",
            "culture", "change", "communication", "headcount",
        ],
        "operations": [
            "operations", "manufacturing", "plant", "production", "supply chain",
            "procurement", "vendor", "logistics", "inventory",
        ],
        "commercial": [
            "sales", "customer", "commercial", "pricing", "cross-sell", "revenue",
            "market", "product", "channel",
        ],
        "decision_analysis": [
            "recommend", "option", "decision", "approve", "strategy", "approval",
            "steerco", "steering committee",
        ],
    }

    for theme, keywords in theme_keywords.items():
        if any(keyword in text_lower for keyword in keywords):
            themes.append(theme)

    return themes


def _split_source_text(file_text: str) -> list[str]:
    """Split the complete source pack while preserving overlap between chunks."""
    text = file_text.strip()
    if not text:
        return []
    if len(text) <= _SOURCE_CHUNK_CHARS:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + _SOURCE_CHUNK_CHARS, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - _SOURCE_CHUNK_OVERLAP, start + 1)
    return chunks


_CHUNK_ANALYSIS_SYSTEM_PROMPT = """You are a senior Post-Merger Integration consultant performing evidence extraction.

Your job is to READ THE ENTIRE PROVIDED CHUNK and preserve management-relevant detail.
Do not write a final report yet.

Rules:
- Extract specific facts, numbers, dates, owners, statuses, milestones, decisions, risks,
  dependencies, synergy information, and workstream context.
- Do not discard qualitative information simply because it cannot be normalized into a KPI.
- Preserve important narrative information from meeting notes, PowerPoint commentary,
  assumptions, issues, and action descriptions.
- If the chunk contains a source/document/slide/sheet identifier, retain it in the extracted item.
- Never invent a project fact.
- You MAY identify a potential implication, but phrase it as an inference, not as a source fact.
- Pay special attention to synergy evidence: baseline, target, initiative, owner, timing,
  one-off cost, run-rate benefit, actual/forecast, dependency, risk, leakage, and confidence.
- Capture contradictions and incomplete information under data_quality_concerns.

Return only valid structured output."""


_SYNTHESIS_SYSTEM_PROMPT = """You are a senior PMI engagement manager synthesizing evidence across multiple source documents.

Build a complete cross-document view before report writing.

IMPORTANT DISTINCTION:
1. KEY FACTS = directly supported by source analyses.
2. MANAGEMENT INSIGHTS = reasoned implications derived from facts.
3. POSSIBLE RECOMMENDATIONS = consultant judgment based on the evidence.

Never convert an inference into a fact. Never invent missing numbers, owners, dates, statuses,
or synergy values. If evidence is incomplete, make the gap explicit.

For synergies, assess the value-creation story wherever evidence allows:
- target vs. identified initiatives,
- identified vs. validated initiatives,
- validated vs. realized/forecast value,
- timing to run-rate,
- implementation cost,
- owner/accountability,
- dependencies and leakage risks,
- confidence of realization.

Also look for cross-workstream patterns, bottlenecks, recurring root causes, critical path,
decision delays, resource constraints, governance weaknesses, and opportunities to accelerate value.

Return only valid structured output."""


_SYSTEM_PROMPT = """You are a senior Post-Merger Integration consultant preparing decision-ready management reporting.

Your role is NOT to merely repeat extracted data. Your role is to understand the integration,
find the management story, explain why it matters, and recommend what leaders should do next.

WORK IN THREE EVIDENCE LEVELS:
A. SOURCED FACTS
   - Numbers, dates, owners, project statuses, milestones, targets and events must come from the evidence.
   - Never invent missing project data.

B. DERIVED PMI INSIGHTS
   - You may infer implications, patterns, root causes, priority areas, bottlenecks, critical-path effects,
     synergy-at-risk signals and likely management consequences from the sourced facts.
   - Phrase these as analysis (e.g. "This suggests...", "The evidence indicates...", "This creates a risk that...").

C. CONSULTANT RECOMMENDATIONS
   - Recommend actions, governance interventions, sequencing, escalation, validation steps and decision paths.
   - Recommendations do not need to appear verbatim in a source file, but they MUST respond to evidence in the files.
   - Clearly distinguish recommendations from established facts.

PMI LENSES TO APPLY WHEN RELEVANT:
- Integration governance / IMO / PMO effectiveness
- Integration strategy and degree of integration
- Day-1 / 100-day / milestone readiness
- Target Operating Model and organizational design
- Workstream execution and cross-functional dependencies
- Value creation and synergy management
- Financial impact and implementation cost
- Risks, issues, decisions and escalation needs
- People, culture, change and communication
- Technology, data, applications and TSA dependencies
- Business continuity / customer / operational impact

SYNERGY ANALYSIS:
Do not just list synergy values. Evaluate the realization mechanism. Where the evidence permits,
connect target -> initiative -> owner -> timing -> cost-to-achieve -> dependency -> forecast/actual -> risk.
Highlight unvalidated value, missing ownership, delayed realization, double counting, weak baselines,
implementation-cost pressure, dependency risk and upside opportunities. If those fields are absent, say so.

CONSULTING COMMUNICATION:
- Answer first. Use a Minto/Pyramid-style storyline: governing message -> supporting insights -> evidence.
- Section titles should communicate conclusions, not generic topics (e.g. "ERP dependency puts Q4 synergy at risk"
  instead of "IT Status").
- Prioritize what requires management attention; do not dump every fact with equal weight.
- Still cover all material workstreams and material information from the evidence base.
- Explain cause -> consequence -> required action.
- Quantify impact when the source data supports it.
- Be audience-specific and decision-oriented.
- Avoid generic PMI boilerplate that is not connected to the evidence.

OUTPUT QUALITY:
- Choose the number and structure of sections needed to answer the user's request; do not force a fixed template.
- Every section must contain substantive content.
- Include gaps/uncertainties only where they matter to interpretation or decisions.
- Do not fabricate RAG statuses. If no status is stated or defensibly inferable, describe the condition without assigning one.
- Return only valid JSON matching the requested schema."""


def _analyze_source_pack(
    file_text: str,
    request: str,
    *,
    audience: Optional[str] = None,
    project_context: Optional[str] = None,
) -> EvidenceSynthesis:
    """Read all source chunks and synthesize them into a report-ready evidence base."""
    from app.llm import fast_model

    chunks = _split_source_text(file_text)
    chunk_analyses: list[SourceAnalysis] = []

    for index, chunk in enumerate(chunks, start=1):
        def fallback_chunk() -> SourceAnalysis:
            return SourceAnalysis(source_scope=f"Chunk {index}: analysis unavailable")

        chunk_prompt = "\n".join([
            f"Chunk {index} of {len(chunks)}",
            f"User reporting request: {request}",
            f"Audience: {audience or 'Not explicitly specified'}",
            f"Project context: {project_context or 'Not provided'}",
            "",
            "SOURCE MATERIAL:",
            chunk,
        ])

        analysis = tasks.run_task(
            "generate.document.source_analysis",
            system=_CHUNK_ANALYSIS_SYSTEM_PROMPT,
            user=chunk_prompt,
            output_model=SourceAnalysis,
            model=fast_model(),
            max_tokens=4500,
            fallback=fallback_chunk,
        )
        chunk_analyses.append(analysis)

    def fallback_synthesis() -> EvidenceSynthesis:
        # A mechanical fallback is preferable to dropping the entire source pack.
        return EvidenceSynthesis(
            key_facts=[
                item
                for analysis in chunk_analyses
                for item in analysis.factual_evidence[:20]
            ],
            workstreams=[
                item
                for analysis in chunk_analyses
                for item in analysis.workstreams[:10]
            ],
            synergy_evidence=[
                item
                for analysis in chunk_analyses
                for item in analysis.synergies[:15]
            ],
            risks_and_issues=[
                item
                for analysis in chunk_analyses
                for item in analysis.risks_and_issues[:15]
            ],
            dependencies=[
                item
                for analysis in chunk_analyses
                for item in analysis.dependencies[:15]
            ],
            evidence_gaps=[
                item
                for analysis in chunk_analyses
                for item in analysis.data_quality_concerns[:15]
            ],
        )

    synthesis_prompt = "\n".join([
        f"User reporting request: {request}",
        f"Audience: {audience or 'Not explicitly specified'}",
        f"Project context: {project_context or 'Not provided'}",
        "",
        "CHUNK ANALYSES:",
        json.dumps([item.model_dump() for item in chunk_analyses], indent=2),
        "",
        "Synthesize the complete evidence base. Preserve material facts and cross-document contradictions.",
    ])

    return tasks.run_task(
        "generate.document.evidence_synthesis",
        system=_SYNTHESIS_SYSTEM_PROMPT,
        user=synthesis_prompt,
        output_model=EvidenceSynthesis,
        model=fast_model(),
        max_tokens=7000,
        fallback=fallback_synthesis,
    )


def generate_document(
    file_text: str,
    request: str,
    *,
    output_format: str = "PowerPoint",
    audience: Optional[str] = None,
    project_context: Optional[str] = None,
) -> tuple[GeneratedContent, list[str]]:
    """Generate consultant-style PMI content from the complete uploaded source pack."""
    warnings: list[str] = []

    if not file_text.strip():
        log.warning("generate_document called with empty file text")
        return GeneratedContent(
            title="No Data",
            subtitle="No files were provided",
            sections=[],
        ), ["No files were uploaded"]

    try:
        evidence = _analyze_source_pack(
            file_text=file_text,
            request=request,
            audience=audience,
            project_context=project_context,
        )

        prompt = _build_prompt(
            evidence=evidence,
            request=request,
            output_format=output_format,
            audience=audience,
            project_context=project_context,
            themes=_detect_content_themes(file_text),
        )

        # Keep the existing model factory so this file remains a drop-in replacement.
        # If your app exposes a stronger/default model, use it here for final synthesis
        # and keep fast_model() for the chunk-analysis stage only.
        from app.llm import fast_model

        def fallback_content() -> GeneratedContent:
            return GeneratedContent(
                title="Content Generation Unavailable",
                subtitle="LLM service temporarily unavailable",
                sections=[],
            )

        draft = tasks.run_task(
            "generate.document",
            system=_SYSTEM_PROMPT,
            user=prompt,
            output_model=GeneratedContent,
            model=fast_model(),
            max_tokens=14000,
            fallback=fallback_content,
        )
        return draft, warnings
    except Exception as exc:
        log.exception("LLM generation failed: %s", exc)
        warnings.append(f"Content generation failed: {exc}")
        return GeneratedContent(
            title="Generation Failed",
            subtitle=str(exc),
            sections=[],
        ), warnings


def regenerate_document(
    file_text: str,
    current_content: GeneratedContent,
    revision: str,
    *,
    output_format: str = "PowerPoint",
    audience: Optional[str] = None,
    project_context: Optional[str] = None,
) -> tuple[GeneratedContent, list[str]]:
    """Revise a report while re-checking the complete source evidence."""
    warnings: list[str] = []

    try:
        evidence = _analyze_source_pack(
            file_text=file_text,
            request=revision,
            audience=audience,
            project_context=project_context,
        )

        prompt = _build_revision_prompt(
            evidence=evidence,
            current_content=current_content,
            revision=revision,
            output_format=output_format,
            audience=audience,
            project_context=project_context,
        )

        from app.llm import fast_model

        def fallback_updated() -> GeneratedContent:
            return current_content

        updated = tasks.run_task(
            "regenerate.document",
            system=_SYSTEM_PROMPT,
            user=prompt,
            output_model=GeneratedContent,
            model=fast_model(),
            max_tokens=14000,
            fallback=fallback_updated,
        )
        return updated, warnings
    except Exception as exc:
        log.exception("LLM regeneration failed: %s", exc)
        warnings.append(f"Content regeneration failed: {exc}")
        return current_content, warnings


def _build_prompt(
    *,
    evidence: EvidenceSynthesis,
    request: str,
    output_format: str,
    audience: Optional[str],
    project_context: Optional[str],
    themes: list[str],
) -> str:
    """Build the final report-generation prompt from cross-document evidence."""
    parts = [
        "## Assignment",
        f"Create a professional {output_format} PMI management report.",
        f"User request: {request}",
        f"Target audience: {audience or 'Infer from the request and content'}",
        f"Project context: {project_context or 'Use only the evidence supplied below'}",
        f"Detected PMI themes: {', '.join(themes) if themes else 'No dominant theme detected'}",
        "",
        "## Cross-document evidence base",
        json.dumps(evidence.model_dump(), indent=2),
        "",
        "## Reporting task",
        "Build the management story rather than reproducing the evidence list.",
        "",
        "For every material topic, use this logic where useful:",
        "- WHAT: What does the evidence establish?",
        "- SO WHAT: Why does it matter for integration, value creation, timing, risk, or management?",
        "- NOW WHAT: What decision/action/validation is recommended?",
        "",
        "Coverage requirements:",
        "- Address all material workstreams present in the evidence, even if the user did not name them individually.",
        "- Surface material qualitative information as well as normalized KPIs.",
        "- Prioritize critical decisions, dependencies, bottlenecks, unresolved issues and value-at-risk.",
        "- Include financial and synergy analysis whenever evidence exists.",
        "- For synergies, explain realization quality, not just the numeric target.",
        "- Identify upside opportunities and acceleration levers when supported by the project situation.",
        "- Explain contradictions or evidence gaps when they affect a conclusion.",
        "- Do not create fake RAG statuses, fake owners, fake dates or fake financial values.",
        "",
        "Recommended content areas (use only those relevant to the request):",
        "Executive message; integration progress; workstream insights; synergy realization; financial impact;",
        "critical milestones; risks/issues; dependencies; decisions required; people/change; technology/TSA;",
        "management recommendations; next actions; data gaps requiring validation.",
        "",
        "## Output requirements",
        "Return ONLY JSON matching GeneratedContent.",
        "Use conclusion-led section titles. Make each section substantive and decision-useful.",
        "The title should communicate the governing message, not merely the document type.",
        "Where useful, explicitly label statements inside content as 'Evidence', 'Insight', and 'Recommendation'.",
    ]
    return "\n".join(parts)


def _build_revision_prompt(
    *,
    evidence: EvidenceSynthesis,
    current_content: GeneratedContent,
    revision: str,
    output_format: str,
    audience: Optional[str],
    project_context: Optional[str],
) -> str:
    """Build a revision prompt that preserves user edits but reuses full evidence."""
    parts = [
        "## Current report",
        json.dumps(current_content.model_dump(), indent=2),
        "",
        "## Revision request",
        revision,
        "",
        "## Target",
        f"Output format: {output_format}",
        f"Audience: {audience or 'Infer from current report and revision'}",
        f"Project context: {project_context or 'No additional context supplied'}",
        "",
        "## Complete evidence synthesis",
        json.dumps(evidence.model_dump(), indent=2),
        "",
        "## Revision rules",
        "- Treat the user's revision as an instruction/correction and preserve it unless it conflicts with a later explicit instruction.",
        "- Do not simply paraphrase the current report; improve the analysis using the evidence base.",
        "- Add material source information that the current report omitted.",
        "- Deepen cause-and-effect reasoning and management implications.",
        "- Strengthen synergy analysis: target, initiative quality, timing, costs, dependencies, realization risk and upside.",
        "- Add concrete recommendations tied to observed evidence.",
        "- Keep facts, derived insights and recommendations distinguishable.",
        "- Never invent missing project facts.",
        "- Return the COMPLETE revised report as GeneratedContent JSON only.",
    ]
    return "\n".join(parts)
