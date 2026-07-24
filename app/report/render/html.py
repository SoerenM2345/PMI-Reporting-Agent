"""HTML rendering. Standard library only — no template engine, no CDN.

Self-contained on purpose: the output is a single file a user can mail, open on
a machine with no network, or print to PDF. A stylesheet link would break all
three, and a PMI report is often read somewhere it cannot fetch anything.

Everything user-derived is escaped. Report content includes file names, task
titles and free text pulled out of uploaded documents — none of it trustworthy
enough to interpolate raw, and a spreadsheet cell containing `<script>` is not a
hypothetical in a tool whose whole job is reading other people's files.
"""
from __future__ import annotations

from html import escape

from app.report.content import ReportContent, Section

_CSS = """
:root { --ink:#1a1a1a; --muted:#757575; --green:#2e7d32; --amber:#f9a825;
        --red:#c62828; --line:#e4e4e4; }
* { box-sizing: border-box; }
body { font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
       Helvetica, Arial, sans-serif; color: var(--ink); margin: 0;
       padding: 2.5rem 1.25rem; background: #fff; }
main { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 2rem; margin: 0 0 .25rem; }
h2 { font-size: 1.25rem; margin: 0 0 .2rem; line-height: 1.35; }
.sub { color: var(--muted); font-size: .9rem; margin: 0 0 1.5rem; }
.label { color: var(--muted); font-size: .8rem; text-transform: uppercase;
         letter-spacing: .06em; margin: 0 0 1rem; }
section { border-top: 1px solid var(--line); padding: 1.75rem 0; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid var(--line);
         vertical-align: top; }
th { background: #fafafa; font-weight: 600; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
         gap: .75rem; }
.tile { border: 1px solid var(--line); border-radius: 8px; padding: .9rem; }
.tile .k { color: var(--muted); font-size: .78rem; }
.tile .v { font-size: 1.5rem; font-weight: 600; margin-top: .15rem; }
.good { color: var(--green); } .warn { color: var(--amber); } .bad { color: var(--red); }
.muted { color: var(--muted); }
.note, .empty { color: var(--muted); font-size: .85rem; font-style: italic; }
ul { margin: .4rem 0 0; padding-left: 1.15rem; }
li { margin: .3rem 0; }
footer { border-top: 1px solid var(--line); margin-top: 2rem; padding-top: 1rem;
         color: var(--muted); font-size: .8rem; }
@media print { body { padding: 0; } section { page-break-inside: avoid; } }
"""


def render_html(content: ReportContent) -> str:
    """The whole report as one self-contained document."""
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(content.title)}</title>",
        f"<style>{_CSS}</style></head><body><main>",
        f"<h1>{escape(content.title)}</h1>",
    ]
    if content.subtitle:
        parts.append(f'<p class="sub">{escape(content.subtitle)}</p>')
    if content.meta_line:
        parts.append(
            '<p class="sub">' + escape(" · ".join(content.meta_line)) + "</p>"
        )

    for section in content.narrative():
        parts.append(_section(section, content))

    if content.footer:
        parts.append(f"<footer>{escape(content.footer)}</footer>")
    parts.append("</main></body></html>")
    return "\n".join(parts)


def _section(section: Section, content: ReportContent) -> str:
    out = [
        "<section>",
        f"<h2>{escape(section.headline)}</h2>",
        f'<p class="label">{escape(section.label)}</p>',
    ]

    rendered = False
    for block in section.blocks:
        body = _block(block, content)
        if body:
            rendered = True
            out.append(body)

    if not rendered and section.empty_explanation:
        out.append(f'<p class="empty">{escape(section.empty_explanation)}</p>')

    out.append("</section>")
    return "\n".join(out)


def _block(block, content: ReportContent) -> str:
    if block.kind == "prose":
        title = f"<p><strong>{escape(block.title)}</strong></p>" if block.title else ""
        return f"{title}<p>{escape(block.text)}</p>"

    if block.kind == "bullets":
        if not block.items:
            return ""
        title = f"<p><strong>{escape(block.title)}</strong></p>" if block.title else ""
        items = "".join(
            f'<li class="{escape(item.emphasis)}">{escape(item.text)}</li>'
            for item in block.items
        )
        return f"{title}<ul>{items}</ul>"

    if block.kind == "tiles":
        if not block.tiles:
            return ""
        tiles = []
        for tile in block.tiles:
            value = (content.facts.display(tile.fact_key)
                     if tile.fact_key else (tile.value or "Not Reported"))
            tiles.append(
                f'<div class="tile"><div class="k">{escape(tile.label)}</div>'
                f'<div class="v {escape(tile.emphasis)}">{escape(value)}</div></div>'
            )
        return f'<div class="tiles">{"".join(tiles)}</div>'

    if block.kind == "table":
        return _table(block)

    if block.kind == "chart":
        # Charts are PNGs on disk; embedding them would stop this being one
        # portable file. The deck and the workbook carry the picture.
        caption = block.caption or block.builder.replace("_", " ").title()
        return f'<p class="note">Chart: {escape(caption)} — see the deck.</p>'

    return ""


def _table(block) -> str:
    if block.is_derived:
        entity = block.query.entity if block.query else "rows"
        return (f'<p class="note">Full {escape(entity)} listing — included in '
                f"the Excel dashboard.</p>")
    if not block.rows:
        return ""

    head = "".join(f"<th>{escape(c.header)}</th>" for c in block.columns)
    limit = block.row_limit or len(block.rows)
    body = "".join(
        "<tr>" + "".join(
            f'<td class="{escape(cell.emphasis)}">{escape(cell.text)}</td>'
            for cell in row
        ) + "</tr>"
        for row in block.rows[:limit]
    )

    title = f"<p><strong>{escape(block.title)}</strong></p>" if block.title else ""
    note = f'<p class="note">{escape(block.note)}</p>' if block.note else ""
    return f"{title}<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{note}"
