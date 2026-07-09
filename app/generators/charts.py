"""Chart generator (matplotlib, Agg backend) — 'Create a chart about risks' etc."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.models.pmi import PMIDataModel, Severity

GREEN = "#2E7D32"
PALETTE = {"low": "#81C784", "medium": "#F9A825", "high": "#EF6C00", "critical": "#C62828"}


def generate(model: PMIDataModel, topic: str, out_dir: Path) -> list[Path]:
    files: list[Path] = []
    if "risk" in topic and model.risks:
        files.append(_risk_chart(model, out_dir))
    else:
        if model.tasks:
            files.append(_status_chart(model, out_dir))
        if model.budget:
            files.append(_budget_chart(model, out_dir))
        if not files and model.risks:
            files.append(_risk_chart(model, out_dir))
    return files


def _risk_chart(model: PMIDataModel, out_dir: Path) -> Path:
    counts = {s.value: 0 for s in Severity}
    for r in model.risks:
        counts[r.severity.value] += 1
    counts = {k: v for k, v in counts.items() if v}
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(counts.keys(), counts.values(),
           color=[PALETTE.get(k, GREEN) for k in counts])
    ax.set_title("PMI Risks by Severity", fontsize=14, fontweight="bold")
    ax.set_ylabel("Number of risks")
    ax.spines[["top", "right"]].set_visible(False)
    out = out_dir / f"risks_by_severity_{date.today().isoformat()}.png"
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)
    return out


def _status_chart(model: PMIDataModel, out_dir: Path) -> Path:
    counts: dict[str, int] = {}
    for t in model.tasks:
        counts[t.status.value.replace("_", " ")] = counts.get(t.status.value.replace("_", " "), 0) + 1
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(counts.keys(), counts.values(), color=GREEN)
    ax.set_title("Tasks by Status", fontsize=14, fontweight="bold")
    ax.set_ylabel("Number of tasks")
    ax.spines[["top", "right"]].set_visible(False)
    out = out_dir / f"tasks_by_status_{date.today().isoformat()}.png"
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)
    return out


def _budget_chart(model: PMIDataModel, out_dir: Path) -> Path:
    cats = [b.category[:20] for b in model.budget]
    planned = [b.planned or 0 for b in model.budget]
    actual = [b.actual or 0 for b in model.budget]
    x = range(len(cats))
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar([i - 0.2 for i in x], planned, width=0.4, label="Planned", color="#A5D6A7")
    ax.bar([i + 0.2 for i in x], actual, width=0.4, label="Actual", color=GREEN)
    ax.set_xticks(list(x)); ax.set_xticklabels(cats, rotation=20, ha="right")
    ax.set_title("Budget: Planned vs Actual (EUR)", fontsize=14, fontweight="bold")
    ax.legend(); ax.spines[["top", "right"]].set_visible(False)
    out = out_dir / f"budget_planned_vs_actual_{date.today().isoformat()}.png"
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)
    return out
