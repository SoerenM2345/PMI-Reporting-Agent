"""Draw a validated `ChartSpec` three ways, from one specification.

* `to_pptx_native` — a real, editable PowerPoint chart. This is the default for
  the deck, because a consultant who cannot re-point a series at next week's
  numbers will rebuild the slide by hand, and then the deck and the data have
  diverged. The template ships no `chartStyles.xml`, so every colour, font and
  axis property is set explicitly from the `BrandSystem`.
* `to_svg` — inline, interactive, self-contained. No CDN, no chart library: the
  HTML output must stay a single file whose every `src` is a `data:` URI.
* `to_png` — matplotlib, for Word and PDF, and for the chart types PowerPoint
  cannot express natively.

All three read the same `Scale` from `scales.py`, so a chart's PNG and its SVG
cannot disagree about its own axis.

The one behaviour every backend shares: **a missing value is a gap.** Not a zero,
not a skipped category that silently shortens the axis. The bar is absent and the
label says so, because "nobody reported this" and "this is nil" are different
findings and the second is usually the worse one.
"""
from __future__ import annotations

import logging
import textwrap
from html import escape
from pathlib import Path
from typing import Optional, Sequence

from app.templates.brand_system import BrandSystem
from app.visualizations import scales
from app.visualizations.specs import ChartSeries, ChartSpec, DataPoint

log = logging.getLogger("pmi.visualizations.charts")

DPI = 200
#: Category names carry meaning and must remain readable after a chart is
#: reduced to the PDF/Word content width. This is deliberately larger than the
#: numeric-axis tick size, which is supporting furniture rather than content.
MIN_CATEGORY_LABEL_PT = 10.0
#: How a missing value is labelled wherever a value would have been.
MISSING_LABEL = "not reported"


