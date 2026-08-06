"""Render a `Deliverable` as a self-contained interactive dashboard.

One file. Every `src` and `href` is a `data:` URI or a fragment, every script is
inline, and there is no chart library — the SVG comes from
`app/visualizations/charts.py` and one delegated handler drives tooltips and
legend toggling. That constraint is not aesthetic: the file gets emailed, opened
from a share, and archived, and a dashboard that needs a CDN is a dashboard that
stops working.

What is different from the renderer this replaces: the page is the **storyline**.
The old one lifted a KPI strip to the top of every report regardless of what the
report was about; here a KPI banner appears only where a page says so, sections
appear in the order the argument needs them, and a page that the planner made
mostly visual renders mostly visual.

The CSS comes from `BrandSystem.css_vars()`, so the dashboard, the deck, the
document and the PDF are the same design language rather than four
approximations of it.
"""
from __future__ import annotations

import logging
from html import escape
from pathlib import Path
from typing import Optional, Sequence

from app.context.schemas import GenerationContext
from app.deliverable.model import (
    BulletsElement,
    ChartElement,
    Deliverable,
    DiagramElement,
    ImageElement,
    KpiRowElement,
    PageDesign,
    TableElement,
    TextElement,
)
from app.renderers import naming
from app.renderers.common import MeasuredBox, RenderResult
from app.templates.brand_system import BrandSystem
from app.visualizations import charts as chart_render
from app.visualizations import diagrams as diagram_render

log = logging.getLogger("pmi.renderers.html")


