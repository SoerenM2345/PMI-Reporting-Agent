"""PowerPoint status report generator (python-pptx).

Styling follows the project's Deloitte deck conventions: white background,
dark-green section headers, black title text, footer line.
Slides: title, executive summary, task assignments per owner, milestones,
risks, budget/KPIs (Finance), open conflicts.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

from app.models.pmi import Audience, PMIDataModel

GREEN = RGBColor(0x2E, 0x7D, 0x32)
DARK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x75, 0x75, 0x75)
RED = RGBColor(0xC6, 0x28, 0x28)
AMBER = RGBColor(0xF9, 0xA8, 0x25)
FOOTER = "TUM Project Study x Deloitte 2026"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def generate(model: PMIDataModel, audience: Audience, bullets: list[str],
             out_dir: Path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H

    _title_slide(prs, model, audience)
    _summary_slide(prs, bullets)
    _tasks_slides(prs, model)
    if model.milestones:
        _table_slide(prs, "Milestones",
                     ["ID", "Milestone", "Due", "Status", "Owner"],
                     [[m.id, m.title, str(m.due_date or "—"), m.status.value.replace("_", " "),
                       m.owner or "—"] for m in model.milestones])
    if model.risks:
        _table_slide(prs, "Risks & Mitigations",
                     ["ID", "Risk", "Severity", "Owner", "Mitigation"],
                     [[r.id, r.title, r.severity.value, r.owner or "—",
                       (r.mitigation or "—")[:80]] for r in model.risks])
    if audience == Audience.FINANCE and model.budget:
        _table_slide(prs, "Budget Overview",
                     ["Category", "Planned (EUR)", "Actual (EUR)", "Δ"],
                     [[b.category, _n(b.planned), _n(b.actual),
                       _n((b.actual or 0) - (b.planned or 0))] for b in model.budget])
    if model.kpis:
        _table_slide(prs, "KPIs",
                     ["KPI", "Value", "Unit", "Target", "Source"],
                     [[k.name, _n(k.value), k.unit or "", _n(k.target),
                       k.source.file_name] for k in model.kpis])
    if model.conflicts:
        _conflicts_slide(prs, model)

    out = out_dir / f"PMI_Status_Report_{audience.value}_{date.today().isoformat()}.pptx"
    prs.save(str(out))
    return out


# ------------------------------------------------------------------ slide builders
def _blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _header(slide, title: str, subtitle: str = ""):
    box = slide.shapes.add_textbox(Inches(0.4), Inches(0.25), SLIDE_W - Inches(0.8), Inches(0.9))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run(); r.text = title
    r.font.size, r.font.bold, r.font.color.rgb = Pt(28), True, DARK
    if subtitle:
        p2 = tf.add_paragraph()
        r2 = p2.add_run(); r2.text = subtitle
        r2.font.size, r2.font.color.rgb = Pt(14), GREY
    _footer(slide)


def _footer(slide):
    box = slide.shapes.add_textbox(Inches(0.4), SLIDE_H - Inches(0.4),
                                   Inches(6), Inches(0.3))
    r = box.text_frame.paragraphs[0].add_run()
    r.text = f"{FOOTER} · {date.today().strftime('%d.%m.%Y')}"
    r.font.size, r.font.color.rgb = Pt(9), GREY


def _title_slide(prs, model: PMIDataModel, audience: Audience):
    slide = _blank(prs)
    box = slide.shapes.add_textbox(Inches(0.8), Inches(2.4), SLIDE_W - Inches(1.6), Inches(2.2))
    tf = box.text_frame
    r = tf.paragraphs[0].add_run()
    r.text = "PMI Status Report"
    r.font.size, r.font.bold, r.font.color.rgb = Pt(40), True, DARK
    p2 = tf.add_paragraph()
    r2 = p2.add_run()
    r2.text = (f"{audience.value} view · {date.today().strftime('%d %B %Y')} · "
               f"sources: {', '.join(model.source_files)}")
    r2.font.size, r2.font.color.rgb = Pt(16), GREY
    bar = slide.shapes.add_textbox(Inches(0.8), Inches(2.2), Inches(2.5), Inches(0.12))
    bar.fill.solid(); bar.fill.fore_color.rgb = GREEN; bar.line.fill.background()
    _footer(slide)


def _summary_slide(prs, bullets: list[str]):
    slide = _blank(prs)
    _header(slide, "Executive Summary")
    box = slide.shapes.add_textbox(Inches(0.6), Inches(1.4), SLIDE_W - Inches(1.2), Inches(5.4))
    tf = box.text_frame; tf.word_wrap = True
    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run(); r.text = f"•  {b}"
        r.font.size, r.font.color.rgb = Pt(18), DARK
        p.space_after = Pt(14)


def _tasks_slides(prs, model: PMIDataModel):
    """One section: task assignments grouped per owner — 'specific tasks to
    different people' is the core ask of this use case."""
    by_owner = model.tasks_by_owner()
    if not by_owner:
        return
    owners = sorted(by_owner, key=lambda o: (o == "Unassigned", o))
    per_slide = 3
    for chunk_start in range(0, len(owners), per_slide):
        chunk = owners[chunk_start:chunk_start + per_slide]
        slide = _blank(prs)
        _header(slide, "Task Assignments by Owner",
                "Open items and status per responsible person")
        top = Inches(1.5)
        for owner in chunk:
            tasks = by_owner[owner]
            open_n = sum(1 for t in tasks if t.status.value != "done")
            hdr = slide.shapes.add_textbox(Inches(0.6), top, SLIDE_W - Inches(1.2), Inches(0.35))
            r = hdr.text_frame.paragraphs[0].add_run()
            r.text = f"{owner} — {len(tasks)} task(s), {open_n} open"
            r.font.size, r.font.bold, r.font.color.rgb = Pt(15), True, GREEN
            top += Inches(0.42)
            for t in tasks[:4]:
                line = slide.shapes.add_textbox(Inches(0.9), top, SLIDE_W - Inches(1.8), Inches(0.32))
                r = line.text_frame.paragraphs[0].add_run()
                due = f", due {t.due_date}" if t.due_date else ""
                pct = f" ({t.progress_pct:.0f}%)" if t.progress_pct is not None else ""
                r.text = f"•  {t.title} — {t.status.value.replace('_', ' ')}{pct}{due}"
                r.font.size = Pt(12)
                r.font.color.rgb = RED if t.status.value in ("overdue", "blocked") else DARK
                top += Inches(0.34)
            if len(tasks) > 4:
                more = slide.shapes.add_textbox(Inches(0.9), top, Inches(6), Inches(0.3))
                r = more.text_frame.paragraphs[0].add_run()
                r.text = f"… and {len(tasks) - 4} more (see Excel dashboard)"
                r.font.size, r.font.color.rgb = Pt(11), GREY
                top += Inches(0.34)
            top += Inches(0.15)


