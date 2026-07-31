"""The conflict report and the data-quality report (spec §18.18, §18.19, §21.17).

These ship with **every** run, not only when the user asks. That is deliberate: the
deck states one number per fact, which is what a deck must do — and these two files
are where the arithmetic behind that number is shown. Without them the deck is an
assertion; with them it is a defensible position.

Markdown rather than Excel, because a conflict report exists to be read by a person
in a hurry, forwarded in an email, and diffed between weeks.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from app.agent.data_quality import summarize
from app.models.pmi import DataQualityReport, PMIDataModel, Severity

_SEVERITY_MARK = {
    Severity.CRITICAL: "🔴 CRITICAL",
    Severity.HIGH: "🟠 HIGH",
    Severity.MEDIUM: "🟡 MEDIUM",
    Severity.LOW: "⚪ LOW",
}


def write_conflict_report(model: PMIDataModel, out_dir: Path) -> Path:
    """Every disagreement between sources, what was decided, and why (§9)."""
    lines: list[str] = [
        "# PMI Conflict Report",
        "",
        f"**Project:** {model.project.project_name}  ",
        f"**Generated:** {date.today():%d-%m-%Y}  ",
        f"**Sources:** {', '.join(model.source_files) or 'none'}",
        "",
        "Where two uploaded files disagreed about the same fact. The report shows what "
        "each source said, which value was used, and on what authority.",
        "",
    ]

    unresolved = model.unresolved_conflicts()
    if unresolved:
        lines += [
            "> ⚠️ **This report contains unresolved conflicts.** The figures in the "
            "accompanying deck reflect one source's view, not an agreed position. "
            "Resolve them before distributing.",
            "",
        ]

    if not model.conflicts:
        lines += ["No cross-source conflicts were detected.", ""]
    else:
        lines += [
            f"## {len(model.conflicts)} conflict(s)",
            "",
        ]
        for conflict in sorted(
            model.conflicts,
            key=lambda c: list(_SEVERITY_MARK).index(c.severity),
        ):
            lines += [
                f"### {_SEVERITY_MARK[conflict.severity]} — {conflict.entity_key} "
                f"({conflict.field.replace('_', ' ')})",
                "",
                f"*Check {conflict.check_id}.* {conflict.message}",
                "",
                "| Source | Location | Value | Confidence |",
                "|---|---|---|---|",
            ]
            for item in conflict.evidence:
                ref = item.source_reference
                lines.append(
                    f"| {ref.file_name} | {ref.location or '—'} | **{item.value}** | "
                    f"{ref.extraction_confidence:.0%} |"
                )

            lines.append("")
            if conflict.is_resolved:
                lines.append(
                    f"**Resolved to `{conflict.resolved_value}`** "
                    f"(from {conflict.resolved_from}, via {conflict.resolution}). "
                    f"{conflict.resolution_note or ''}"
                )
            else:
                lines.append(
                    "**UNRESOLVED — awaiting a decision.** "
                    f"{conflict.resolution_note or ''}"
                )
            lines.append("")

    path = out_dir / f"conflict_report_{date.today().isoformat()}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_quality_report(
    model: PMIDataModel, report: DataQualityReport, out_dir: Path
) -> Path:
    """What this run could and could not do (§21.17)."""
    lines: list[str] = [
        "# PMI Data-Quality Report",
        "",
        f"**Project:** {model.project.project_name}  ",
        f"**Generated:** {date.today():%d-%m-%Y}  ",
        f"**Score:** {report.score:.0f} / 100",
        "",
        "## Summary",
        "",
    ]
    lines += [f"- {line}" for line in summarize(report)]
    lines.append("")

    # --- what we could not read ---------------------------------------------
    if report.failed_files:
        lines += [
            "## Files that could NOT be read",
            "",
            "These contributed **nothing** to the report. Anything they contained is "
            "missing from it.",
            "",
        ]
        lines += [f"- `{f}`" for f in report.failed_files]
        lines.append("")

    # --- low-confidence findings (§5.6) --------------------------------------
    low = model.low_confidence_items()
    if low:
        lines += [
            "## Low-confidence findings — please review",
            "",
            "Read from an image, a scan or a photo. Verify each against the source "
            "system before relying on it.",
            "",
            "| Type | Item | Confidence | Read from |",
            "|---|---|---|---|",
        ]
        for kind, label, confidence in sorted(low, key=lambda x: x[2]):
            where = _where(model, kind, label)
            lines.append(f"| {kind} | {label} | {confidence:.0%} | {where} |")
        lines.append("")

    # --- validation issues (§8.2-8.4) ---------------------------------------
    if model.validation_issues:
        lines += [f"## {len(model.validation_issues)} validation issue(s)", ""]
        for family in ("mathematical", "temporal", "completeness"):
            issues = [i for i in model.validation_issues if i.family == family]
            if not issues:
                continue
            lines += [f"### {family.title()} ({len(issues)})", ""]
            for issue in sorted(
                issues, key=lambda i: list(_SEVERITY_MARK).index(i.severity)
            ):
                correction = (
                    f" → corrected to **{issue.corrected_value}**"
                    if issue.corrected_value else ""
                )
                lines.append(
                    f"- {_SEVERITY_MARK[issue.severity]} `{issue.check_id}` "
                    f"{issue.message}{correction}"
                )
            lines.append("")

    # --- caveats -------------------------------------------------------------
    if report.warnings:
        lines += [
            "## Processing caveats",
            "",
            "Things that went differently than intended. Each one means the report is "
            "thinner than it looks.",
            "",
        ]
        lines += [f"- {w}" for w in report.warnings]
        lines.append("")

    lines += [
        "---",
        "",
        "*Generated outputs are a prototype and require Senior Manager review before "
        "distribution to stakeholders.*",
    ]

    path = out_dir / f"data_quality_report_{date.today().isoformat()}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _where(model: PMIDataModel, kind: str, label: str) -> str:
    collections = {
        "task": (model.tasks, "title"), "milestone": (model.milestones, "name"),
        "risk": (model.risks, "title"), "issue": (model.issues, "title"),
        "budget": (model.budget, "category"), "synergy": (model.synergies, "title"),
        "kpi": (model.kpis, "name"),
        "dependency": (model.dependencies, "description"),
        "decision": (model.decisions, "title"),
    }
    entry = collections.get(kind)
    if not entry:
        return "—"

    items, attr = entry
    for item in items:
        if getattr(item, attr, None) == label and item.primary_source:
            return item.primary_source.cite()
    return "—"
