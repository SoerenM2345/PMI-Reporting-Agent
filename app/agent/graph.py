"""The LangGraph workflow (spec §10).

Three compiled graphs over one set of shared node functions:

    ANALYSIS_GRAPH    parse -> validate -> extract -> standardize -> derive -> calculate
                      -> match -> check -> score -> auto-resolve
    GENERATION_GRAPH  apply resolutions -> summarize -> generate -> verify outputs

There are two graphs, not three: the one-shot `FULL_GRAPH` and its `/api/report`
endpoint were the pre-chat wizard's path and are gone. Analysis and generation
stay separate for one concrete reason: **generation must never re-run
extraction.** The original design had a single graph, and the human-in-the-loop
round trip re-ran it from the top — which, once §5.6 landed, meant paying for a vision call on every
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
from app.generators import charts, pptx_report
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
    # File analysis needs three routing fields, not another semantic opinion.
    # The complete report planner will interpret the actual request later with
    # the full project and evidence context.
    from app.llm.fallbacks import heuristic_parse

    parsed = heuristic_parse(state.get("request_text", ""))
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
        priority_override=getattr(state.get("project"), "source_priority", None),
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
def plan_content(state: AgentState) -> AgentState:
    """§10.25 `plan_pmi_report`, now an explicit step with a durable result.

    Decides what the report *says* — sections, titles, which rows — before
    anything is drawn. Split out for three reasons: the user can read and
    approve it as text first; re-rendering into a second format reuses it
    instead of re-rolling the summary prose; and a revision ("add a slide about
    the TSA") edits this rather than re-running extraction.

    An approved version passed in by the API wins. Otherwise we plan fresh, so
    callers that never touch the preview behave exactly as they did before.
    """
    from app.report.pipeline import plan_for_session
    from app.storage.json_store import SessionAnalysis

    approved = state.get("report_content")
    if approved is not None:
        return {"report_content": approved,
                "summary_bullets": _summary_bullets(approved)}

    # Designed documents are planned before the user previews them. Their
    # renderer consumes that approved Deliverable directly, so building the
    # legacy ReportContent here cannot affect the file; it only adds another
    # reasoning-model round trip to every PowerPoint/Word/PDF/HTML export.
    # Preserve the response summary from the approved argument without
    # re-planning a second, unused document.
    deliverable = state.get("deliverable")
    output_type = _canonical_format(state.get("output_type", "powerpoint"))
    if deliverable is not None and output_type in (
            "powerpoint", "word", "pdf", "html", "excel"):
        bullets = ([deliverable.executive_takeaway]
                   if deliverable.executive_takeaway else [])
        return {"report_content": None, "summary_bullets": bullets}

    # `plan_for_session` is the only place a report is planned. Feeding it the
    # graph's state as a `SessionAnalysis` keeps this node a caller rather than
    # a fourth implementation — the three that existed before all assembled the
    # bullets, the quality report and the fingerprint slightly differently.
    content = plan_for_session(
        state.get("session_id", ""),
        SessionAnalysis(
            session_id=state.get("session_id", ""),
            request_text=state.get("request_text", ""),
            topic=state.get("topic", "status"),
            audience=state.get("audience") or Audience.PMO,
            data_model=state["data_model"],
            quality_report=state.get("quality_report"),
            errors=list(state.get("errors", [])),
            warnings=list(state.get("warnings", [])),
        ),
        # The graph runs on paths that may have no stored draft to reuse prose
        # from; `plan_for_session` falls back to writing it either way.
        save=False,
    )
    return {
        "report_content": content,
        "summary_bullets": _summary_bullets(content),
        "warnings": list(state.get("warnings", [])) + tasks.drain_warnings(),
    }


def _render_document(output_type: str, content, out_dir: Path, model=None) -> Path:
    """Word, PDF and HTML all read the same approved `ReportContent`."""
    from datetime import date as _date

    if content is None:
        raise ValueError(
            f"{output_type} output needs planned content; plan_content did not run"
        )

    if output_type == "word":
        from app.report.render import docx as renderer

        return renderer.render(content, out_dir)

    if output_type == "pdf":
        from app.report.render import pdf as renderer

        return renderer.render(content, out_dir)

    from app.report.render.html import render_html

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (
        f"PMI_Report_{content.audience.value}_{_date.today().isoformat()}.html"
    )
    # The model lets the dashboard render and inline its charts; without it the
    # page still builds and names the charts instead.
    path.write_text(render_html(content, model, out_dir), encoding="utf-8")
    return path


def _render_charts(content, model, topic: str, out_dir: Path) -> list[Path]:
    """The content's own charts, then the topic's — deduplicated, in order.

    A "generate an image of the milestones" request maps through the topic to
    `milestone_timeline` + `day_1_readiness`; a preview that already carried a
    workstream-progress chart contributes that one first. Rendering the
    approved charts before the topic extras is what stops a picture asserting
    something the preview did not.
    """
    from app.report import charts_registry

    seen: set[str] = set()
    paths: list[Path] = []

    if content is not None:
        for section in content.sections:
            for block in section.blocks:
                if getattr(block, "kind", None) != "chart":
                    continue
                builder = charts_registry.resolve(block.builder)
                if builder is None or block.builder in seen:
                    continue
                seen.add(block.builder)
                try:
                    path = builder(model, out_dir)
                except Exception as exc:                      # noqa: BLE001
                    log.warning("chart %s failed: %s", block.builder, exc)
                    continue
                if path is not None:
                    paths.append(Path(path))

    # Topic-driven extras fill in anything the content did not already show,
    # and guarantee a non-empty result — an empty chart request looks like a
    # broken app.
    for path in charts.generate(model, topic, out_dir):
        if Path(path).name not in {p.name for p in paths}:
            paths.append(Path(path))
    return paths


def _summary_bullets(content) -> list[str]:
    """Keep `/api/generate`'s response shape identical whichever path ran."""
    section = content.section("summary.executive")
    if section is None or not section.blocks:
        return []
    return [item.text for item in section.blocks[0].items]


#: `parse_request` and the chat classifier both emit "image" for a picture; the
#: renderer branch is called "chart". Normalising here rather than at each caller
#: means a new entry point cannot reintroduce the silent fall-through that made
#: "generate an image of the milestones" hand back the data-quality report.
_FORMAT_ALIASES = {"image": "chart", "images": "chart", "picture": "chart",
                   "png": "chart", "graph": "chart", "diagram": "chart",
                   "pptx": "powerpoint", "docx": "word", "xlsx": "excel"}


def _canonical_format(output_type: str) -> str:
    return _FORMAT_ALIASES.get((output_type or "").strip().lower(),
                               output_type or "powerpoint")


def _render_designed(state: AgentState, output_type: str,
                     out_dir: Path) -> list[str]:
    """Render the approved `Deliverable`, planning one only if there is none.

    Planning here rather than reusing the approved plan would break the promise
    the preview makes: the user would approve one document and receive another,
    invisibly, because both look right on their own.

    On failure this returns nothing and records the error, so the run still hands
    over the quality and conflict reports — a session that produces no deck but
    explains why is better than one that 500s.
    """
    from app.agent.cancellation import Cancelled
    from app.deliverable import session as session_plan
    from app.renderers import registry

    session_id = state.get("session_id") or ""
    fmt = registry.normalize(output_type)
    try:
        from app.context import builder
        from app.quality import repair, review

        from app.agent.cancellation import check

        cancel = state.get("cancel")
        deliverable = state.get("deliverable")
        analysis = _analysis_for(state)
        if deliverable is None:
            deliverable = session_plan.plan(session_id, analysis,
                                            request_text=state.get("request_text", ""),
                                            fmt=fmt, cancel=cancel)
        check(cancel, f"rendering the {fmt}")

        context = builder.build_for_session(
            session_id, state.get("request_text", "") or "", analysis=analysis)
        from app.deliverable import references

        references.apply_to_context(
            session_id, context, deliverable.source_use_constraints)
        reviewed = review(deliverable, context, use_model=False)
        if not reviewed.passed:
            deliverable, _applied = repair(deliverable, context, reviewed)

        check(cancel, f"writing the {fmt} file")
        results = registry.render_all(deliverable, context, out_dir, [fmt])
        state["deliverable_warnings"] = (list(deliverable.warnings)
                                        + [w for r in results for w in r.warnings])
        return [str(r.path) for r in results if r.page_count]
    except Cancelled:
        # Re-raised so the turn reports "stopped" rather than "failed": the
        # user asked for this, and a half-written file is never handed over as
        # though it were finished.
        raise
    except Exception as exc:                                   # noqa: BLE001
        log.exception("could not generate the %s deliverable", output_type)
        state["deliverable_errors"] = [
            f"The {output_type} deliverable could not be produced "
            f"({type(exc).__name__}: {exc})."]
        return []


def _analysis_for(state: AgentState):
    """The stored analysis, or one assembled from the state we were handed."""
    from app.storage.json_store import SessionAnalysis, load_analysis

    stored = load_analysis(state.get("session_id", ""))
    if stored is not None:
        return stored
    return SessionAnalysis(
        session_id=state.get("session_id", ""),
        request_text=state.get("request_text", ""),
        output_type=state.get("output_type", "powerpoint"),
        topic=state.get("topic", "status"),
        audience=state.get("audience"),
        data_model=state["data_model"],
        quality_report=state.get("quality_report"))


def generate_output(state: AgentState) -> AgentState:
    """§10.24-31: the deliverable, plus the two reports the spec always requires.

    The designed formats — including the workbook — render the approved
    `Deliverable`, so the deck, the document, the PDF, the web page and the
    workbook can never disagree about a figure the user corrected. Only the
    standalone charts still render from `ReportContent`: a set of PNGs is not a
    document and gains nothing from a storyline.
    """
    model = state["data_model"]
    out_dir = _out_dir(state)

    content = state.get("report_content")
    bullets = state.get("summary_bullets") or []
    output_type = _canonical_format(state.get("output_type", "powerpoint"))
    report = state.get("quality_report")
    files: list[str] = []

    if output_type in ("powerpoint", "word", "pdf", "html", "excel"):
        # The designed formats render the *approved plan* — the very object the
        # preview projected — so the deck, the document, the PDF, the web page
        # and the workbook state exactly what the user read. `ReportContent`
        # remains the revision vocabulary; it is no longer the shape of the
        # artifact.
        files.extend(_render_designed(state, output_type, out_dir))
    elif output_type == "chart":
        deliverable = state.get("deliverable")
        if deliverable is not None:
            from app.context import builder
            from app.deliverable import chart_output, references

            context = builder.build_for_session(
                state.get("session_id", ""), state.get("request_text", "") or "",
                analysis=_analysis_for(state))
            references.apply_to_context(
                state.get("session_id", ""), context,
                deliverable.source_use_constraints)
            files.extend(str(path) for path in chart_output.render(
                deliverable, context, out_dir))
        else:
            files.extend(str(p) for p in _render_charts(
                content, model, state.get("topic", "status"), out_dir))

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
        # Returned, not appended to `state`: the graph merges what a node
        # returns, so a mutation of the input dict is lost.
        "errors": (list(state.get("errors", []))
                   + list(state.get("deliverable_errors", []))),
        "warnings": (list(state.get("warnings", []))
                     + list(state.get("deliverable_warnings", []))
                     + tasks.drain_warnings()),
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
    elif suffix == ".docx":
        from docx import Document

        Document(str(path))
    elif suffix == ".pdf":
        import fitz                       # PyMuPDF, already a dependency

        with fitz.open(str(path)) as document:
            if document.page_count == 0:
                raise ValueError("PDF has no pages")
    elif suffix in (".md", ".html", ".htm"):
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("file is empty")
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
    g.add_node("plan_content", plan_content)
    g.add_node("generate_output", generate_output)
    g.add_node("verify_outputs", verify_outputs)
    g.add_edge("plan_content", "generate_output")
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
    g.add_edge("apply_user_resolutions", "plan_content")
    return g.compile()


_ANALYSIS = None
_GENERATION = None


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


def blocking_conflicts(state: AgentState):
    """High/critical conflicts still awaiting a human (§9 Mode C)."""
    model = state.get("data_model")
    return critical_unresolved(model) if model else []
