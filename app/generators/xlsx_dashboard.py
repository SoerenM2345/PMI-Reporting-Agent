"""Excel dashboard generator (XlsxWriter).

Sheets: Overview (summary + KPIs + chart), Tasks (per-owner assignments),
Milestones, Risks, Budget, Conflicts.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import xlsxwriter

from app.models.pmi import Audience, PMIDataModel

GREEN = "#2E7D32"
LIGHT = "#E8F5E9"


def generate(model: PMIDataModel, audience: Audience, bullets: list[str],
             out_dir: Path) -> Path:
    out = out_dir / f"PMI_Dashboard_{audience.value}_{date.today().isoformat()}.xlsx"
    wb = xlsxwriter.Workbook(str(out))
    fmt = _formats(wb)

    _overview(wb, fmt, model, audience, bullets)
    _tasks(wb, fmt, model)
    if model.milestones:
        _sheet(wb, fmt, "Milestones", ["ID", "Milestone", "Due", "Status", "Owner", "Source"],
               [[m.id, m.title, str(m.due_date or ""), m.status.value, m.owner or "",
                 m.source.file_name] for m in model.milestones])
    if model.risks:
        _sheet(wb, fmt, "Risks",
               ["ID", "Risk", "Severity", "Likelihood", "Owner", "Mitigation", "Source"],
               [[r.id, r.title, r.severity.value, r.likelihood or "", r.owner or "",
                 r.mitigation or "", r.source.file_name] for r in model.risks])
    if model.budget:
        _sheet(wb, fmt, "Budget",
               ["ID", "Category", "Planned", "Actual", "Delta", "Source"],
               [[b.id, b.category, b.planned, b.actual,
                 (b.actual or 0) - (b.planned or 0), b.source.file_name]
                for b in model.budget])
    if model.conflicts:
        _sheet(wb, fmt, "Conflicts",
               ["Item", "Field", "Values by file", "Resolved value", "From", "How"],
               [[c.entity_key, c.field,
                 "; ".join(f"{f}: {v}" for f, v in c.values.items()),
                 c.resolved_value or "UNRESOLVED", c.resolved_from or "",
                 c.resolution or ""] for c in model.conflicts])

    wb.close()
    return out


def _formats(wb):
    return {
        "title": wb.add_format({"bold": True, "font_size": 18, "font_color": "#1A1A1A"}),
        "sub": wb.add_format({"font_color": "#757575", "font_size": 10}),
        "hdr": wb.add_format({"bold": True, "bg_color": GREEN, "font_color": "white",
                              "border": 1}),
        "cell": wb.add_format({"border": 1}),
        "num": wb.add_format({"border": 1, "num_format": "#,##0"}),
        "pct": wb.add_format({"border": 1, "num_format": '0"%"'}),
        "owner": wb.add_format({"bold": True, "bg_color": LIGHT, "border": 1}),
        "bullet": wb.add_format({"text_wrap": True, "valign": "top"}),
        "kpi_name": wb.add_format({"bold": True}),
    }


def _overview(wb, fmt, model: PMIDataModel, audience: Audience, bullets: list[str]):
    ws = wb.add_worksheet("Overview")
    ws.set_column("A:A", 55)
    ws.set_column("B:E", 16)
    ws.write(0, 0, "PMI Status Dashboard", fmt["title"])
    ws.write(1, 0, f"{audience.value} view · {date.today().isoformat()} · "
                   f"sources: {', '.join(model.source_files)}", fmt["sub"])

    row = 3
    ws.write(row, 0, "Executive Summary", fmt["hdr"])
    for b in bullets:
        row += 1
        ws.write(row, 0, f"• {b}", fmt["bullet"])

    row += 2
    ws.write(row, 0, "Key Figures", fmt["hdr"])
    prog = model.overall_progress()
    figures = [
        ("Overall progress (avg of task progress)", f"{prog:.0f}%" if prog is not None else "n/a"),
        ("Tasks tracked / open",
         f"{len(model.tasks)} / {sum(1 for t in model.tasks if t.status.value != 'done')}"),
        ("Risks (high/critical)",
         f"{len(model.risks)} ({sum(1 for r in model.risks if r.severity.value in ('high', 'critical'))})"),
        ("Milestones", str(len(model.milestones))),
        ("Conflicts detected / unresolved",
         f"{len(model.conflicts)} / {sum(1 for c in model.conflicts if not c.resolved_value)}"),
    ]
    for name, val in figures:
        row += 1
        ws.write(row, 0, name, fmt["kpi_name"])
        ws.write(row, 1, val)

    if model.kpis:
        row += 2
        ws.write(row, 0, "KPIs", fmt["hdr"])
        ws.write(row, 1, "Value", fmt["hdr"])
        ws.write(row, 2, "Target", fmt["hdr"])
        ws.write(row, 3, "Source", fmt["hdr"])
        for k in model.kpis:
            row += 1
            ws.write(row, 0, k.name, fmt["cell"])
            ws.write(row, 1, k.value if k.value is not None else "", fmt["num"])
            ws.write(row, 2, k.target if k.target is not None else "", fmt["num"])
            ws.write(row, 3, k.source.file_name, fmt["cell"])

    # status distribution chart
    counts: dict[str, int] = {}
    for t in model.tasks:
        counts[t.status.value] = counts.get(t.status.value, 0) + 1
    if counts:
        base = row + 2
        ws.write(base, 0, "Task status distribution (chart data)", fmt["sub"])
        for i, (k, v) in enumerate(counts.items()):
            ws.write(base + 1 + i, 0, k)
            ws.write_number(base + 1 + i, 1, v)
        chart = wb.add_chart({"type": "column"})
        chart.add_series({
            "categories": ["Overview", base + 1, 0, base + len(counts), 0],
            "values": ["Overview", base + 1, 1, base + len(counts), 1],
            "fill": {"color": GREEN},
            "name": "Tasks",
        })
        chart.set_title({"name": "Tasks by status"})
        chart.set_legend({"none": True})
        ws.insert_chart(3, 3, chart, {"x_scale": 1.1, "y_scale": 1.2})


def _tasks(wb, fmt, model: PMIDataModel):
    ws = wb.add_worksheet("Tasks")
    headers = ["ID", "Task", "Owner", "Status", "Progress %", "Due", "Workstream",
               "Priority", "Source"]
    widths = [7, 50, 20, 14, 11, 12, 18, 10, 24]
    for j, (h, w) in enumerate(zip(headers, widths)):
        ws.set_column(j, j, w)
        ws.write(0, j, h, fmt["hdr"])
    row = 0
    for owner, tasks in sorted(model.tasks_by_owner().items(),
                               key=lambda kv: (kv[0] == "Unassigned", kv[0])):
        row += 1
        ws.merge_range(row, 0, row, len(headers) - 1,
                       f"{owner} — {len(tasks)} task(s)", fmt["owner"])
        for t in tasks:
            row += 1
            ws.write(row, 0, t.id, fmt["cell"])
            ws.write(row, 1, t.title, fmt["cell"])
            ws.write(row, 2, t.owner or "", fmt["cell"])
            ws.write(row, 3, t.status.value, fmt["cell"])
            if t.progress_pct is not None:
                ws.write_number(row, 4, t.progress_pct, fmt["pct"])
            else:
                ws.write(row, 4, "", fmt["cell"])
            ws.write(row, 5, str(t.due_date or ""), fmt["cell"])
            ws.write(row, 6, t.workstream or "", fmt["cell"])
            ws.write(row, 7, t.priority or "", fmt["cell"])
            ws.write(row, 8, t.source.file_name, fmt["cell"])
    ws.autofilter(0, 0, max(row, 1), len(headers) - 1)


def _sheet(wb, fmt, name: str, headers: list[str], rows: list[list]):
    ws = wb.add_worksheet(name)
    for j, h in enumerate(headers):
        ws.set_column(j, j, max(14, len(h) + 4))
        ws.write(0, j, h, fmt["hdr"])
    ws.set_column(1, 1, 45)
    for i, r in enumerate(rows, start=1):
        for j, v in enumerate(r):
            if isinstance(v, (int, float)):
                ws.write_number(i, j, v, fmt["num"])
            else:
                ws.write(i, j, "" if v is None else str(v), fmt["cell"])
    ws.autofilter(0, 0, max(len(rows), 1), len(headers) - 1)
