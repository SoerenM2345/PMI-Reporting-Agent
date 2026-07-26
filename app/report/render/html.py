"""Render a `ReportContent` as a branded, interactive dashboard (item 11).

Two things this file will not give up, whatever else it does:

* **One self-contained file.** The output is mailed, opened offline, and printed
  to PDF. A stylesheet link, a CDN script or a remote font breaks all three, and
  a PMI report is routinely read somewhere it cannot fetch anything. Everything
  — CSS, the sort/filter JavaScript, the logo, the charts — is inlined.
* **Everything user-derived is escaped.** File names, task titles and free text
  come out of documents this tool was handed; a spreadsheet cell holding
  `<script>` is not hypothetical for a tool whose whole job is reading other
  people's files. Nothing user-derived reaches the page without `escape()`.

What changed from the plain document it used to be: the palette, logo and RAG
colours come from `report.brand` (the one place the deck, workbook and charts
also read them, so they cannot drift), KPI tiles read from `TilesBlock`, tables
sort and filter client-side with vanilla JS, and charts are inlined as base64
PNGs from the same matplotlib builders the deck uses — so the dashboard shows the
picture rather than pointing at another format for it.
"""
from __future__ import annotations

import base64
import logging
from html import escape
from pathlib import Path
from typing import Optional

from app.report import brand
from app.report.content import ReportContent, Section

log = logging.getLogger("pmi.render.html")


def render_html(content: ReportContent, model=None, out_dir: Optional[Path] = None) -> str:
    """The whole report as one self-contained, interactive page.

    `model` and `out_dir` are optional: with them the charts are rendered and
    inlined; without them the chart blocks name themselves and say the picture
    is in the deck, exactly as before. Callers that never had a model keep
    working.
    """
    charts = _chart_images(content, model, out_dir)

    body = [
        _masthead(content),
        _kpi_strip(content),
    ]
    for section in content.narrative():
        body.append(_section(section, content, charts))
    if content.footer:
        body.append(f'<footer>{escape(content.footer)}</footer>')

    return "\n".join([
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(content.title)}</title>",
        f"<style>{_css()}</style></head><body>",
        '<main>',
        *body,
        "</main>",
        f"<script>{_JS}</script>",
        "</body></html>",
    ])


# ------------------------------------------------------------------- masthead
def _masthead(content: ReportContent) -> str:
    logo = brand.logo_data_uri()
    mark = (f'<img class="logo" alt="" src="{logo}">' if logo
            else '<span class="wordmark">Deloitte.</span>')
    meta = (f'<p class="meta">{escape(" · ".join(content.meta_line))}</p>'
            if content.meta_line else "")
    subtitle = (f'<p class="sub">{escape(content.subtitle)}</p>'
                if content.subtitle else "")
    return (
        '<header class="masthead">'
        f'<div class="brandbar">{mark}</div>'
        f'<h1>{escape(content.title)}</h1>{subtitle}{meta}'
        '</header>'
    )


def _kpi_strip(content: ReportContent) -> str:
    """The first tiles block, lifted to a KPI banner across the top.

    A dashboard's headline numbers belong at the top, not wherever the narrative
    order happens to place the tiles. The same block still renders in its section
    below; this is a projection of it, not a second copy of the figures.
    """
    for section in content.narrative():
        for block in section.blocks:
            if block.kind == "tiles" and block.tiles:
                cards = "".join(_kpi_card(t, content) for t in block.tiles)
                return f'<section class="kpis">{cards}</section>'
    return ""


def _kpi_card(tile, content: ReportContent) -> str:
    value = (content.facts.display(tile.fact_key)
             if tile.fact_key else (tile.value or "Not Reported"))
    return (
        f'<div class="kpi {escape(tile.emphasis)}">'
        f'<div class="kpi-v">{escape(value)}</div>'
        f'<div class="kpi-k">{escape(tile.label)}</div></div>'
    )


# -------------------------------------------------------------------- sections
def _section(section: Section, content: ReportContent, charts: dict) -> str:
    out = [
        '<section class="card">',
        f"<h2>{escape(section.headline)}</h2>",
        f'<p class="label">{escape(section.label)}</p>',
    ]

    rendered = False
    for block in section.blocks:
        html = _block(block, content, charts)
        if html:
            rendered = True
            out.append(html)

    if not rendered and section.empty_explanation:
        out.append(f'<p class="empty">{escape(section.empty_explanation)}</p>')

    out.append("</section>")
    return "\n".join(out)


