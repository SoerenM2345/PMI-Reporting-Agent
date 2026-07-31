"""Export a saved draft to PowerPoint, Word, PDF, HTML, Excel or Markdown.

The rule that governs this file: **an export shows the text the user approved.**
It never independently regenerates a different narrative (Scenario 6). Where a
section has been hand-edited, that edit is overlaid onto the planned deliverable
before rendering, and where a whole draft has been replaced the Markdown is
written out verbatim.

What changed: the binary formats used to be built by re-parsing the draft's
Markdown into a small document model, which discarded cell provenance, emphasis,
column types and every chart on the way out — so a "chart" became the line
`Chart: Workstream Progress`. They now render from the `Deliverable` the draft was
planned from, via `app/renderers/`, so the exported deck is the designed artifact.

Exporting is an **audit** action: it logs a `draft_export` event and never changes
knowledge or the draft.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from app.project import docmodel, paths
from app.project.docmodel import DocSection, NormalizedDoc
from app.project.json_repositories import Repositories, default_repositories
from app.project.models import AuditEvent, DraftRecord

log = logging.getLogger("pmi.project.export")

FORMATS = {
    "markdown": ".md", "md": ".md", "html": ".html",
    "word": ".docx", "docx": ".docx", "powerpoint": ".pptx", "pptx": ".pptx",
    "pdf": ".pdf", "excel": ".xlsx", "xlsx": ".xlsx",
}


class ExportError(RuntimeError):
    """The draft could not be exported (unknown draft or format)."""


def export_draft(project_id: str, draft_id: str, fmt: str, *,
                 repos: Optional[Repositories] = None,
                 chat_id: Optional[str] = None) -> Path:
    """Export the latest saved version of a draft. Returns the written file path."""
    repos = repos or default_repositories()
    draft = repos.drafts.get(project_id, draft_id)
    if draft is None:
        raise ExportError(f"No such draft: {draft_id}")

    key = (fmt or "").strip().lower()
    if key not in FORMATS:
        raise ExportError(f"Unknown export format: {fmt}")

    out_dir = paths.exports_dir(project_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{_slug(draft.title)}_{draft.draft_id}_v{draft.version}"
    path = out_dir / f"{stem}{FORMATS[key]}"

    if key in ("markdown", "md"):
        # The draft's own Markdown, byte for byte — the most faithful export
        # there is, and the only one the user can have edited directly.
        path.write_text(draft.content, encoding="utf-8")
    elif key in ("excel", "xlsx"):
        # The workbook is a data dump, not a designed document, so it is still
        # built from the draft's own parsed structure.
        _build_xlsx(docmodel.to_document(draft), path)
    else:
        _render(draft, project_id, key, path, repos)

    repos.audit.append(AuditEvent(
        event_id=f"aud_{uuid.uuid4().hex[:10]}", project_id=project_id,
        chat_id=chat_id, type="draft_export",
        content=f"Exported “{draft.title}” as {key}",
        metadata={"draft_id": draft_id, "version": draft.version,
                  "file": path.name}))
    log.info("project %s: exported draft %s v%d as %s", project_id, draft_id,
             draft.version, key)
    return path


# ------------------------------------------------------------------ helpers
def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "report").strip("_")[:40] or "report"


def _render(draft: DraftRecord, project_id: str, key: str, path: Path,
            repos: Repositories) -> None:
    """Render the planned deliverable, with the user's edits applied.

    Falls back to the Markdown-parsing path for a draft written before the
    planning engine existed, or one whose deliverable can no longer be loaded —
    an old draft must still export rather than 500.
    """
    from app.renderers import registry

    deliverable, context = _load(draft, project_id, repos)
    if deliverable is None or context is None:
        _render_legacy(draft, key, path)
        return

    _apply_user_edits(deliverable, draft)
    result = registry.render(deliverable, context, path.parent,
                             registry.normalize(key))
    if result.path != path:
        result.path.replace(path)


def _load(draft: DraftRecord, project_id: str, repos: Repositories):
    """The deliverable this draft was planned from, and a context to render it."""
    if not draft.deliverable_id:
        return None, None
    from app.context import builder
    from app.deliverable import store

    try:
        deliverable = store.load(project_id=project_id,
                                 version=draft.deliverable_version)
        if deliverable is None or deliverable.deliverable_id != draft.deliverable_id:
            deliverable = store.load(project_id=project_id)
        if deliverable is None:
            return None, None
        context = builder.build_for_project(project_id, "", repos=repos)
        return deliverable, context
    except Exception as exc:                                   # noqa: BLE001
        log.warning("could not load the deliverable for draft %s (%s); "
                    "exporting from the draft text instead", draft.draft_id, exc)
        return None, None


def _apply_user_edits(deliverable, draft: DraftRecord) -> None:
    """Overlay hand-edited section text onto the pages it belongs to.

    The user's words replace the page's prose and its title, and the page's
    charts and tables are kept — an edit to the commentary is not a request to
    delete the chart it was commenting on.
    """
    from app.deliverable.model import TextElement

    for section in draft.sections:
        if section.origin != "user":
            continue
        page = deliverable.page(section.section_id)
        if page is None:
            continue

        heading, body = _split_heading(section.content)
        if heading:
            page.title = heading
        page.elements = [e for e in page.elements
                         if e.role not in ("body", "bullets", "callout", "quote")]
        if body:
            page.elements.insert(0, TextElement(
                element_id=f"{page.page_id}-user", role="body", text=body,
                authored_by="user", evidence_ids=list(page.evidence_ids),
                prominence="primary"))
        page.warnings.append("This page carries the user's own wording.")


def _split_heading(markdown: str) -> tuple[str, str]:
    """A section's edited Markdown, as `(heading, body)`."""
    lines = [line for line in (markdown or "").splitlines()]
    heading = ""
    body: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not heading and stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            continue
        body.append(line)
    return heading, "\n".join(body).strip()


