"""The LangGraph workflow (spec §10).

Three compiled graphs over one set of shared node functions:

    ANALYSIS_GRAPH    parse -> validate -> extract -> standardize -> derive -> calculate
                      -> match -> check -> score -> auto-resolve
    GENERATION_GRAPH  apply resolutions -> summarize -> generate -> verify outputs
    FULL_GRAPH        both, in one shot

The split exists for one concrete reason: **generation must never re-run extraction.**
The original design had a single graph, and the human-in-the-loop round trip re-ran it
from the top — which, once §5.6 landed, meant paying for a vision call on every
conflict the user resolved, and re-rolling the dice on what the model saw each time.
Analysis is now run once and persisted; resolving a conflict and regenerating reads
that back.

Note also what we did *not* do: adopt a LangGraph checkpointer with `interrupt()`.
A `MemorySaver` dies on a uvicorn reload (fatal for a demo), and `SqliteSaver` buys
durability this prototype already gets free from the JSON session store. The upgrade
path is documented in docs/architecture.md.

§10 lists 31 nodes. Implementing 31 LangGraph nodes would be ceremony; these ~13 cover
the same ground, and docs/architecture.md carries a node-by-node traceability table.
"""
from __future__ import annotations

import logging
from pathlib import Path

from langgraph.graph import END, StateGraph

from app.agent.calculations import recompute_derived
from app.agent.consistency import (
    apply_resolutions,
    critical_unresolved,
    registered,
    resolve_conflicts,
    run_checks,
)
from app.agent.data_quality import build_report
from app.agent.standardize import standardize
from app.agent.state import AgentState
from app.config import get_settings
from app.extractors import SUPPORTED_EXTENSIONS, extract_file
from app.generators import charts, pptx_report, xlsx_dashboard
from app.generators.quality_report import write_conflict_report, write_quality_report
from app.llm import tasks
from app.models.pmi import Audience, PMIProject

log = logging.getLogger("pmi.agent")


def _out_dir(state: AgentState) -> Path:
    directory = get_settings().output_dir / state.get("session_id", "default")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# ============================================================ analysis nodes
def parse_request(state: AgentState) -> AgentState:
    """§10.1-6: what was asked for, for whom. Ask about the audience if unclear."""
    parsed = tasks.parse_request(state.get("request_text", ""))
    audience = state.get("audience") or parsed.audience

    log.info("Request parsed: output=%s audience=%s topic=%s",
             parsed.output_type, audience, parsed.topic)
    return {
        "output_type": parsed.output_type,
        "topic": parsed.topic,
        "audience": audience,
        # §4: "If the audience cannot be inferred, the agent asks." It does not guess —
        # the audience reshapes the entire report.
        "needs_audience": audience is None,
        "warnings": list(state.get("warnings", [])) + tasks.drain_warnings(),
    }


def validate_files(state: AgentState) -> AgentState:
    """§10.3: reject what we cannot read, before we pretend to have read it."""
    ok, errors = [], list(state.get("errors", []))

    for raw in state.get("file_paths", []):
        path = Path(raw)
        if not path.exists():
            errors.append(f"{path.name}: file not found")
        elif path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            errors.append(f"{path.name}: unsupported file type '{path.suffix}'")
        else:
            ok.append(raw)

    return {"file_paths": ok, "errors": errors}


def extract(state: AgentState) -> AgentState:
    """§10.9-14: run the format-specific extractor on every file."""
    records: list[dict] = []
    errors = list(state.get("errors", []))

    for raw in state.get("file_paths", []):
        path = Path(raw)
        try:
            found = extract_file(path)
            records.extend(found)
        except Exception as exc:
            # One broken file must not sink the run — but it must not vanish either.
            # This lands in the data-quality report and caps the score (§21.17).
            errors.append(f"{path.name}: {exc}")
            log.warning("extraction failed for %s: %s", path.name, exc)

    return {
        "raw_records": records,
        "errors": errors,
        "warnings": list(state.get("warnings", [])) + tasks.drain_warnings(),
    }


def standardize_node(state: AgentState) -> AgentState:
    """§10.15-17 + §10.20: one data model, then every derived value in plain Python (§11)."""
    project = state.get("project") or PMIProject(
        project_id=state.get("session_id", "p_default"),
        source_files=[Path(p).name for p in state.get("file_paths", [])],
    )

    model = standardize(
        state.get("raw_records", []),
        [Path(p).name for p in state.get("file_paths", [])],
        project=project,
    )
    model, issues = recompute_derived(model, project.reporting_date)
    model.validation_issues.extend(issues)

    log.info("Standardized %d entities across %d workstream(s); %d derived-value issue(s)",
             model.entity_count(), len(model.workstreams), len(issues))
    return {
        "data_model": model,
        "warnings": list(state.get("warnings", [])) + model.warnings,
    }


def check_consistency(state: AgentState) -> AgentState:
    """§10.18-19: match entities across sources, then run all §8 checks."""
    model = state["data_model"]
    results = run_checks(model)

    model.conflicts = results.conflicts
    model.validation_issues.extend(results.issues)  # calculations.py added its own

    log.info("%d check(s) ran: %d conflict(s), %d validation issue(s)",
             len(registered()), len(model.conflicts), len(model.validation_issues))
    return {"data_model": model}


def resolve(state: AgentState) -> AgentState:
    """§10.21-23 + §10.20: apply §9, then score the run."""
    model = state["data_model"]

    model.conflicts = resolve_conflicts(
        model.conflicts,
        strategy=state.get("conflict_strategy"),
        user_choices=state.get("user_conflict_choices"),
    )
    model = apply_resolutions(model)

    report = build_report(
        model,
        failed_files=[e.split(":", 1)[0] for e in state.get("errors", [])],
        warnings=state.get("warnings", []),
    )

    log.info("Data quality %.0f/100 — %d conflict(s) unresolved",
             report.score, report.conflicts_unresolved)
    return {"data_model": model, "quality_report": report}