def _block(block, content: ReportContent, charts: dict) -> str:
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
        uri = charts.get(block.builder)
        caption = escape(block.caption or block.builder.replace("_", " ").title())
        if uri:
            return (f'<figure class="chart"><img alt="{caption}" src="{uri}">'
                    f'<figcaption>{caption}</figcaption></figure>')
        return f'<p class="note">Chart: {caption} — see the deck.</p>'

    return ""


def _table(block) -> str:
    if block.is_derived:
        entity = block.query.entity if block.query else "rows"
        return (f'<p class="note">Full {escape(entity)} listing — included in '
                f"the Excel dashboard.</p>")
    if not block.rows:
        return ""

    head = "".join(
        f'<th data-col="{index}">{escape(column.header)}'
        '<span class="arrow"></span></th>'
        for index, column in enumerate(block.columns)
    )
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
    # A filter box per table, wired by the shared script. Client-side and
    # dependency-free, so the single-file guarantee holds.
    controls = ('<input class="filter" type="search" placeholder="Filter rows…" '
                'aria-label="Filter rows">')
    return (f'{title}{controls}'
            f'<div class="scroll"><table class="sortable">'
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{note}")


# --------------------------------------------------------------------- charts
def _chart_images(content: ReportContent, model, out_dir: Optional[Path]) -> dict:
    """`{builder: data-uri}` for every chart the content names.

    Rendered with the same matplotlib builders the deck uses, then base64-inlined
    so the page stays one file. A builder that fails is skipped with a warning —
    a missing chart is a gap, not a reason to fail the whole document.
    """
    if model is None:
        return {}

    from app.report import charts_registry

    import tempfile

    directory = Path(out_dir) if out_dir else Path(tempfile.mkdtemp())
    directory.mkdir(parents=True, exist_ok=True)

    images: dict[str, str] = {}
    for section in content.narrative():
        for block in section.blocks:
            if getattr(block, "kind", None) != "chart" or block.builder in images:
                continue
            builder = charts_registry.resolve(block.builder)
            if builder is None:
                continue
            try:
                path = builder(model, directory)
            except Exception as exc:                          # noqa: BLE001
                log.warning("dashboard chart %s failed: %s", block.builder, exc)
                continue
            if path and Path(path).is_file():
                data = Path(path).read_bytes()
                images[block.builder] = (
                    "data:image/png;base64,"
                    + base64.b64encode(data).decode("ascii")
                )
    return images


# ------------------------------------------------------------------------- CSS
def _css() -> str:
    return _CSS_TEMPLATE.format(
        green=brand.GREEN, bright=brand.BRIGHT, ink=brand.DARK, muted=brand.GREY,
        good=brand.RAG_GREEN, amber=brand.RAG_AMBER, red=brand.RAG_RED,
    )


_CSS_TEMPLATE = """
:root {{
  --green:{green}; --bright:{bright}; --ink:{ink}; --muted:{muted};
  --good:{good}; --amber:{amber}; --red:{red}; --line:#e6e6e6; --bg:#f4f5f2;
}}
* {{ box-sizing: border-box; }}
body {{ font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        Helvetica, Arial, sans-serif; color: var(--ink); margin: 0;
        background: var(--bg); }}
main {{ max-width: 74rem; margin: 0 auto; padding: 0 1.25rem 3rem; }}
.masthead {{ padding: 1.75rem 0 1.25rem; }}
.brandbar {{ display:flex; align-items:center; min-height: 2rem; margin-bottom: 1rem; }}
.logo {{ height: 2rem; }}
.wordmark {{ font-weight: 700; font-size: 1.4rem; color: var(--green);
             letter-spacing: -.02em; }}
.wordmark::after {{ content:""; display:inline-block; width:.32rem; height:.32rem;
             background: var(--bright); border-radius:50%; margin-left:.1rem;
             vertical-align: baseline; }}
h1 {{ font-size: 2rem; margin: 0 0 .25rem; letter-spacing: -.01em; }}
h2 {{ font-size: 1.2rem; margin: 0 0 .15rem; line-height: 1.3; }}
.sub {{ color: var(--muted); font-size: .95rem; margin: 0; }}
.meta {{ color: var(--muted); font-size: .82rem; margin: .35rem 0 0; }}
.label {{ color: var(--muted); font-size: .74rem; text-transform: uppercase;
          letter-spacing: .07em; margin: 0 0 1rem; }}

.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem,1fr));
         gap: .75rem; margin: 0 0 1.5rem; }}
.kpi {{ background:#fff; border:1px solid var(--line); border-top:3px solid var(--green);
        border-radius:10px; padding:1rem; box-shadow: 0 1px 2px rgba(0,0,0,.03); }}
.kpi.good {{ border-top-color: var(--good); }}
.kpi.warn {{ border-top-color: var(--amber); }}
.kpi.bad  {{ border-top-color: var(--red); }}
.kpi-v {{ font-size: 1.7rem; font-weight: 700; }}
.kpi-k {{ color: var(--muted); font-size: .78rem; margin-top: .2rem; }}

.card {{ background:#fff; border:1px solid var(--line); border-radius:12px;
         padding: 1.4rem 1.5rem; margin: 0 0 1.1rem;
         box-shadow: 0 1px 2px rgba(0,0,0,.03); }}
.tiles {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(11rem,1fr));
          gap:.75rem; }}
.tile {{ border:1px solid var(--line); border-radius:8px; padding:.9rem; }}
.tile .k {{ color: var(--muted); font-size:.78rem; }}
.tile .v {{ font-size:1.4rem; font-weight:600; margin-top:.15rem; }}

.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: .88rem; }}
th, td {{ text-align: left; padding: .5rem .6rem; border-bottom: 1px solid var(--line);
          vertical-align: top; }}
th {{ background:#fafafa; font-weight:600; cursor:pointer; user-select:none;
      position: sticky; top: 0; white-space: nowrap; }}
th .arrow {{ font-size:.7rem; color: var(--muted); margin-left:.3rem; }}
tbody tr:hover {{ background:#fbfdf9; }}
.filter {{ margin:.25rem 0 .6rem; padding:.4rem .6rem; width:min(20rem,100%);
           border:1px solid var(--line); border-radius:6px; font-size:.85rem; }}

.good {{ color: var(--good); }} .warn {{ color: var(--amber); }}
.bad {{ color: var(--red); }} .muted {{ color: var(--muted); }}
.note, .empty {{ color: var(--muted); font-size:.85rem; font-style: italic; }}
ul {{ margin:.4rem 0 0; padding-left:1.15rem; }} li {{ margin:.3rem 0; }}
.chart {{ margin:.8rem 0 0; }} .chart img {{ max-width:100%; height:auto;
          border:1px solid var(--line); border-radius:8px; }}
.chart figcaption {{ color: var(--muted); font-size:.8rem; margin-top:.35rem; }}
footer {{ color: var(--muted); font-size:.8rem; padding: 1rem 0; }}

@media print {{
  body {{ background:#fff; }}
  .card, .kpi {{ box-shadow:none; break-inside: avoid; }}
  .filter {{ display:none; }}
  th {{ position: static; }}
}}
"""


# Vanilla JS: click a header to sort, type in a filter to hide rows. No library,
# no framework — the single-file guarantee forbids a CDN, and the interactions
# are simple enough not to want one.
_JS = """
document.querySelectorAll('table.sortable').forEach(function (table) {
  var filter = table.closest('section').querySelector('.filter');
  if (filter) {
    filter.addEventListener('input', function () {
      var q = this.value.toLowerCase();
      table.querySelectorAll('tbody tr').forEach(function (row) {
        row.style.display = row.textContent.toLowerCase().indexOf(q) > -1 ? '' : 'none';
      });
    });
  }
  table.querySelectorAll('th').forEach(function (th, index) {
    var asc = true;
    th.addEventListener('click', function () {
      var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
      rows.sort(function (a, b) {
        var x = a.children[index].textContent.trim();
        var y = b.children[index].textContent.trim();
        var nx = parseFloat(x.replace(/[^0-9.\\-]/g, ''));
        var ny = parseFloat(y.replace(/[^0-9.\\-]/g, ''));
        var both = !isNaN(nx) && !isNaN(ny);
        var cmp = both ? nx - ny : x.localeCompare(y);
        return asc ? cmp : -cmp;
      });
      var body = table.querySelector('tbody');
      rows.forEach(function (row) { body.appendChild(row); });
      table.querySelectorAll('th .arrow').forEach(function (a) { a.textContent = ''; });
      th.querySelector('.arrow').textContent = asc ? '▲' : '▼';
      asc = !asc;
    });
  });
});
"""