def _render_legacy(draft: DraftRecord, key: str, path: Path) -> None:
    """The Markdown-parsing path, kept only for drafts with no deliverable.

    Deliberately plain. A draft planned by the current engine never reaches
    here, and one that does is being exported from text alone, so promising a
    designed artifact would be a lie.
    """
    from app.renderers import registry
    from app.deliverable.model import Deliverable, PageDesign, TextElement

    doc = docmodel.to_document(draft)
    deliverable = Deliverable(
        deliverable_id=f"legacy_{draft.draft_id}", title=doc.title,
        primary_format=registry.normalize(key), planned_by="fallback",
        warnings=["This draft predates the planning engine, so it was exported "
                  "from its text alone: it carries no charts, no validated "
                  "figures and no source notes."],
        pages=[PageDesign(
            page_id=f"p{index}", index=index, title=section.heading,
            purpose="content", elements=[TextElement(
                element_id=f"p{index}-body", role="body", authored_by="user",
                text=_flatten(section))])
            for index, section in enumerate(doc.sections)])

    context = _bare_context()
    result = registry.render(deliverable, context, path.parent,
                             registry.normalize(key))
    if result.path != path:
        result.path.replace(path)


def _flatten(section) -> str:
    parts: list[str] = []
    for block in section.blocks:
        if getattr(block, "text", ""):
            parts.append(block.text)
        for item in getattr(block, "items", []) or []:
            parts.append(f"\u2022  {item}")
        for row in getattr(block, "rows", []) or []:
            parts.append("  ".join(str(cell) for cell in row))
    return "\n".join(parts)


def _bare_context():
    from app.context.schemas import GenerationContext
    from app.templates import template_registry

    context = GenerationContext(scope="project")
    context.template_reference = template_registry.default()
    context.brand_system = context.template_reference.brand
    return context


def _build_xlsx(doc: NormalizedDoc, path: Path) -> None:
    """A workbook of the draft's tables, one sheet per section that has one.

    Kept on the parsed-Markdown path deliberately: a spreadsheet is a data dump
    for someone who wants to pivot it, not a designed artifact, and the draft's
    own tables are exactly what they asked for.
    """
    import xlsxwriter

    book = xlsxwriter.Workbook(str(path), {"in_memory": True})
    header = book.add_format({"bold": True, "bg_color": "#046A38",
                              "font_color": "#FFFFFF", "border": 1})
    cell = book.add_format({"border": 1, "valign": "top", "text_wrap": True})

    wrote = False
    for index, section in enumerate(doc.sections, start=1):
        tables = [b for b in section.blocks if b.type == "table" and b.rows]
        if not tables:
            continue
        sheet = book.add_worksheet(_sheet_name(section.heading, index))
        row_index = 0
        for table in tables:
            for column_index, column in enumerate(table.columns):
                sheet.write(row_index, column_index, column, header)
            sheet.freeze_panes(row_index + 1, 0)
            for row in table.rows:
                row_index += 1
                for column_index, value in enumerate(row):
                    sheet.write(row_index, column_index, value, cell)
            row_index += 2
            sheet.set_column(0, max(len(table.columns) - 1, 0), 28)
        wrote = True

    if not wrote:
        sheet = book.add_worksheet("Report")
        sheet.write(0, 0, doc.title, header)
        for index, section in enumerate(doc.sections, start=1):
            sheet.write(index, 0, section.heading, cell)
        sheet.set_column(0, 0, 60)
    book.close()


def _sheet_name(heading: str, index: int) -> str:
    """Excel forbids []:*?/\\ and caps sheet names at 31 characters."""
    cleaned = re.sub(r"[\[\]:*?/\\]", " ", heading or f"Section {index}").strip()
    return (cleaned[:28] + f" {index}") if len(cleaned) > 28 else (
        cleaned or f"Section {index}")