def _table_slide(prs, title: str, headers: list[str], rows: list[list[str]]):
    slide = _blank(prs)
    _header(slide, title)
    rows = rows[:12]
    n_rows, n_cols = len(rows) + 1, len(headers)
    tbl_shape = slide.shapes.add_table(
        n_rows, n_cols, Inches(0.5), Inches(1.5), SLIDE_W - Inches(1.0),
        Emu(int(Inches(0.4)) * n_rows))
    tbl = tbl_shape.table
    for j, h in enumerate(headers):
        cell = tbl.cell(0, j)
        cell.text = h
        cell.fill.solid(); cell.fill.fore_color.rgb = GREEN
        r = cell.text_frame.paragraphs[0].runs[0]
        r.font.size, r.font.bold, r.font.color.rgb = Pt(12), True, RGBColor(255, 255, 255)
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = str(val)
            for p in cell.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(11)


def _conflicts_slide(prs, model: PMIDataModel):
    rows = []
    for c in model.conflicts:
        vals = "; ".join(f"{f}: {v}" for f, v in c.values.items())
        res = (f"{c.resolved_value} (from {c.resolved_from}, {c.resolution})"
               if c.resolved_value else "UNRESOLVED — needs decision")
        rows.append([c.entity_key, c.field, vals[:70], res[:70]])
    _table_slide(prs, "Data Consistency — Detected Conflicts",
                 ["Item", "Field", "Reported values", "Resolution"], rows)


def _n(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"
