"""Markdown rendering — the preview the user approves before anything is built.

This is the point of the whole content layer. Generating a deck is slow, costs a
vision call if anything has to be re-read, and produces a binary nobody can
skim; showing the same content as text takes milliseconds and lets a person
catch "that's the wrong audience" or "you've dropped the TSA milestone" before
any of that happens.

So the rule here is fidelity, not prettiness: if the preview says a figure, the
deck must say the same figure. Both read the same `ReportContent`, and neither
recomputes anything.

`show_provenance` appends the file and cell each figure came from. Off by default
because it doubles the length, but it is the one place a user can actually check
a citation — a slide footnote is too small and a workbook cell is too far away.
"""
from __future__ import annotations

from app.report.content import ReportContent, Section


def render_markdown(
    content: ReportContent,
    *,
    show_provenance: bool = False,
) -> str:
    """The narrative, as text. Pure — no disk, no side effects."""
    lines: list[str] = [f"# {content.title}"]
    if content.subtitle:
        lines.append(f"*{content.subtitle}*")
    if content.meta_line:
        lines += ["", " · ".join(content.meta_line)]

    for section in content.narrative():
        lines += ["", "---", ""]
        lines += _section(section, content, show_provenance)

    if content.footer:
        lines += ["", "---", "", f"*{content.footer}*"]

    return "\n".join(lines).rstrip() + "\n"


def render_blocks(content: ReportContent) -> list[dict]:
    """The narrative as structured sections, for a UI that can edit it.

    The markdown above is the same content flattened to text, and flattening is
    lossy in exactly the way that matters here: a cell in a markdown table has no
    identity, so a click on it cannot be turned into "write 12-08-2026 into
    milestone M1's planned date". `Cell.ref` survives this projection, which is
    what makes the preview editable and what keeps the edit going to the *data
    model* rather than to the stored text.

    Deliberately a projection of the same `ReportContent`, not a second plan —
    the preview and the deck must not be able to disagree.
    """
    return [
        {
            "section_id": section.section_id,
            "label": section.label,
            "headline": section.headline,
            "empty_explanation": section.empty_explanation,
            "blocks": [_block_payload(block, content) for block in section.blocks],
        }
        for section in content.narrative()
    ]


def _block_payload(block, content: ReportContent) -> dict:
    base = {"kind": block.kind, "block_id": block.block_id,
            "title": getattr(block, "title", None)}

    if block.kind == "bullets":
        return {**base, "items": [{"text": i.text, "emphasis": i.emphasis}
                                  for i in block.items]}
    if block.kind == "prose":
        return {**base, "text": block.text}
    if block.kind == "tiles":
        return {**base, "tiles": [
            {"label": t.label, "emphasis": t.emphasis,
             "value": (content.facts.display(t.fact_key) if t.fact_key
                       else (t.value or "Not Reported")),
             "fact_key": t.fact_key}
            for t in block.tiles
        ]}
    if block.kind == "chart":
        return {**base, "caption": block.caption
                or block.builder.replace("_", " ").title()}
    if block.kind == "table":
        if block.is_derived:
            return {**base, "derived": True,
                    "entity": block.query.entity if block.query else "rows",
                    "columns": [], "rows": []}
        return {
            **base,
            "derived": False,
            "note": block.note,
            "row_limit": block.row_limit,
            "columns": [{"header": c.header, "kind": c.kind} for c in block.columns],
            "rows": [
                [
                    {
                        "text": cell.text,
                        # Only a cell that names one model field can be written
                        # back. A computed variance or a citation carries no ref
                        # and the UI must not offer to edit it.
                        "editable": bool(cell.ref and cell.ref.field),
                        "field": cell.ref.field if cell.ref else None,
                    }
                    for cell in row
                ]
                for row in block.rows[:(block.row_limit or len(block.rows))]
            ],
        }
    return base


def _section(
    section: Section, content: ReportContent, show_provenance: bool
) -> list[str]:
    # The headline is the management message (§12.5); the label is only the
    # section's name, so it goes underneath in smaller type.
    lines = [f"## {section.headline}", f"*{section.label}*"]

    rendered_any = False
    for block in section.blocks:
        body = _block(block, content, show_provenance)
        if body:
            rendered_any = True
            lines += [""] + body

    # "No critical risks" and "nobody told us about the risks" are different
    # claims; an empty section must say which one it is.
    if not rendered_any and section.empty_explanation:
        lines += ["", f"> {section.empty_explanation}"]

    return lines


def _block(block, content: ReportContent, show_provenance: bool) -> list[str]:
    if block.kind == "prose":
        return ([f"**{block.title}**", ""] if block.title else []) + [block.text]

    if block.kind == "bullets":
        if not block.items:
            return []
        lines = [f"**{block.title}**", ""] if block.title else []
        for item in block.items:
            mark = {"bad": "❗ ", "warn": "⚠ "}.get(item.emphasis, "")
            lines.append(f"- {mark}{item.text}")
        return lines

    if block.kind == "tiles":
        if not block.tiles:
            return []
        lines = ["| Measure | Value |", "| --- | --- |"]
        for tile in block.tiles:
            value = (content.facts.display(tile.fact_key)
                     if tile.fact_key else (tile.value or "Not Reported"))
            lines.append(f"| {tile.label} | **{value}** |")
        return lines + _tile_provenance(block, content, show_provenance)

    if block.kind == "table":
        return _table(block, show_provenance)

    if block.kind == "chart":
        caption = block.caption or block.builder.replace("_", " ").title()
        return [f"> 📊 Chart: **{caption}**"]

    return []


def _table(block, show_provenance: bool) -> list[str]:
    if block.is_derived:
        # Large dumps are stored as a query, not as rows — the preview says so
        # rather than silently showing an empty table.
        entity = block.query.entity if block.query else "rows"
        return [f"> 📋 Full {entity} listing — included in the Excel dashboard."]

    if not block.rows:
        return []

    lines = []
    if block.title:
        lines += [f"**{block.title}**", ""]

    headers = [c.header for c in block.columns]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")

    limit = block.row_limit or len(block.rows)
    for row in block.rows[:limit]:
        cells = [_escape(cell.text) for cell in row]
        # Pad short rows rather than emitting a ragged table.
        cells += [""] * (len(headers) - len(cells))
        lines.append("| " + " | ".join(cells) + " |")

    if block.note:
        lines += ["", f"*{block.note}*"]

    return lines


def _tile_provenance(block, content: ReportContent, show: bool) -> list[str]:
    if not show:
        return []
    cites: list[str] = []
    for tile in block.tiles:
        fact = content.facts.get(tile.fact_key) if tile.fact_key else None
        if not fact:
            continue
        for ref in fact.refs:
            if ref.file_name:
                where = f" ({ref.location})" if ref.location else ""
                cites.append(f"{fact.label}: {ref.file_name}{where}")
            elif ref.is_derived:
                cites.append(f"{fact.label}: computed")
    if not cites:
        return []
    # dict.fromkeys keeps first-seen order while removing duplicates.
    return ["", "<sub>" + " · ".join(dict.fromkeys(cites)) + "</sub>"]


def _escape(text: str) -> str:
    """A pipe inside a cell would split the row into two columns."""
    return (text or "").replace("|", "\\|").replace("\n", " ")
