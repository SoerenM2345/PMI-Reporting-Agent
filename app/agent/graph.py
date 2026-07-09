"""The single-agent LangGraph workflow — the 7 steps of the PDF spec (slide 5).

  1. user uploads files + request        (input to the graph)
  2. parse_request / ask audience        (conditional interrupt)
  3. extract                             (Excel/PPTX/PDF/Word/HTML)
  4. standardize                         (one PMI data model)
  5. check_consistency                   (cross-source comparison)
  6. resolve_conflicts                   (Option A ask / Option B source priority)
  7. generate_output                     (PowerPoint / Excel dashboard / chart)
"""
from __future__ import annotations

import logging
from pathlib import Path

from langgraph.graph import END, StateGraph

from app.agent import llm
from app.agent.consistency import apply_resolutions, detect_conflicts, resolve_conflicts
from app.agent.standardize import standardize
from app.agent.state import AgentState
from app.extractors import extract_file
from app.generators import charts, pptx_report, xlsx_dashboard
from app.models.pmi import Audience

log = logging.getLogger("pmi.agent")

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


# ------------------------------------------------------------------ nodes
def parse_request(state: AgentState) -> AgentState:
    """Step 2: derive output type + audience; flag if audience must be asked."""
    parsed = llm.parse_request(state.get("request_text", ""))
    audience = state.get("audience") or parsed["audience"]
    log.info("Parsed request: output=%s audience=%s", parsed["output_type"], audience)
    return {
        "output_type": parsed["output_type"],
        "topic": parsed["topic"],
        "audience": audience,
        "needs_audience": audience is None,
    }


def extract(state: AgentState) -> AgentState:
    """Step 3: run the format-specific extractor on every uploaded file."""
    records: list[dict] = []
    errors: list[str] = list(state.get("errors", []))
    for fp in state["file_paths"]:
        try:
            recs = extract_file(Path(fp))
            log.info("Extracted %d records from %s", len(recs), Path(fp).name)
            records.extend(recs)
        except Exception as exc:  # a broken file must not sink the run
            errors.append(f"{Path(fp).name}: {exc}")
            log.warning("Extraction failed for %s: %s", fp, exc)
    return {"raw_records": records, "errors": errors}


def standardize_node(state: AgentState) -> AgentState:
    """Step 4: raw records -> one standardized PMI data model."""
    model = standardize(
        state["raw_records"],
        [Path(p).name for p in state["file_paths"]],
    )
    log.info("Standardized: %d tasks, %d milestones, %d risks, %d budget, %d KPIs",
             len(model.tasks), len(model.milestones), len(model.risks),
             len(model.budget), len(model.kpis))
    return {"data_model": model}


def check_consistency(state: AgentState) -> AgentState:
    """Step 5: detect cross-source inconsistencies."""
    model = state["data_model"]
    model.conflicts = detect_conflicts(model)
    log.info("Detected %d conflicts", len(model.conflicts))
    return {"data_model": model}


def resolve(state: AgentState) -> AgentState:
    """Step 6: resolve — user choices > source priority (Excel > Word/PDF > PPTX > HTML)."""
    model = state["data_model"]
    model.conflicts = resolve_conflicts(
        model.conflicts,
        strategy=state.get("conflict_strategy", "priority"),
        user_choices=state.get("user_conflict_choices"),
    )
    model = apply_resolutions(model)
    return {"data_model": model}


def generate_output(state: AgentState) -> AgentState:
    """Step 7: produce the requested deliverable."""
    model = state["data_model"]
    audience = state.get("audience") or Audience.PMO
    out_dir = OUTPUT_DIR / state.get("session_id", "default")
    out_dir.mkdir(parents=True, exist_ok=True)

    bullets = llm.write_summary(model, audience, state.get("request_text", ""))
    files: list[str] = []
    output_type = state.get("output_type", "powerpoint")

    if output_type == "powerpoint":
        files.append(str(pptx_report.generate(model, audience, bullets, out_dir)))
    elif output_type == "excel":
        files.append(str(xlsx_dashboard.generate(model, audience, bullets, out_dir)))
    elif output_type == "chart":
        files.extend(str(p) for p in charts.generate(model, state.get("topic", "status"), out_dir))
    log.info("Generated %s -> %s", output_type, files)
    return {"summary_bullets": bullets, "output_files": files}


# ------------------------------------------------------------------ graph
def _route_after_parse(state: AgentState) -> str:
    # Step 2's question is asked by the UI; the graph pauses by ending early.
    return "ask_user" if state.get("needs_audience") else "extract"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("parse_request", parse_request)
    g.add_node("extract", extract)
    g.add_node("standardize", standardize_node)
    g.add_node("check_consistency", check_consistency)
    g.add_node("resolve_conflicts", resolve)
    g.add_node("generate_output", generate_output)

    g.set_entry_point("parse_request")
    g.add_conditional_edges("parse_request", _route_after_parse,
                            {"ask_user": END, "extract": "extract"})
    g.add_edge("extract", "standardize")
    g.add_edge("standardize", "check_consistency")
    g.add_edge("check_consistency", "resolve_conflicts")
    g.add_edge("resolve_conflicts", "generate_output")
    g.add_edge("generate_output", END)
    return g.compile()


_GRAPH = None


def run_agent(state: AgentState) -> AgentState:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH.invoke(state)