# ================================================================ matplotlib
def to_png(spec: ChartSpec, brand: BrandSystem, out_dir: Path, *,
           size_in: tuple[float, float] = (9.0, 5.0),
           dpi: int = DPI) -> Path:
    """Render to PNG. Used by Word, PDF, and for non-native chart types."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    out_dir.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(figsize=size_in, dpi=dpi)
    figure.patch.set_facecolor(brand.chart.surface)
    axes.set_facecolor(brand.chart.surface)

    try:
        _draw_matplotlib(spec, brand, axes, plt)
    except Exception:                                          # noqa: BLE001
        plt.close(figure)                 # never leak a figure on the error path
        raise

    if spec.chart_type not in ("pie", "donut"):
        scale = _scale_for(spec)
        axes.set_ylim(scale.minimum, scale.maximum)
        axes.set_yticks(list(scale.ticks))
        axes.yaxis.set_major_formatter(FuncFormatter(
            lambda value, _pos: scales.tick_label(
                value, is_percentage=spec.value_axis.is_percentage,
                currency=spec.value_axis.currency)))
        axes.grid(axis="y", color=brand.chart.gridline_color,
                  linewidth=brand.chart.gridline_pt, zorder=0)
        axes.set_axisbelow(True)
        for side in ("top", "right"):
            axes.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            axes.spines[side].set_color(brand.chart.axis_color)
        axes.tick_params(colors=brand.chart.axis_color,
                         labelsize=brand.chart.tick_pt)
        category_labels = (axes.get_yticklabels()
                           if spec.chart_type in ("bar", "stacked_bar")
                           else axes.get_xticklabels())
        for label in category_labels:
            label.set_fontsize(_category_label_pt(brand))
        if spec.value_axis.title:
            axes.set_ylabel(spec.value_axis.title,
                            color=brand.chart.axis_color,
                            fontsize=brand.chart.label_pt)

    if spec.title:
        axes.set_title(spec.title, color=brand.semantic["text"],
                       fontsize=brand.chart.title_pt, loc="left", pad=12)
    if len(spec.series) > 1 and spec.legend != "none":
        axes.legend(frameon=False, fontsize=brand.chart.label_pt,
                    loc="upper center" if spec.legend == "bottom" else "best",
                    bbox_to_anchor=(0.5, -0.12) if spec.legend == "bottom" else None,
                    ncols=min(len(spec.series), 4))

    _note_missing(spec, axes, brand)
    figure.tight_layout()
    path = out_dir / f"{_safe(spec.spec_id)}.png"
    figure.savefig(path, bbox_inches="tight", facecolor=figure.get_facecolor())
    plt.close(figure)
    log.info("rendered chart %s to %s", spec.spec_id, path.name)
    return path


def _draw_matplotlib(spec: ChartSpec, brand: BrandSystem, axes, plt) -> None:
    kind = spec.chart_type
    categories = spec.categories or [p.label for p in spec.all_points()]
    positions = list(range(len(categories)))

    if kind in ("pie", "donut"):
        series = spec.series[0]
        values = [p.value or 0.0 for p in series.points]
        labels = [p.label for p in series.points]
        colors = [brand.series_color(i) for i in range(len(values))]
        axes.pie(values, labels=labels, colors=colors, autopct="%1.0f%%",
                 textprops={"fontsize": brand.chart.label_pt,
                            "color": brand.semantic["text"]},
                 wedgeprops={"width": 0.42} if kind == "donut" else None)
        axes.set_aspect("equal")
        return

    if kind in ("line", "area", "slope"):
        for index, series in enumerate(spec.series):
            color = brand.series_color(index)
            # Missing values break the line rather than being interpolated:
            # drawing through a gap invents a trajectory nobody reported.
            axes.plot(positions, series.values, marker="o", color=color,
                      linewidth=2.0, label=series.name)
            if kind == "area":
                axes.fill_between(positions,
                                  [v or 0.0 for v in series.values],
                                  color=color, alpha=0.18)
        _category_axis(axes, positions, categories, brand)
        return

    if kind in ("scatter", "bubble"):
        for index, series in enumerate(spec.series):
            axes.scatter(positions, series.values,
                         s=[abs(v or 0) * 4 + 40 for v in series.values]
                         if kind == "bubble" else 60,
                         color=brand.series_color(index), alpha=0.8,
                         label=series.name)
        _category_axis(axes, positions, categories, brand)
        return

    if kind == "waterfall":
        _draw_waterfall(spec, brand, axes, positions, categories)
        return

    stacked = kind in ("stacked_column", "stacked_bar")
    horizontal = kind in ("bar", "stacked_bar")
    count = max(len(spec.series), 1)
    width = 0.8 if stacked else 0.8 / count
    bottoms = [0.0] * len(categories)

    for index, series in enumerate(spec.series):
        color = brand.series_color(index)
        values = [p.value for p in series.points]
        offsets = positions if stacked else [
            p - 0.4 + width * (index + 0.5) for p in positions]
        drawable = [v if v is not None else 0.0 for v in values]

        if series.kind_override in ("line", "area"):
            axes.plot(positions, values, marker="o", color=color, linewidth=2.0,
                      label=series.name, zorder=3)
            continue

        bar = axes.barh if horizontal else axes.bar
        kwargs = dict(color=color, label=series.name, zorder=2,
                      edgecolor="none")
        if stacked:
            kwargs["bottom" if not horizontal else "left"] = bottoms
        bars = bar(offsets, drawable, width, **kwargs)

        # Hide the zero-height rectangle a missing value would otherwise draw.
        for rect, value in zip(bars, values):
            if value is None:
                rect.set_visible(False)
        if stacked:
            bottoms = [b + (v or 0.0) for b, v in zip(bottoms, values)]

        if spec.data_labels != "none":
            _label_bars(axes, offsets, values, series.points, brand,
                        horizontal=horizontal)

    _category_axis(axes, positions, categories, brand, horizontal=horizontal)
    _draw_annotations(spec, axes, brand)


def _draw_waterfall(spec: ChartSpec, brand: BrandSystem, axes,
                    positions: Sequence[int], categories: Sequence[str]) -> None:
    points = spec.all_points()
    running = 0.0
    for index, point in enumerate(points):
        value = point.value or 0.0
        is_end = index in (0, len(points) - 1)
        if is_end:
            bottom, height = 0.0, value
            color = brand.semantic["primary"]
        else:
            bottom, height = running, value
            color = (brand.semantic["negative"] if value < 0
                     else brand.semantic["positive"])
        axes.bar(index, height, 0.6, bottom=bottom, color=color, zorder=2,
                 edgecolor="none")
        if not is_end:
            running += value
        else:
            running = value
        axes.annotate(point.display, (index, bottom + height),
                      ha="center", va="bottom" if height >= 0 else "top",
                      fontsize=brand.chart.label_pt,
                      color=brand.semantic["text"])
    _category_axis(axes, positions, categories, brand)


def _category_axis(axes, positions, categories, brand: BrandSystem, *,
                   horizontal: bool = False) -> None:
    setter = axes.set_yticks if horizontal else axes.set_xticks
    labeller = axes.set_yticklabels if horizontal else axes.set_xticklabels
    setter(list(positions))
    limit = 28 if horizontal else 18
    labeller([_wrap(str(c), limit) for c in categories], rotation=0,
             ha="right" if horizontal else "center",
             fontsize=_category_label_pt(brand),
             color=brand.chart.axis_color)


def _label_bars(axes, offsets, values, points: Sequence[DataPoint],
                brand: BrandSystem, *, horizontal: bool) -> None:
    for offset, value, point in zip(offsets, values, points):
        text = point.display if value is not None else MISSING_LABEL
        color = (brand.semantic["muted"] if value is None
                 else brand.semantic["text"])
        if horizontal:
            axes.annotate(text, (value or 0.0, offset), xytext=(4, 0),
                          textcoords="offset points", va="center",
                          fontsize=brand.chart.label_pt, color=color)
        else:
            axes.annotate(text, (offset, value or 0.0), xytext=(0, 4),
                          textcoords="offset points", ha="center",
                          fontsize=brand.chart.label_pt, color=color)


def _draw_annotations(spec: ChartSpec, axes, brand: BrandSystem) -> None:
    for annotation in spec.annotations:
        if annotation.kind in ("target_line", "threshold") \
                and annotation.value is not None:
            axes.axhline(annotation.value, color=brand.semantic["emphasis"],
                         linestyle="--", linewidth=1.2, zorder=1)
            axes.annotate(annotation.text, (0.99, annotation.value),
                          xycoords=("axes fraction", "data"), ha="right",
                          va="bottom", fontsize=brand.chart.label_pt,
                          color=brand.semantic["emphasis"])


def _note_missing(spec: ChartSpec, axes, brand: BrandSystem) -> None:
    missing = [p for p in spec.all_points() if p.is_missing]
    if not missing:
        return
    axes.annotate(f"{len(missing)} value(s) not reported and shown as gaps",
                  (0.0, -0.18), xycoords="axes fraction",
                  fontsize=brand.chart.label_pt, color=brand.semantic["muted"])


# ======================================================================= SVG
def to_svg(spec: ChartSpec, brand: BrandSystem, *,
           width: int = 720, height: int = 380,
           native_tooltips: bool = True) -> str:
    """Inline SVG, self-contained and accessible.

    Every mark carries `data-evidence-id`, `data-label` and `data-value`, so a
    single delegated handler in the page drives tooltips and legend toggling
    without a chart library. They are emitted unconditionally: with no
    JavaScript present they are inert. Standalone SVG uses a native ``<title>``
    tooltip; the HTML renderer disables it because that page supplies one
    styled tooltip of its own. In both cases marks retain an ``aria-label``.
    """
    if spec.chart_type in ("pie", "donut"):
        return _svg_pie(spec, brand, width, height,
                        native_tooltips=native_tooltips)
    return _svg_cartesian(spec, brand, width, height,
                          native_tooltips=native_tooltips)


_PAD_LEFT, _PAD_RIGHT, _PAD_TOP, _PAD_BOTTOM = 64, 16, 28, 56


def _svg_cartesian(spec: ChartSpec, brand: BrandSystem, width: int,
                   height: int, *, native_tooltips: bool = True) -> str:
    scale = _scale_for(spec)
    categories = spec.categories or [p.label for p in spec.all_points()]
    category_lines = [_wrap(str(category), 16).splitlines()
                      for category in categories]
    max_category_lines = max((len(lines) for lines in category_lines), default=1)
    has_legend = len(spec.series) > 1 and spec.legend != "none"
    pad_bottom = (_PAD_BOTTOM + (max_category_lines - 1) * 13
                  + (20 if has_legend else 0))
    plot_w = width - _PAD_LEFT - _PAD_RIGHT
    plot_h = height - _PAD_TOP - pad_bottom
    count = max(len(categories), 1)
    slot = plot_w / count

    def y_of(value: float) -> float:
        return _PAD_TOP + plot_h * (1.0 - scale.position(scale.clamp(value)))

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'class="pmi-chart" data-chart-id="{escape(spec.spec_id)}" '
        f'aria-label="{escape(spec.alt_text or spec.title or spec.spec_id)}" '
        f'preserveAspectRatio="xMidYMid meet">',
    ]
    if native_tooltips:
        parts.append(f"<title>{escape(spec.title or spec.spec_id)}</title>")
    parts.append(f"<desc>{escape(spec.alt_text)}</desc>")

    for tick in scale.ticks:
        y = y_of(tick)
        parts.append(
            f'<line x1="{_PAD_LEFT}" y1="{y:.1f}" x2="{width - _PAD_RIGHT}" '
            f'y2="{y:.1f}" stroke="{brand.chart.gridline_color}" '
            f'stroke-width="{brand.chart.gridline_pt}"/>')
        parts.append(
            f'<text x="{_PAD_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="{brand.chart.tick_pt}" '
            f'fill="{brand.chart.axis_color}">'
            f'{escape(scales.tick_label(tick, is_percentage=spec.value_axis.is_percentage, currency=spec.value_axis.currency))}'
            f'</text>')

    zero_y = y_of(0.0) if scale.minimum < 0 < scale.maximum else y_of(scale.minimum)
    series_count = max(len(spec.series), 1)
    stacked = spec.chart_type in ("stacked_column", "stacked_bar")
    bar_w = (slot * 0.7) if stacked else (slot * 0.7 / series_count)
    bottoms = [0.0] * count

    for series_index, series in enumerate(spec.series):
        color = brand.series_color(series_index)
        if spec.chart_type in ("line", "area", "slope") \
                or series.kind_override in ("line", "area"):
            parts.append(_svg_line(
                series, color, slot, y_of, brand,
                native_tooltips=native_tooltips))
            continue

        for index, point in enumerate(series.points):
            centre = _PAD_LEFT + slot * (index + 0.5)
            x = (centre - bar_w / 2 if stacked
                 else centre - slot * 0.35 + bar_w * series_index)
            if point.value is None:
                # A gap, marked. Not a zero-height bar, which reads as nil.
                parts.append(
                    f'<text x="{centre:.1f}" y="{zero_y - 6:.1f}" '
                    f'text-anchor="middle" font-size="{brand.chart.label_pt}" '
                    f'fill="{brand.semantic["muted"]}">{MISSING_LABEL}</text>')
                continue
            top = y_of(bottoms[index] + point.value) if stacked \
                else y_of(max(point.value, 0.0))
            base = y_of(bottoms[index]) if stacked else zero_y
            label = f"{series.name} — {point.label}: {point.display}"
            parts.append(
                f'<rect class="pmi-mark" x="{x:.1f}" y="{min(top, base):.1f}" '
                f'width="{bar_w:.1f}" height="{abs(base - top):.1f}" '
                f'fill="{color}" '
                f'data-evidence-id="{escape(point.evidence_id)}" '
                f'data-label="{escape(point.label)}" '
                f'data-series="{escape(series.name)}" '
                f'data-value="{escape(point.display)}"'
                + (f' data-note="{escape(point.note)}"' if point.note else "")
                + _svg_mark_tail("rect", label, native_tooltips))
            if stacked:
                bottoms[index] += point.value

    for index, lines in enumerate(category_lines):
        centre = _PAD_LEFT + slot * (index + 0.5)
        y = height - pad_bottom + 18
        tspans = "".join(
            f'<tspan x="{centre:.1f}" dy="{0 if line_index == 0 else 13}">'
            f'{escape(line)}</tspan>'
            for line_index, line in enumerate(lines))
        parts.append(
            f'<text x="{centre:.1f}" y="{y}" text-anchor="middle" '
            f'font-size="{_category_label_pt(brand)}" '
            f'fill="{brand.chart.axis_color}">{tspans}</text>')

    parts.append(
        f'<line x1="{_PAD_LEFT}" y1="{zero_y:.1f}" x2="{width - _PAD_RIGHT}" '
        f'y2="{zero_y:.1f}" stroke="{brand.chart.axis_color}" '
        f'stroke-width="1"/>')

    if has_legend:
        parts.append(_svg_legend(spec, brand, width, height))
    parts.append("</svg>")
    return "\n".join(parts)


def _svg_line(series: ChartSeries, color: str, slot: float, y_of,
              brand: BrandSystem, *, native_tooltips: bool = True) -> str:
    """A polyline that breaks at gaps rather than interpolating through them."""
    runs: list[list[str]] = [[]]
    markers: list[str] = []
    for index, point in enumerate(series.points):
        if point.value is None:
            if runs[-1]:
                runs.append([])
            continue
        x = _PAD_LEFT + slot * (index + 0.5)
        y = y_of(point.value)
        runs[-1].append(f"{x:.1f},{y:.1f}")
        label = f"{series.name} — {point.label}: {point.display}"
        markers.append(
            f'<circle class="pmi-mark" cx="{x:.1f}" cy="{y:.1f}" r="4" '
            f'fill="{color}" data-evidence-id="{escape(point.evidence_id)}" '
            f'data-label="{escape(point.label)}" '
            f'data-series="{escape(series.name)}" '
            f'data-value="{escape(point.display)}"'
            + _svg_mark_tail("circle", label, native_tooltips))
    lines = [f'<polyline points="{" ".join(run)}" fill="none" stroke="{color}" '
             f'stroke-width="2"/>' for run in runs if len(run) > 1]
    return "\n".join(lines + markers)


def _svg_pie(spec: ChartSpec, brand: BrandSystem, width: int,
             height: int, *, native_tooltips: bool = True) -> str:
    import math

    series = spec.series[0] if spec.series else ChartSeries()
    points = [p for p in series.points if p.value is not None]
    total = sum(p.value or 0.0 for p in points) or 1.0
    cx, cy = width / 2, height / 2
    radius = min(width, height) / 2 - 24
    inner = radius * 0.58 if spec.chart_type == "donut" else 0.0

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" class="pmi-chart" '
             f'data-chart-id="{escape(spec.spec_id)}" '
             f'aria-label="{escape(spec.alt_text or spec.title or spec.spec_id)}">']
    if native_tooltips:
        parts.append(f"<title>{escape(spec.title)}</title>")
    parts.append(f"<desc>{escape(spec.alt_text)}</desc>")
    angle = -math.pi / 2
    for index, point in enumerate(points):
        sweep = 2 * math.pi * ((point.value or 0.0) / total)
        end = angle + sweep
        large = 1 if sweep > math.pi else 0
        x1, y1 = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
        x2, y2 = cx + radius * math.cos(end), cy + radius * math.sin(end)
        if inner:
            xi1, yi1 = cx + inner * math.cos(end), cy + inner * math.sin(end)
            xi2, yi2 = cx + inner * math.cos(angle), cy + inner * math.sin(angle)
            path = (f"M {x1:.1f} {y1:.1f} A {radius:.1f} {radius:.1f} 0 {large} 1 "
                    f"{x2:.1f} {y2:.1f} L {xi1:.1f} {yi1:.1f} "
                    f"A {inner:.1f} {inner:.1f} 0 {large} 0 {xi2:.1f} {yi2:.1f} Z")
        else:
            path = (f"M {cx:.1f} {cy:.1f} L {x1:.1f} {y1:.1f} "
                    f"A {radius:.1f} {radius:.1f} 0 {large} 1 {x2:.1f} {y2:.1f} Z")
        label = f"{point.label}: {point.display}"
        parts.append(
            f'<path class="pmi-mark" d="{path}" fill="{brand.series_color(index)}" '
            f'data-evidence-id="{escape(point.evidence_id)}" '
            f'data-label="{escape(point.label)}" '
            f'data-value="{escape(point.display)}"'
            + _svg_mark_tail("path", label, native_tooltips))
        angle = end
    parts.append("</svg>")
    return "\n".join(parts)


def _svg_mark_tail(tag: str, label: str, native_tooltips: bool) -> str:
    """Close an SVG mark with one tooltip mechanism and an accessible name."""
    accessible = f' aria-label="{escape(label)}" tabindex="0"'
    if native_tooltips:
        return accessible + f"><title>{escape(label)}</title></{tag}>"
    return accessible + f"></{tag}>"


def _svg_legend(spec: ChartSpec, brand: BrandSystem, width: int,
                height: int) -> str:
    parts = ['<g class="pmi-legend">']
    x = _PAD_LEFT
    y = height - 14
    for index, series in enumerate(spec.series):
        parts.append(
            f'<rect x="{x}" y="{y - 9}" width="10" height="10" '
            f'fill="{brand.series_color(index)}" '
            f'data-series="{escape(series.name)}"/>')
        parts.append(
            f'<text x="{x + 15}" y="{y}" font-size="{brand.chart.label_pt}" '
            f'fill="{brand.semantic["text"]}">{escape(series.name)}</text>')
        x += 22 + len(series.name) * 6.2
    parts.append("</g>")
    return "\n".join(parts)


# ================================================================ pptx native
def to_pptx_native(spec: ChartSpec, brand: BrandSystem, slide, box):
    """A real, editable PowerPoint chart, styled explicitly.

    `box` is `(left, top, width, height)` in EMU — the geometry of the layout
    slot the visual planner assigned, so this is "positioned by the template",
    not by a magic number.
    """
    from pptx.chart.data import CategoryChartData, XyChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.util import Pt

    name = _PPTX_TYPES.get(spec.chart_type)
    if name is None:
        raise ValueError(f"{spec.chart_type} is not a native pptx chart type")
    kind = getattr(XL_CHART_TYPE, name)

    left, top, width, height = box
    if spec.chart_type in ("scatter", "bubble"):
        data = XyChartData()
        for series in spec.series:
            xy = data.add_series(series.name)
            for index, point in enumerate(series.points):
                if point.value is not None:
                    xy.add_data_point(float(index), point.value)
    else:
        data = CategoryChartData()
        data.categories = spec.categories or [p.label for p in spec.all_points()]
        for series in spec.series:
            # `None` survives into the chart XML as a genuinely blank cell, which
            # PowerPoint renders as a gap. This is the one place the missing-value
            # rule is enforced by *not* doing anything.
            data.add_series(series.name, series.values)

    frame = slide.shapes.add_chart(kind, left, top, width, height, data)
    chart = frame.chart
    apply_chart_brand(chart, brand, spec)

    if len(spec.series) > 1 and spec.legend != "none":
        chart.has_legend = True
        chart.legend.position = (XL_LEGEND_POSITION.BOTTOM
                                 if spec.legend == "bottom"
                                 else XL_LEGEND_POSITION.RIGHT)
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(brand.chart.label_pt)
    else:
        chart.has_legend = False
    return frame


_PPTX_TYPES: dict[str, str] = {
    "column": "COLUMN_CLUSTERED",
    "bar": "BAR_CLUSTERED",
    "stacked_column": "COLUMN_STACKED",
    "stacked_bar": "BAR_STACKED",
    "line": "LINE_MARKERS",
    "area": "AREA",
    "pie": "PIE",
    "donut": "DOUGHNUT",
    "scatter": "XY_SCATTER",
    "bubble": "BUBBLE",
    "waterfall": "COLUMN_STACKED",
}


def apply_chart_brand(chart, brand: BrandSystem, spec: ChartSpec) -> None:
    """Set every visual property explicitly.

    The template defines no `chartStyles.xml`, so there is nothing to inherit:
    an unstyled native chart comes out in PowerPoint's default blue.
    """
    from pptx.util import Pt

    chart.font.size = Pt(brand.chart.label_pt)
    chart.font.color.rgb = brand.pptx_rgb("text")
    # Leave `font.name` unset so the theme's Aptos is inherited on the viewer's
    # machine rather than hard-coded to a font they may not have.

    for index, series in enumerate(chart.series):
        fill = series.format.fill
        fill.solid()
        fill.fore_color.rgb = brand.pptx_rgb(brand.series_color(index))
        line = series.format.line
        line.color.rgb = brand.pptx_rgb(brand.series_color(index))
        line.width = Pt(2.0)

    if spec.data_labels != "none":
        try:
            plot = chart.plots[0]
            plot.has_data_labels = True
            labels = plot.data_labels
            labels.font.size = Pt(brand.chart.label_pt)
            labels.font.color.rgb = brand.pptx_rgb("text")
            labels.number_format_is_linked = False
            labels.number_format = _number_format(spec)
            plot.gap_width = brand.chart.bar_gap_percent
            if len(spec.series) > 1:
                plot.overlap = brand.chart.series_overlap_percent
        except (IndexError, ValueError, AttributeError) as exc:  # noqa: BLE001
            log.debug("could not style data labels on %s (%s)", spec.spec_id, exc)

    for axis, has_grid in ((getattr(chart, "value_axis", None), True),
                           (getattr(chart, "category_axis", None), False)):
        if axis is None:
            continue
        try:
            axis.has_major_gridlines = has_grid
            if has_grid:
                gridlines = axis.major_gridlines.format.line
                gridlines.color.rgb = brand.pptx_rgb("rule")
                gridlines.width = Pt(brand.chart.gridline_pt)
            axis.format.line.color.rgb = brand.pptx_rgb("muted")
            axis.tick_labels.font.size = Pt(
                brand.chart.tick_pt if has_grid else _category_label_pt(brand))
            axis.tick_labels.font.color.rgb = brand.pptx_rgb("muted")
            if has_grid:
                axis.tick_labels.number_format_is_linked = False
                axis.tick_labels.number_format = _number_format(spec)
        except (ValueError, AttributeError) as exc:            # noqa: BLE001
            log.debug("could not style an axis on %s (%s)", spec.spec_id, exc)


def _number_format(spec: ChartSpec) -> str:
    if spec.value_axis.is_percentage:
        return '0"%"'
    if spec.value_axis.currency:
        return '#,##0'
    return "#,##0"


# ================================================================== helpers
def _scale_for(spec: ChartSpec) -> scales.Scale:
    if spec.chart_type in ("stacked_column", "stacked_bar", "area"):
        totals = scales.stacked_totals([s.values for s in spec.series])
        return scales.nice_scale(totals,
                                 is_percentage=spec.value_axis.is_percentage)
    values = [p.value for p in spec.all_points()]
    if spec.chart_type == "waterfall":
        # A bridge's axis must cover the running balance, not just the deltas.
        running, cumulative = 0.0, []
        for index, point in enumerate(spec.all_points()):
            value = point.value or 0.0
            running = value if index in (0, len(values) - 1) else running + value
            cumulative.append(running)
        values = values + cumulative
    return scales.nice_scale(values, is_percentage=spec.value_axis.is_percentage)


def _wrap(text: str, limit: int = 18) -> str:
    lines = textwrap.wrap(
        " ".join((text or "").split()), width=limit,
        break_long_words=True, break_on_hyphens=True,
    )
    return "\n".join(lines) if lines else ""


def _category_label_pt(brand: BrandSystem) -> float:
    return max(float(brand.chart.tick_pt), float(brand.chart.label_pt),
               MIN_CATEGORY_LABEL_PT)


def _safe(name: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "chart"