def render(deliverable: Deliverable, context: GenerationContext,
           out_dir: Path) -> RenderResult:
    brand: BrandSystem = context.brand_system or _fallback_brand()
    body = "\n".join([
        _masthead(deliverable, context, brand),
        _rail(deliverable),
        "<main>",
        *[_page(page, deliverable, brand) for page in deliverable.pages],
        _methodology(deliverable, context),
        "</main>",
        _footer(deliverable, context),
    ])

    document = (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(deliverable.title or 'Integration report')}</title>\n"
        f"<style>\n{_css(brand)}\n</style>\n</head>\n<body>\n"
        f"{body}\n<script>\n{_JS}\n</script>\n</body>\n</html>\n")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / naming.output_name(deliverable, context, "html")
    path.write_text(document, encoding="utf-8")
    log.info("rendered %s (%d KB)", path.name, len(document) // 1024)

    return RenderResult(
        path=path, page_count=len(deliverable.pages),
        element_boxes=_measure(deliverable), warnings=list(deliverable.warnings))


def _fallback_brand() -> BrandSystem:
    from app.templates import template_registry

    return template_registry.default().brand


# ================================================================== sections
def _masthead(deliverable: Deliverable, context: GenerationContext,
              brand: BrandSystem) -> str:
    logo = brand.logo_data_uri()
    mark = (f'<img class="logo" src="{logo}" alt="">' if logo
            else '<span class="wordmark">Deloitte</span>')
    # Bare values made ``STEERING COMMITTEE · UNKNOWN`` impossible to
    # understand: Unknown was the integration phase, not the audience or report
    # status. Keep every value attached to its field name, including absences.
    meta = " &middot; ".join(
        f'<span><span class="meta-label">{escape(label)}:</span> '
        f'{escape(_meta_value(value))}</span>'
        for label, value in (
            ("Audience", deliverable.audience_label),
            ("Reporting period", context.reporting_period),
            ("Integration phase", context.transaction.integration_phase),
        )
        if value
    )

    takeaway = (f'<p class="takeaway">{escape(deliverable.executive_takeaway)}</p>'
                if deliverable.executive_takeaway else "")
    return (f'<header class="masthead">\n<div class="brand">{mark}</div>\n'
            f"<h1>{escape(deliverable.title)}</h1>\n"
            f'<p class="subtitle">{escape(deliverable.subtitle)}</p>\n'
            f'<p class="meta">{meta}</p>\n'
            f'<p class="governing">{escape(deliverable.governing_message)}</p>\n'
            f"{takeaway}\n</header>")


def _rail(deliverable: Deliverable) -> str:
    """A sticky contents rail with scroll-spy, so a long report stays navigable."""
    items = [f'<li><a href="#{escape(page.page_id)}">{escape(page.title or page.page_id)}'
             f"</a></li>"
             for page in deliverable.pages if page.purpose != "cover"]
    if len(items) < 2:
        return ""
    return ('<nav class="rail" aria-label="Contents">\n<p class="rail-title">'
            "Contents</p>\n<ol>\n" + "\n".join(items) + "\n</ol>\n</nav>")


def _page(page: PageDesign, deliverable: Deliverable,
          brand: BrandSystem) -> str:
    if page.purpose == "cover":
        return ""                          # the masthead already is the cover

    columns = _column_count(page.composition)
    classes = f"page {page.composition} cols-{columns} density-normal"
    parts = [f'<section id="{escape(page.page_id)}" class="{classes}">']
    parts.append(f"<h2>{escape(page.title)}</h2>")
    if page.subtitle:
        parts.append(f'<p class="lede">{escape(page.subtitle)}</p>')

    if page.warnings:
        parts.append('<p class="page-warning">'
                     + escape(" ".join(page.warnings)) + "</p>")

    parts.append('<div class="grid">')
    for element in page.elements:
        rendered = _element(element, deliverable, brand)
        if rendered:
            span = "wide" if element.prominence == "primary" and columns > 1 \
                else ""
            parts.append(f'<div class="cell {span}">{rendered}</div>')
    parts.append("</div>")

    if page.source_note:
        parts.append('<details class="sources"><summary>Sources and caveats'
                     "</summary><p>" + escape(page.source_note) + "</p></details>")
    parts.append("</section>")
    return "\n".join(parts)


def _column_count(composition: str) -> int:
    return {"two_column": 2, "chart_plus_commentary": 2, "three_column": 3,
            "four_column": 4}.get(composition, 1)


def _element(element, deliverable: Deliverable, brand: BrandSystem) -> str:
    if isinstance(element, TextElement):
        if not element.text:
            return ""
        if element.role == "callout":
            return (f'<aside class="callout {escape(element.emphasis)}">'
                    f"{escape(element.text)}</aside>")
        if element.role == "quote":
            return f"<blockquote>{escape(element.text)}</blockquote>"
        return f"<p>{escape(element.text)}</p>"

    if isinstance(element, BulletsElement):
        if not element.items:
            return ""
        return "<ul>" + "".join(f"<li>{escape(item)}</li>"
                                for item in element.items) + "</ul>"

    if isinstance(element, KpiRowElement):
        return _kpis(element)

    if isinstance(element, ChartElement):
        spec = deliverable.specs.charts.get(element.spec_id)
        if spec is None:
            return ""
        # SVG mark ``<title>`` nodes produce a browser-native tooltip. This page
        # already has the styled delegated tooltip below, so enabling both shows
        # the same value twice on hover.
        svg = chart_render.to_svg(spec, brand, native_tooltips=False)
        return f'<figure class="chart">{svg}</figure>'

    if isinstance(element, DiagramElement):
        spec = deliverable.specs.diagrams.get(element.spec_id)
        if spec is None:
            return ""
        svg = diagram_render.to_svg(spec, brand)
        return f'<figure class="diagram">{svg}</figure>'

    if isinstance(element, TableElement):
        spec = deliverable.specs.tables.get(element.spec_id)
        return _table(spec) if spec is not None else ""

    if isinstance(element, ImageElement) and element.image_ref:
        data = _data_uri(Path(element.image_ref))
        return (f'<figure><img src="{data}" alt="{escape(element.alt)}">'
                f"</figure>") if data else ""
    return ""


def _kpis(element: KpiRowElement) -> str:
    tiles = []
    for tile in element.tiles:
        note = f'<span class="kpi-note">{escape(tile.note)}</span>' \
            if tile.note else ""
        tiles.append(
            f'<div class="kpi {escape(tile.emphasis)}" '
            f'data-evidence-id="{escape(tile.evidence_id)}">'
            f'<span class="kpi-value">{escape(tile.display)}</span>'
            f'<span class="kpi-label">{escape(tile.label)}</span>{note}</div>')
    return f'<div class="kpi-row">{"".join(tiles)}</div>' if tiles else ""


def _table(spec) -> str:
    """A sortable, filterable table. Wide ones scroll inside their own box."""
    headers = "".join(
        f'<th class="{_align(column.kind)}{" source-col" if column.header == "Source" else ""}" '
        f'data-kind="{escape(column.kind)}" '
        f'{"style=\"width: 80px;\"" if column.header == "Source" else ""}>'
        f"{escape(column.header)}</th>" for column in spec.columns)

    rows = []
    for index, row in enumerate(spec.displayed_rows):
        emphasis = ' class="emphasis"' if index in spec.emphasis_rows else ""
        cells = "".join(
            f'<td class="{_align(spec.columns[position].kind)} '
            f'{escape(cell.emphasis)}{" source-col" if spec.columns[position].header == "Source" else ""}">'
            f'{escape(cell.text)}</td>'
            for position, cell in enumerate(row) if position < len(spec.columns))
        rows.append(f"<tr{emphasis}>{cells}</tr>")

    note = (f'<p class="note">{escape(spec.note())}</p>'
            if spec.has_note else "")
    caption = f"<caption>{escape(spec.caption)}</caption>" if spec.caption else ""
    return (f'<div class="table-wrap">'
            f'<input class="filter" type="search" placeholder="Filter rows" '
            f'aria-label="Filter table rows">'
            f'<table class="sortable">{caption}<thead><tr>{headers}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table>{note}</div>")


def _align(kind: str) -> str:
    return "num" if kind in ("number", "currency", "percent") else "txt"


def _meta_value(value: str) -> str:
    text = " ".join(str(value or "").replace("_", " ").split())
    return "Unknown" if text.casefold() == "unknown" else text


def _methodology(deliverable: Deliverable, context: GenerationContext) -> str:
    """How the document was made, and what it could not do.

    Collapsed, but present. A reader who wants to know which file a figure came
    from should not have to ask.
    """
    files = context.evidence.projected_from_files
    rows = "".join(f"<li>{escape(name)}</li>" for name in files) or \
        "<li>No files were read.</li>"

    caveats = "".join(f"<li>{escape(note)}</li>" for note in deliverable.notes)
    warnings = "".join(f"<li>{escape(warning)}</li>"
                       for warning in deliverable.warnings[:12])
    conflicts = "".join(
        f"<li>{escape(conflict.entity_key)} &mdash; {escape(conflict.field)}: "
        f"{escape('; '.join(f'{k} says {v}' for k, v in conflict.values.items()))}"
        f"</li>" for conflict in context.unresolved_critical_conflicts)

    sections = [f'<h3>Sources</h3><ul class="source-files">{rows}</ul>']
    if conflicts:
        sections.append("<h3>Unresolved disagreements between sources</h3>"
                        f"<ul>{conflicts}</ul>")
    if caveats:
        sections.append(f"<h3>Limitations</h3><ul>{caveats}</ul>")
    if warnings:
        sections.append(f"<h3>What the system could not do</h3><ul>{warnings}</ul>")

    return ('<details class="methodology" id="methodology">'
            "<summary>Sources and methodology</summary>"
            + "".join(sections) + "</details>")


def _footer(deliverable: Deliverable, context: GenerationContext) -> str:
    return (f'<footer><p>{escape(context.display_name())}'
            f" &middot; {escape(deliverable.audience_label)}"
            f" &middot; generated {escape(deliverable.created_at[:10])}</p>"
            f'<p class="print-hint">Use your browser\'s print command for a '
            f"paginated copy.</p></footer>")


def _data_uri(path: Path) -> Optional[str]:
    import base64

    try:
        return ("data:image/png;base64,"
                + base64.b64encode(path.read_bytes()).decode("ascii"))
    except OSError:
        return None


# ================================================================== styling
def _css(brand: BrandSystem) -> str:
    return brand.css_vars() + """
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0; font-family: var(--font-stack);
  color: var(--brand-text); background: var(--brand-surface);
  font-size: 15px; line-height: 1.55;
}
.masthead {
  padding: 2.2rem clamp(1rem, 4vw, 3.5rem) 1.6rem;
  border-bottom: 3px solid var(--brand-primary);
}
.masthead .logo { height: 30px; }
.wordmark { font-weight: 700; color: var(--brand-primary); letter-spacing: -.02em; }
.masthead h1 { margin: .8rem 0 .2rem; font-size: clamp(1.5rem, 3.2vw, 2.1rem);
  line-height: 1.15; }
.subtitle { margin: 0; color: var(--brand-muted); }
.meta { margin: .3rem 0 0; color: var(--brand-muted); font-size: .82rem;
  text-transform: uppercase; letter-spacing: .06em; }
.governing {
  margin: 1.3rem 0 0; padding-left: .9rem; max-width: 62ch;
  border-left: 4px solid var(--brand-emphasis);
  font-size: 1.12rem; font-weight: 600;
}
.takeaway { margin: .7rem 0 0; max-width: 70ch; color: var(--brand-text); }
.banner {
  margin: 1.1rem 0 0; padding: .7rem .9rem; max-width: 78ch;
  background: var(--brand-surface-alt); border-left: 4px solid var(--brand-rag-amber);
  font-size: .9rem;
}
main { padding: 0 clamp(1rem, 4vw, 3.5rem) 3rem; }
.rail {
  position: sticky; top: 0; z-index: 5; padding: .6rem clamp(1rem, 4vw, 3.5rem);
  background: var(--brand-surface); border-bottom: 1px solid var(--brand-rule);
  overflow-x: auto;
}
.rail-title { display: none; }
.rail ol { display: flex; gap: 1.1rem; margin: 0; padding: 0; list-style: none;
  white-space: nowrap; }
.rail a { color: var(--brand-muted); text-decoration: none; font-size: .84rem;
  padding-bottom: .2rem; border-bottom: 2px solid transparent; }
.rail a:hover { color: var(--brand-text); }
.rail a.active { color: var(--brand-primary); border-bottom-color: var(--brand-primary); }
.page { padding: 2.2rem 0; border-bottom: 1px solid var(--brand-rule); }
.page h2 { margin: 0 0 .35rem; font-size: clamp(1.15rem, 2.2vw, 1.5rem);
  line-height: 1.25; max-width: 46ch; }
.lede { margin: 0 0 1.1rem; color: var(--brand-muted); max-width: 62ch; }
.page-warning { margin: 0 0 1rem; padding: .55rem .8rem; font-size: .86rem;
  background: var(--brand-surface-alt); border-left: 3px solid var(--brand-rag-amber); }
.grid { display: grid; gap: 1.3rem; grid-template-columns: 1fr; }
@media (min-width: 900px) {
  .cols-2 .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .cols-3 .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .cols-4 .grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .chart_plus_commentary .grid { grid-template-columns: 1.6fr 1fr; }
}
.cell { min-width: 0; }
.cell p { margin: 0 0 .7rem; max-width: 70ch; }
.cell ul { margin: 0 0 .7rem; padding-left: 1.15rem; max-width: 70ch; }
.cell li { margin-bottom: .4rem; }
blockquote {
  margin: 0; padding: .2rem 0 .2rem 1rem; max-width: 40ch;
  border-left: 5px solid var(--brand-emphasis);
  font-size: clamp(1.3rem, 3vw, 1.9rem); font-weight: 600; line-height: 1.2;
  color: var(--brand-deep);
}
.callout {
  padding: .8rem 1rem; background: var(--brand-surface-alt);
  border-left: 4px solid var(--brand-primary); font-size: .93rem;
}
.callout.warn { border-left-color: var(--brand-rag-amber); }
.callout.bad  { border-left-color: var(--brand-rag-red); }
.callout.good { border-left-color: var(--brand-rag-green); }
.kpi-row { display: grid; gap: .8rem;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
.kpi { padding: .85rem 1rem; background: var(--brand-surface-alt); border-radius: 4px; }
.kpi-value { display: block; font-size: 1.7rem; font-weight: 700; line-height: 1.1;
  color: var(--brand-primary); }
.kpi.bad .kpi-value { color: var(--brand-rag-red); }
.kpi.warn .kpi-value { color: var(--brand-rag-amber); }
.kpi.good .kpi-value { color: var(--brand-rag-green); }
.kpi.muted .kpi-value { color: var(--brand-muted); font-size: 1.1rem; }
.kpi-label { display: block; margin-top: .25rem; font-size: .78rem;
  color: var(--brand-muted); text-transform: uppercase; letter-spacing: .05em; }
.kpi-note { display: block; margin-top: .3rem; font-size: .75rem; font-style: italic;
  color: var(--brand-rag-amber); }
figure { margin: 0; }
figure svg { width: 100%; height: auto; display: block; }
figcaption { margin-top: .5rem; font-size: .82rem; color: var(--brand-muted);
  max-width: 70ch; }
.pmi-mark { transition: opacity .12s ease; cursor: pointer; }
.pmi-chart.dimmed .pmi-mark:not(.hot) { opacity: .28; }
.pmi-legend rect { cursor: pointer; }
.table-wrap { overflow-x: auto; }
.filter { width: min(260px, 100%); margin-bottom: .5rem; padding: .35rem .5rem;
  font: inherit; font-size: .86rem; border: 1px solid var(--brand-rule);
  border-radius: 3px; background: var(--brand-surface); color: var(--brand-text); }
table { width: 100%; border-collapse: collapse; font-size: .87rem; }
caption { text-align: left; padding-bottom: .4rem; font-size: .82rem;
  color: var(--brand-muted); }
th { background: var(--brand-primary); color: var(--brand-text-inverse);
  text-align: left; padding: .45rem .6rem; font-weight: 600; cursor: pointer;
  white-space: nowrap; }
th::after { content: ""; }
th[aria-sort="ascending"]::after { content: " \\2191"; }
th[aria-sort="descending"]::after { content: " \\2193"; }
td { padding: .4rem .6rem; border-bottom: 1px solid var(--brand-rule);
  vertical-align: top; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.bad { color: var(--brand-rag-red); font-weight: 600; }
td.warn { color: var(--brand-rag-amber); }
td.good { color: var(--brand-rag-green); }
td.muted { color: var(--brand-muted); }
th.source-col, td.source-col { color: var(--brand-muted); font-size: 0.75rem;
  font-weight: 500; width: 80px; }
tr.emphasis td { background: var(--brand-surface-alt); }
.note { margin: .4rem 0 0; font-size: .8rem; color: var(--brand-muted); }
.sources { margin-top: .8rem; font-size: .68rem; color: #a3a3a3; }
.sources summary { cursor: pointer; color: #a3a3a3; }
.methodology { margin-top: 1.2rem; font-size: .86rem; }
.methodology summary { cursor: pointer; color: var(--brand-muted); }
.methodology { padding: 1.6rem 0 0; }
.methodology h3 { margin: 1rem 0 .35rem; font-size: .95rem; }
.methodology ul { margin: 0; padding-left: 1.15rem; }
.methodology .source-files { font-size: .68rem; color: #a3a3a3; }
footer { padding: 1.4rem clamp(1rem, 4vw, 3.5rem) 2.4rem; color: var(--brand-muted);
  font-size: .82rem; border-top: 1px solid var(--brand-rule); }
#tooltip {
  position: fixed; z-index: 20; display: none; max-width: 240px;
  padding: .4rem .6rem; background: var(--brand-text);
  color: var(--brand-text-inverse); border-radius: 3px; font-size: .8rem;
  pointer-events: none;
}
@media (prefers-color-scheme: dark) {
  body { background: #14161a; color: #e9eaec; }
  .rail, .masthead { background: #14161a; }
  .kpi, .callout, .banner, tr.emphasis td { background: #1e2126; }
  td { border-bottom-color: #2b2f36; }
  .filter { background: #1e2126; color: #e9eaec; border-color: #2b2f36; }
  #tooltip { background: #e9eaec; color: #14161a; }
}
@media print {
  .rail, .filter, #tooltip { display: none !important; }
  body { font-size: 10.5pt; }
  .page { break-inside: avoid; break-after: page; border-bottom: none;
          padding: 0 0 1.2rem; }
  .masthead { break-after: page; }
  figure, .kpi-row, table { break-inside: avoid; }
  details { display: block; }
  details > summary { display: none; }
  a[href^="#"] { text-decoration: none; color: inherit; }
}
"""


#: One delegated handler per behaviour. No library, no build step.
_JS = """
(function () {
  'use strict';

  var tip = document.createElement('div');
  tip.id = 'tooltip';
  tip.setAttribute('role', 'status');
  document.body.appendChild(tip);

  // Chart tooltips. Delegated, so it costs one listener however many charts.
  document.addEventListener('mousemove', function (event) {
    var mark = event.target.closest ? event.target.closest('.pmi-mark') : null;
    if (!mark) { tip.style.display = 'none'; return; }
    var parts = [mark.getAttribute('data-series'), mark.getAttribute('data-label')]
      .filter(Boolean).join(' \\u2014 ');
    var value = mark.getAttribute('data-value') || '';
    var note = mark.getAttribute('data-note');
    tip.textContent = parts + (value ? ': ' + value : '') + (note ? ' (' + note + ')' : '');
    tip.style.display = 'block';
    tip.style.left = Math.min(event.clientX + 12, window.innerWidth - 250) + 'px';
    tip.style.top = (event.clientY + 16) + 'px';
  });

  // Legend toggling: highlight one series rather than hiding it, so the axis
  // does not move under the reader.
  document.addEventListener('click', function (event) {
    var swatch = event.target.closest ? event.target.closest('.pmi-legend rect') : null;
    if (!swatch) { return; }
    var chart = swatch.closest('.pmi-chart');
    var series = swatch.getAttribute('data-series');
    var already = chart.classList.contains('dimmed') &&
                  chart.getAttribute('data-hot') === series;
    chart.querySelectorAll('.pmi-mark').forEach(function (mark) {
      mark.classList.toggle('hot', !already && mark.getAttribute('data-series') === series);
    });
    chart.classList.toggle('dimmed', !already);
    chart.setAttribute('data-hot', already ? '' : series);
  });

  // Sortable columns.
  document.querySelectorAll('table.sortable thead th').forEach(function (th) {
    th.addEventListener('click', function () {
      var table = th.closest('table');
      var index = Array.prototype.indexOf.call(th.parentNode.children, th);
      var numeric = th.classList.contains('num');
      var descending = th.getAttribute('aria-sort') === 'ascending';
      var body = table.tBodies[0];
      var rows = Array.prototype.slice.call(body.rows);

      rows.sort(function (a, b) {
        var x = a.cells[index] ? a.cells[index].textContent.trim() : '';
        var y = b.cells[index] ? b.cells[index].textContent.trim() : '';
        if (numeric) {
          var nx = parseFloat(x.replace(/[^0-9.\\-]/g, ''));
          var ny = parseFloat(y.replace(/[^0-9.\\-]/g, ''));
          // "Not Reported" always sorts last: it is not a zero.
          if (isNaN(nx) && isNaN(ny)) { return 0; }
          if (isNaN(nx)) { return 1; }
          if (isNaN(ny)) { return -1; }
          return descending ? ny - nx : nx - ny;
        }
        return descending ? y.localeCompare(x) : x.localeCompare(y);
      });
      rows.forEach(function (row) { body.appendChild(row); });
      table.querySelectorAll('th').forEach(function (other) {
        other.removeAttribute('aria-sort');
      });
      th.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
    });
  });

  // Row filtering.
  document.querySelectorAll('.table-wrap .filter').forEach(function (input) {
    input.addEventListener('input', function () {
      var needle = input.value.toLowerCase();
      var table = input.parentNode.querySelector('table');
      Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
        row.style.display = row.textContent.toLowerCase().indexOf(needle) === -1
          ? 'none' : '';
      });
    });
  });

  // Scroll-spy on the contents rail.
  var links = Array.prototype.slice.call(document.querySelectorAll('.rail a'));
  if (links.length && 'IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) { return; }
        links.forEach(function (link) {
          link.classList.toggle('active',
            link.getAttribute('href') === '#' + entry.target.id);
        });
      });
    }, { rootMargin: '-20% 0px -70% 0px' });
    links.forEach(function (link) {
      var target = document.querySelector(link.getAttribute('href'));
      if (target) { observer.observe(target); }
    });
  }
}());
"""


def _measure(deliverable: Deliverable) -> list[MeasuredBox]:
    """HTML reflows, so there is no geometry to report — only content.

    The overflow critic skips this format for that reason, and the completeness
    and grounding critics read the text instead.
    """
    return [MeasuredBox(page_id=page.page_id, name="page", text=page.text_content())
            for page in deliverable.pages]
