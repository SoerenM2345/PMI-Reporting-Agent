"""The normalized document model, and building it from a saved draft (Phase 4).

Exports must reflect *the draft the user approved and edited*, not a fresh re-plan
of the knowledge base (Scenario 6). So the pipeline is:

    saved draft (Markdown)  →  NormalizedDoc  →  PPTX / DOCX / PDF / XLSX / HTML

The draft's sections are Markdown — including any the user rewrote by hand — so the
one honest way to export them is to parse that Markdown back into structure. This
module is that parser plus the format-neutral document it produces; the exporters
in `exporting.py` consume `NormalizedDoc` and never look at the knowledge base, so
an edited sentence in the draft is an edited sentence in the deck.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.project.models import DraftRecord

BlockType = Literal["paragraph", "bullets", "table", "note", "chart"]


class DocBlock(BaseModel):
    type: BlockType
    text: str = ""                              # paragraph / note / chart caption
    items: list[str] = Field(default_factory=list)      # bullets
    columns: list[str] = Field(default_factory=list)    # table header
    rows: list[list[str]] = Field(default_factory=list)  # table body


class DocSection(BaseModel):
    section_id: str
    heading: str = ""
    blocks: list[DocBlock] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class NormalizedDoc(BaseModel):
    title: str
    subtitle: str = ""
    meta: list[str] = Field(default_factory=list)
    sections: list[DocSection] = Field(default_factory=list)


def to_document(draft: DraftRecord) -> NormalizedDoc:
    """Parse a saved draft into a format-neutral document."""
    sections = []
    for section in draft.sections:
        heading, blocks = _parse_section(section.content, section.heading)
        sections.append(DocSection(
            section_id=section.section_id,
            heading=heading or section.heading,
            blocks=blocks,
            source_ids=section.depends_on.source_ids,
        ))
    return NormalizedDoc(title=draft.title, sections=sections)


# ------------------------------------------------------------------ parsing
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}.*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_HEADING = re.compile(r"^\s*#{1,6}\s+(.*)$")
_EMPHASIS = re.compile(r"^\s*\*(.+)\*\s*$")


def _parse_section(md: str, fallback_heading: str) -> tuple[str, list[DocBlock]]:
    lines = (md or "").splitlines()
    blocks: list[DocBlock] = []
    heading = ""
    para: list[str] = []
    i = 0

    def flush_paragraph():
        if para:
            blocks.append(DocBlock(type="paragraph", text=" ".join(para).strip()))
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        # First heading is the section title; later ones become bold paragraphs.
        m = _HEADING.match(line)
        if m:
            flush_paragraph()
            if not heading:
                heading = m.group(1).strip()
            else:
                blocks.append(DocBlock(type="paragraph", text=m.group(1).strip()))
            i += 1
            continue

        # The section's own "*label*" subtitle line — drop it (the heading carries it).
        if not blocks and not para and _EMPHASIS.match(line):
            i += 1
            continue

        # A pipe table: header row, separator, then body rows.
        if stripped.startswith("|") and i + 1 < len(lines) \
                and _TABLE_SEP.match(lines[i + 1]):
            flush_paragraph()
            columns = _cells(lines[i])
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            blocks.append(DocBlock(type="table", columns=columns, rows=rows))
            continue

        # A blockquote → a note (e.g. an "empty section" explanation, or a chart).
        if stripped.startswith(">"):
            flush_paragraph()
            text = stripped.lstrip("> ").strip()
            btype: BlockType = "chart" if text.startswith("📊") else "note"
            blocks.append(DocBlock(type=btype, text=text))
            i += 1
            continue

        # A run of bullets.
        if _BULLET.match(line):
            flush_paragraph()
            items = []
            while i < len(lines) and _BULLET.match(lines[i]):
                items.append(_clean(_BULLET.match(lines[i]).group(1)))
                i += 1
            blocks.append(DocBlock(type="bullets", items=items))
            continue

        para.append(stripped)
        i += 1

    flush_paragraph()
    return heading or fallback_heading, blocks


def _cells(line: str) -> list[str]:
    """Split a Markdown table row, honouring the escaped pipe `\\|`."""
    parts = re.split(r"(?<!\\)\|", line.strip())
    # A leading/trailing pipe yields empty edge cells — drop them.
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [_clean(c.replace("\\|", "|")) for c in parts]


def _clean(text: str) -> str:
    """Strip Markdown emphasis and the emphasis glyphs the planner adds."""
    text = text.strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"\1", text)
    return text.replace("❗", "").replace("⚠", "").strip()
