"""PMI chart generation (spec §14). matplotlib, per §14's "Use matplotlib as the default".

The chart types §14 asks for, with the risk heatmap and the milestone timeline as the
two that carry real analytical weight: a heatmap turns a 40-row risk register into one
picture a Steering Committee can act on, and a timeline is the only honest way to show
that four milestones have quietly slipped past Day 1.

Every chart refuses to invent data. A workstream with no reported progress does not
render as a zero-height bar — it renders as "Not Reported", because a bar at zero says
"they did nothing", which is a different and possibly libellous claim (§7).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")  # no display in a container
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from app.models.pmi import PMIDataModel, Severity, Status  # noqa: E402

log = logging.getLogger("pmi.charts")

GREEN = "#2E7D32"
LIGHT_GREEN = "#A5D6A7"
AMBER = "#F9A825"
RED = "#C62828"
GREY = "#9E9E9E"
DARK = "#1A1A1A"

RAG = {
    Severity.LOW: LIGHT_GREEN,
    Severity.MEDIUM: AMBER,
    Severity.HIGH: "#EF6C00",
    Severity.CRITICAL: RED,
}

STATUS_COLOURS = {
    Status.COMPLETED: GREEN,
    Status.IN_PROGRESS: LIGHT_GREEN,
    Status.AT_RISK: AMBER,
    Status.BLOCKED: RED,
    Status.NOT_STARTED: GREY,
    Status.CANCELLED: "#616161",
    Status.UNKNOWN: "#E0E0E0",
}

DPI = 150


def generate(model: PMIDataModel, topic: str, out_dir: Path) -> list[Path]:
    """Pick charts by what the user asked for and what the data can actually support."""
    topic = (topic or "status").casefold()
    wanted: list[Callable[[PMIDataModel, Path], Path | None]] = []

    if "risk" in topic:
        wanted += [risk_heatmap, risks_by_workstream]
    elif "budget" in topic or "cost" in topic:
        wanted += [budget_vs_actual, budget_variance]
    elif "synerg" in topic:
        wanted += [synergy_target_vs_realized]
    elif "milestone" in topic or "timeline" in topic or "day" in topic:
        wanted += [milestone_timeline, day_1_readiness]
    elif "depend" in topic:
        wanted += [overdue_by_workstream]
    else:
        wanted += [workstream_progress, tasks_by_status, risk_heatmap]

    paths: list[Path] = []
    for builder in wanted:
        try:
            path = builder(model, out_dir)
        except Exception as exc:
            log.warning("chart %s failed: %s", builder.__name__, exc)
            continue
        if path is not None:
            paths.append(path)

    # Never hand back nothing: an empty chart request looks like a broken app.
    if not paths:
        fallback = tasks_by_status(model, out_dir) or _empty(
            "No chartable data was found in the uploaded files.", out_dir
        )
        paths.append(fallback)

    return paths


# --------------------------------------------------------------- §14 risk heatmap
def risk_heatmap(model: PMIDataModel, out_dir: Path) -> Path | None:
    """The 5x5 probability x impact matrix (§14).

    Only risks with BOTH factors can be placed. Risks missing one are listed beneath
    rather than dropped, because a risk with an unknown probability is not a low risk —
    it is an unassessed one, and silently omitting it from the picture is how it stays
    unassessed.
    """
    placed = [r for r in model.risks if r.is_fully_scored]
    unplaced = [r for r in model.risks if not r.is_fully_scored]
    if not model.risks:
        return None

    fig, ax = plt.subplots(figsize=(9, 7))

    for probability in range(1, 6):
        for impact in range(1, 6):
            score = probability * impact
            colour = (
                RED if score >= 16 else
                "#EF6C00" if score >= 10 else
                AMBER if score >= 5 else
                LIGHT_GREEN
            )
            ax.add_patch(Rectangle(
                (probability - 0.5, impact - 0.5), 1, 1,
                facecolor=colour, alpha=0.35, edgecolor="white", linewidth=2,
            ))

    from collections import defaultdict

    cells: dict[tuple[int, int], list] = defaultdict(list)
    for risk in placed:
        cells[(risk.probability, risk.impact)].append(risk)

    for (probability, impact), risks in cells.items():
        label = "\n".join(r.risk_id for r in risks[:3])
        if len(risks) > 3:
            label += f"\n+{len(risks) - 3}"
        ax.text(probability, impact, label, ha="center", va="center",
                fontsize=9, fontweight="bold", color=DARK)

    ax.set_xlim(0.5, 5.5)
    ax.set_ylim(0.5, 5.5)
    ax.set_xticks(range(1, 6))
    ax.set_yticks(range(1, 6))
    ax.set_xlabel("Probability →", fontsize=11)
    ax.set_ylabel("Impact →", fontsize=11)
    ax.set_title(f"Risk Heatmap — {len(placed)} risk(s) plotted",
                 fontsize=14, fontweight="bold")
    ax.set_aspect("equal")
    ax.spines[["top", "right"]].set_visible(False)

    if unplaced:
        ax.text(
            0.5, -0.14,
            f"{len(unplaced)} risk(s) could not be plotted — no probability and/or "
            f"impact was reported: {', '.join(r.risk_id for r in unplaced[:6])}"
            f"{'…' if len(unplaced) > 6 else ''}",
            transform=ax.transAxes, ha="center", fontsize=9, color=RED,
        )

    return _save(fig, out_dir, "risk_heatmap")


# ------------------------------------------------------------ §14 workstreams
def workstream_progress(model: PMIDataModel, out_dir: Path) -> Path | None:
    """Progress bar per workstream, RAG-coloured (§14)."""
    reported = [w for w in model.workstreams if w.progress_percentage is not None]
    silent = [w for w in model.workstreams if w.progress_percentage is None]
    if not reported and not silent:
        return None

    fig, ax = plt.subplots(figsize=(10, max(4, 0.5 * len(model.workstreams) + 2)))

    names = [w.name for w in reported]
    values = [w.progress_percentage for w in reported]
    colours = [
        RED if v < 40 else AMBER if v < 70 else GREEN for v in values
    ]

    if reported:
        bars = ax.barh(names, values, color=colours)
        for bar, value in zip(bars, values):
            ax.text(min(value + 1.5, 97), bar.get_y() + bar.get_height() / 2,
                    f"{value:.0f}%", va="center", fontsize=10)

    # Workstreams that reported nothing get a hatched bar and an explicit label —
    # NOT a zero-height bar, which would read as "they achieved nothing" (§7).
    for workstream in silent:
        ax.barh([workstream.name], [100], color="none",
                edgecolor=GREY, hatch="///", linewidth=1)
        ax.text(2, workstream.name, "Not Reported", va="center",
                fontsize=9, color=GREY, style="italic")

    ax.set_xlim(0, 100)
    ax.set_xlabel("Progress (%)")
    ax.set_title("Progress by Workstream", fontsize=14, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.invert_yaxis()

    return _save(fig, out_dir, "workstream_progress")


def overdue_by_workstream(model: PMIDataModel, out_dir: Path) -> Path | None:
    """§14: 'Overdue tasks by workstream'. Overdue is derived from dates, never read
    from a RAG column — which is the point of the check that catches an overdue task
    marked Green (§8.2)."""
    from collections import Counter

    counts = Counter(
        t.workstream or "Unassigned" for t in model.tasks if t.is_overdue
    )
    if not counts:
        return None

    fig, ax = plt.subplots(figsize=(9, 5))
    names, values = zip(*counts.most_common())
    ax.bar(names, values, color=RED)
    ax.set_ylabel("Overdue tasks")
    ax.set_title("Overdue Tasks by Workstream", fontsize=14, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

    return _save(fig, out_dir, "overdue_by_workstream")


def risks_by_workstream(model: PMIDataModel, out_dir: Path) -> Path | None:
    from collections import defaultdict

    grouped: dict[str, dict[Severity, int]] = defaultdict(
        lambda: {s: 0 for s in Severity}
    )
    for risk in model.risks:
        grouped[risk.workstream or "Unassigned"][risk.rating] += 1
    if not grouped:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))
    names = list(grouped)
    bottom = [0] * len(names)

    for severity in (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
        values = [grouped[n][severity] for n in names]
        ax.bar(names, values, bottom=bottom, label=severity.value.title(),
               color=RAG[severity])
        bottom = [b + v for b, v in zip(bottom, values)]

    ax.set_ylabel("Risks")
    ax.set_title("Risks by Workstream and Rating", fontsize=14, fontweight="bold")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

    return _save(fig, out_dir, "risks_by_workstream")


# ---------------------------------------------------------------- §14 tasks
def tasks_by_status(model: PMIDataModel, out_dir: Path) -> Path | None:
    from collections import Counter

    counts = Counter(t.status for t in model.tasks)
    if not counts:
        return None

    fig, ax = plt.subplots(figsize=(9, 5))
    statuses = list(counts)
    ax.bar(
        [s.value.replace("_", " ").title() for s in statuses],
        [counts[s] for s in statuses],
        color=[STATUS_COLOURS.get(s, GREY) for s in statuses],
    )
    ax.set_ylabel("Tasks")
    ax.set_title("Tasks by Status", fontsize=14, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)

    return _save(fig, out_dir, "tasks_by_status")


# ----------------------------------------------------------- §14 milestones
def milestone_timeline(model: PMIDataModel, out_dir: Path) -> Path | None:
    """Planned vs forecast/actual, with slippage drawn as a red bar (§14).

    The single most useful chart in a status pack: it makes a slipped date impossible
    to skim past.
    """
    dated = [m for m in model.milestones if m.planned_date]
    if not dated:
        return None

    dated.sort(key=lambda m: m.planned_date)
    fig, ax = plt.subplots(figsize=(11, max(4, 0.45 * len(dated) + 2)))

    for index, milestone in enumerate(dated):
        planned = milestone.planned_date
        actual = milestone.actual_date or milestone.forecast_date

        ax.plot([planned], [index], marker="|", markersize=16, color=DARK)

        if actual and actual != planned:
            late = actual > planned
            ax.plot([planned, actual], [index, index],
                    color=RED if late else GREEN, linewidth=4, alpha=0.7)
            ax.plot([actual], [index], marker="o", markersize=8,
                    color=RED if late else GREEN)
            if late:
                ax.text(actual, index + 0.25,
                        f"+{(actual - planned).days}d", fontsize=8, color=RED)
        else:
            ax.plot([planned], [index], marker="o", markersize=7,
                    color=STATUS_COLOURS.get(milestone.status, GREY))

    ax.set_yticks(range(len(dated)))
    ax.set_yticklabels([m.name[:44] for m in dated], fontsize=9)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m-%Y"))  # §7
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

    day_1 = model.project.day_1_date
    if day_1:
        ax.axvline(day_1, color=RED, linestyle="--", linewidth=1.5, alpha=0.8)
        ax.text(day_1, -0.7, " Day 1", color=RED, fontsize=9, fontweight="bold")

    ax.set_title("Milestone Timeline — planned vs actual/forecast",
                 fontsize=14, fontweight="bold")
    ax.grid(axis="x", alpha=0.25)
    ax.spines[["top", "right", "left"]].set_visible(False)

    return _save(fig, out_dir, "milestone_timeline")


def day_1_readiness(model: PMIDataModel, out_dir: Path) -> Path | None:
    critical = [t for t in model.tasks if t.is_day_1_critical]
    if not critical:
        return None

    done = sum(1 for t in critical if t.status is Status.COMPLETED)
    percent = done / len(critical) * 100

    fig, ax = plt.subplots(figsize=(8, 3))
    ax.barh([""], [100], color="#EEEEEE")
    ax.barh([""], [percent],
            color=GREEN if percent >= 90 else AMBER if percent >= 70 else RED)
    ax.text(50, 0, f"{percent:.0f}%  ({done} of {len(critical)} Day-1 items complete)",
            ha="center", va="center", fontsize=13, fontweight="bold")
    ax.set_xlim(0, 100)
    ax.set_xticks([])
    ax.set_title("Day 1 Readiness", fontsize=14, fontweight="bold")
    ax.spines[:].set_visible(False)

    return _save(fig, out_dir, "day_1_readiness")


# ------------------------------------------------------------- §14 finance
def budget_vs_actual(model: PMIDataModel, out_dir: Path) -> Path | None:
    items = [b for b in model.budget if b.budget is not None]
    if not items:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(items))
    ax.bar([i - 0.2 for i in x], [b.budget or 0 for b in items],
           width=0.4, label="Budget", color=LIGHT_GREEN)
    ax.bar([i + 0.2 for i in x], [b.actual or 0 for b in items],
           width=0.4, label="Actual", color=GREEN)

    ax.set_xticks(list(x))
    ax.set_xticklabels([b.category[:18] for b in items], rotation=20, ha="right")
    ax.set_ylabel(f"Amount ({items[0].currency})")
    ax.set_title("Budget vs Actual", fontsize=14, fontweight="bold")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)

    return _save(fig, out_dir, "budget_vs_actual")


def budget_variance(model: PMIDataModel, out_dir: Path) -> Path | None:
    items = [b for b in model.budget if b.variance is not None]
    if not items:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))
    values = [b.variance for b in items]
    ax.bar([b.category[:18] for b in items], values,
           color=[RED if v < 0 else GREEN for v in values])
    ax.axhline(0, color=DARK, linewidth=0.8)
    ax.set_ylabel(f"Variance ({items[0].currency}) — negative = over budget")
    ax.set_title("Budget Variance", fontsize=14, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

    return _save(fig, out_dir, "budget_variance")


def synergy_target_vs_realized(model: PMIDataModel, out_dir: Path) -> Path | None:
    items = [s for s in model.synergies if s.target_value is not None]
    if not items:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(items))
    ax.bar([i - 0.2 for i in x], [s.target_value or 0 for s in items],
           width=0.4, label="Target", color=LIGHT_GREEN)
    ax.bar([i + 0.2 for i in x], [s.realized_value or 0 for s in items],
           width=0.4, label="Realized", color=GREEN)

    ax.set_xticks(list(x))
    ax.set_xticklabels([s.title[:18] for s in items], rotation=20, ha="right")
    ax.set_ylabel(f"Value ({items[0].currency})")
    ax.set_title("Synergies — target vs realized", fontsize=14, fontweight="bold")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)

    return _save(fig, out_dir, "synergy_target_vs_realized")


# ------------------------------------------------------------------ helpers
def _save(fig, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}_{date.today().isoformat()}.png"
    # bbox_inches="tight" already fits the figure to its contents, including the notes
    # drawn outside the axes (the heatmap's "could not be plotted" line). Calling
    # tight_layout() as well fights with those and only emits a warning.
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _empty(message: str, out_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12, color=GREY)
    ax.axis("off")
    return _save(fig, out_dir, "no_data")