# ========================================================== generation nodes
def generate_output(state: AgentState) -> AgentState:
    """§10.24-31: the deliverable, plus the two reports the spec always requires."""
    model = state["data_model"]
    audience = state.get("audience") or Audience.PMO
    out_dir = _out_dir(state)

    bullets = tasks.write_summary(model, audience, state.get("request_text", ""))
    output_type = state.get("output_type", "powerpoint")
    report = state.get("quality_report")
    files: list[str] = []

    if output_type == "powerpoint":
        files.append(str(
            pptx_report.generate(model, audience, bullets, out_dir, quality=report)
        ))
    elif output_type == "excel":
        files.append(str(
            xlsx_dashboard.generate(model, audience, bullets, out_dir, quality=report)
        ))
    elif output_type == "chart":
        files.extend(
            str(p) for p in charts.generate(model, state.get("topic", "status"), out_dir)
        )

    # §18.18-19: the conflict report and the data-quality report ship with EVERY run,
    # not only when the user thinks to ask. They are what make the deck defensible.
    if report is not None:
        files.append(str(write_quality_report(model, report, out_dir)))
    if model.conflicts:
        files.append(str(write_conflict_report(model, out_dir)))

    log.info("Generated %s: %s", output_type, [Path(f).name for f in files])
    return {
        "summary_bullets": bullets,
        "output_files": files,
        "warnings": list(state.get("warnings", [])) + tasks.drain_warnings(),
    }


def verify_outputs(state: AgentState) -> AgentState:
    """§10.29 / §21.15: 'Ensure generated files open successfully.'

    A runtime check, not a hope. We re-open every file we just wrote with the library
    a recipient would use. A corrupt deck that we confidently handed over is the worst
    possible failure — the user finds out in the meeting.
    """
    errors = list(state.get("errors", []))
    verified: list[str] = []

    for raw in state.get("output_files", []):
        path = Path(raw)
        try:
            _open_check(path)
            verified.append(raw)
        except Exception as exc:
            errors.append(f"{path.name}: generated file will not open ({exc})")
            log.error("output verification FAILED for %s: %s", path.name, exc)

    return {"output_files": verified, "errors": errors}


def _open_check(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".pptx":
        from pptx import Presentation

        Presentation(str(path))
    elif suffix == ".xlsx":
        from openpyxl import load_workbook

        load_workbook(str(path)).close()
    elif suffix == ".png":
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
    elif suffix == ".md":
        path.read_text(encoding="utf-8")
    else:
        if path.stat().st_size == 0:
            raise ValueError("file is empty")


# ================================================================== the graphs
def _after_parse(state: AgentState) -> str:
    return "ask_user" if state.get("needs_audience") else "validate_files"


def _analysis_nodes(g: StateGraph) -> None:
    g.add_node("parse_request", parse_request)
    g.add_node("validate_files", validate_files)
    g.add_node("extract", extract)
    g.add_node("standardize", standardize_node)
    g.add_node("check_consistency", check_consistency)
    g.add_node("resolve_conflicts", resolve)

    g.set_entry_point("parse_request")
    g.add_conditional_edges(
        "parse_request", _after_parse,
        {"ask_user": END, "validate_files": "validate_files"},
    )
    g.add_edge("validate_files", "extract")
    g.add_edge("extract", "standardize")
    g.add_edge("standardize", "check_consistency")
    g.add_edge("check_consistency", "resolve_conflicts")


def _generation_nodes(g: StateGraph) -> None:
    g.add_node("generate_output", generate_output)
    g.add_node("verify_outputs", verify_outputs)
    g.add_edge("generate_output", "verify_outputs")
    g.add_edge("verify_outputs", END)


def build_analysis_graph():
    """Everything up to (and including) auto-resolution. Stops before generating."""
    g = StateGraph(AgentState)
    _analysis_nodes(g)
    g.add_edge("resolve_conflicts", END)
    return g.compile()


def build_generation_graph():
    """Generation only — fed a data model that analysis already produced."""
    g = StateGraph(AgentState)
    g.add_node("apply_user_resolutions", resolve)
    g.set_entry_point("apply_user_resolutions")
    _generation_nodes(g)
    g.add_edge("apply_user_resolutions", "generate_output")
    return g.compile()


def build_graph():
    """The one-shot path (`POST /api/report`)."""
    g = StateGraph(AgentState)
    _analysis_nodes(g)
    _generation_nodes(g)
    g.add_edge("resolve_conflicts", "generate_output")
    return g.compile()


_ANALYSIS = None
_GENERATION = None
_FULL = None


def run_analysis(state: AgentState) -> AgentState:
    global _ANALYSIS
    if _ANALYSIS is None:
        _ANALYSIS = build_analysis_graph()
    return _ANALYSIS.invoke(state)


def run_generation(state: AgentState) -> AgentState:
    global _GENERATION
    if _GENERATION is None:
        _GENERATION = build_generation_graph()
    return _GENERATION.invoke(state)


def run_agent(state: AgentState) -> AgentState:
    """Analysis + generation in one call."""
    global _FULL
    if _FULL is None:
        _FULL = build_graph()
    return _FULL.invoke(state)


def blocking_conflicts(state: AgentState):
    """High/critical conflicts still awaiting a human (§9 Mode C)."""
    model = state.get("data_model")
    return critical_unresolved(model) if model else []
