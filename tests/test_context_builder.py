"""The generation context (`app/context/`).

Phase 1's whole claim is that the request and the project's own context reach
generation. Two things used to be true and are asserted false here: that
`planner.plan()` never saw the user's words, and that
`chat_store.Project.knowledge` reached no prompt at all.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.context import builder
from app.context.schemas import CompanyNames, GenerationContext, KnowledgeDigest
from app.extractors.base import make_source
from app.models.entities import PMIProject
from app.models.pmi import (
    Conflict,
    PMIDataModel,
    Severity,
    SourceFormat,
    Status,
    Task,
)
from app.models.quality import ConflictEvidence
from app.storage import chat_store

XLSX = SourceFormat.EXCEL


@pytest.fixture
def model() -> PMIDataModel:
    xlsx = make_source("tracker.xlsx", XLSX, sheet_name="Workplan")
    return PMIDataModel(
        project=PMIProject(project_id="p1", reporting_date=date(2026, 7, 27),
                           reporting_period="July 2026"),
        source_files=["tracker.xlsx"],
        tasks=[Task(task_id="T1", title="ERP migration cutover", owner="Anna",
                    workstream="IT", status=Status.IN_PROGRESS,
                    progress_percentage=40.0,
                    due_date=date(2026, 8, 1), source_references=[xlsx])],
    )


def build(model, request, **kwargs) -> GenerationContext:
    """The private assembler, exercised without touching either store."""
    return builder._assemble(
        scope="project", project_id="proj", chat_id=None, session_id=None,
        model=model, digest=kwargs.pop("digest", KnowledgeDigest()),
        folder_name=kwargs.pop("folder_name", ""), quality=None,
        request_text=request, requested_format=None,
        messages=kwargs.pop("messages", []),
    )


# =================================================== §19: context is used
def test_company_names_in_project_context_reach_the_deliverable(model):
    """§19 "Context use". The names are in the user's free text and nowhere else.

    Nothing used to read `chat_store.Project.knowledge` outside CRUD, so a
    project whose background said exactly who was merging still produced a
    document titled "PMI Project".
    """
    digest = KnowledgeDigest(
        free_text="MedAxis SE is integrating NordCare GmbH. Day 1 is 1 October.")
    context = build(model, "Prepare a status update.", digest=digest)

    assert context.company_names.acquirer == "MedAxis SE"
    assert context.company_names.target == "NordCare GmbH"
    assert context.project_name == "MedAxis SE / NordCare GmbH"
    assert context.subject_line() == "MedAxis SE is integrating NordCare GmbH."
    assert "PMI Project" not in context.display_name()


def test_the_generic_project_title_no_longer_exists(model):
    """A default that is indistinguishable from a real name is worse than none."""
    assert PMIProject(project_id="x").project_name == ""
    context = build(model, "Prepare a status update.")
    assert context.project_name == ""
    # Display sites still get a string — just never a fabricated one.
    assert context.display_name() == "Untitled integration report"
    assert model.project_name == "(unnamed project)"


def test_the_name_resolution_chain_prefers_the_most_specific(model):
    header = PMIProject(project_id="p", deal_name="Project Aurora")
    companies = CompanyNames(acquirer="MedAxis SE", target="NordCare GmbH")

    assert builder.resolve_project_name(header, "Folder", companies, "") == \
        "Project Aurora"
    assert builder.resolve_project_name(PMIProject(project_id="p"), "Folder",
                                        companies, "") == "Folder"
    assert builder.resolve_project_name(PMIProject(project_id="p"), "",
                                        companies, "") == "MedAxis SE / NordCare GmbH"
    assert builder.resolve_project_name(
        PMIProject(project_id="p"), "", CompanyNames(),
        "a deck for the Helios integration") == "Helios"
    assert builder.resolve_project_name(PMIProject(project_id="p"), "",
                                        CompanyNames(), "hello") == ""


def test_company_extraction_stops_at_the_legal_form(model):
    """Without a boundary the greedy capture turns half a sentence into a name."""
    digest = KnowledgeDigest(free_text=(
        "Following board approval, MedAxis SE is integrating NordCare GmbH "
        "across all European operations from October."))
    context = build(model, "Status please.", digest=digest)
    assert context.company_names.target == "NordCare GmbH"
    assert "European" not in (context.company_names.target or "")


def test_an_unnamed_project_is_flagged_rather_than_papered_over(model):
    context = build(model, "Give me a report.")
    assert any(g.gap_id == "unnamed_project" for g in context.gaps)
    assert all(g.severity != "block" for g in context.gaps if g.gap_id ==
               "unnamed_project")


# ============================================ §19: requested sections survive
ELEVEN = """Prepare a finance-focused SteerCo pack with these sections:
1. Executive Summary
2. Financial Integration Status
3. Budget vs. Actual Analysis
4. Synergy Realization Dashboard
5. Cost Savings Progress
6. One-Time Integration Costs
7. Cash Flow Impact
8. Key Financial KPIs
9. Major Risks and Issues
10. Decisions Required from the Steering Committee
11. Recommended Next Steps
"""


def test_all_eleven_requested_sections_are_captured_verbatim(model):
    """§19 "Requested sections". The planner may retitle or regroup. It may not
    lose them, and it cannot lose what it was never given."""
    context = build(model, ELEVEN)
    assert len(context.requested_sections) == 11
    assert context.requested_sections[0] == "Executive Summary"
    assert context.requested_sections[6] == "Cash Flow Impact"
    assert context.requested_sections[-1] == "Recommended Next Steps"
    assert "Decisions Required from the Steering Committee" in \
        context.requested_sections


def test_a_requested_section_with_no_evidence_becomes_a_stated_gap(model):
    context = build(model, ELEVEN)
    gap = context.evidence.get("ev:absence:cash-flow-impact")
    assert gap is not None and gap.is_absence
    assert "Cash Flow Impact" in gap.statement


def test_sections_are_also_read_from_an_inline_list(model):
    context = build(model, "Write a report covering: budget position, "
                           "open risks, and next steps.")
    assert context.requested_sections == ["budget position", "open risks",
                                          "next steps"]


def test_slides_on_preserves_the_cfo_outline_verbatim(model):
    context = build(
        model,
        "Create a Finance Status Report for the CFO based on the uploaded PMI "
        "documents. Create slides on Budget Overview, Synergy Realization, "
        "Cost Tracking, Financial Risks, Forecast vs. Actuals, and Key "
        "Financial Decisions.",
    )
    assert context.requested_sections == [
        "Budget Overview", "Synergy Realization", "Cost Tracking",
        "Financial Risks", "Forecast vs. Actuals", "Key Financial Decisions",
    ]


def test_prose_does_not_get_mined_for_imaginary_sections(model):
    """Guessing sections out of a sentence invents structure the user did not
    ask for — the exact failure this redesign exists to end."""
    context = build(model, "How is the integration going? Anything I should "
                           "worry about before Thursday?")
    assert context.requested_sections == []


def test_an_inline_numbered_list_is_read_as_sections(model):
    """How people actually type it into a chat box, on one line."""
    context = build(model, "Create a status report for the steering committee "
                           "with the following sections: 1. Risks 2. Budget "
                           "3. Milestones")
    assert context.requested_sections == ["Risks", "Budget", "Milestones"]


# ============================== §17: a structure outlives the turn that gave it
def test_a_remembered_structure_survives_a_turn_that_names_none(model):
    """"Now make it a Word document" names no sections. Before this, the order
    the user gave three turns ago was simply lost — it was stored in
    `kb.structure`, read only by the retired `ReportContent` planner, and the
    new engine never looked at it."""
    digest = KnowledgeDigest(
        requested_structure=["Risks", "Budget", "Milestones"])
    context = build(model, "Now make it a Word document.", digest=digest)

    assert context.requested_sections == ["Risks", "Budget", "Milestones"]


def test_a_structure_named_this_turn_beats_the_remembered_one(model):
    """The same precedence `request_history` follows: the latest ask wins."""
    digest = KnowledgeDigest(
        requested_structure=["Risks", "Budget", "Milestones"])
    context = build(model, "Actually, use these sections: 1. Synergies "
                           "2. Decisions Required", digest=digest)

    assert context.requested_sections == ["Synergies", "Decisions Required"]


def test_a_malformed_stored_structure_is_ignored_rather_than_fatal(model):
    """`kb.structure` is stored untyped so `report.structure` can own the
    schema. A half-written one must cost the structure, never the report."""
    assert builder._structure_titles(None) == []
    assert builder._structure_titles({"sections": [None, {}, {"title": "  "}]}) == []
    assert builder._structure_titles({"sections": [{"title": " Risks "}]}) == ["Risks"]


def test_the_verbatim_request_is_preserved(model):
    context = build(model, ELEVEN)
    assert context.user_request.strip().startswith("Prepare a finance-focused")
    assert "Cash Flow Impact" in context.user_request


# ================================================= the request stops being sticky
class _Message:
    def __init__(self, text, role="user", at="2026-07-27T10:00:00Z"):
        self.message_id = f"m{at}"
        self.role = role
        self.kind = "text"
        self.content = {"text": text}
        self.created_at = at
        self.superseded = False


def test_a_refined_request_replaces_the_first_one(model):
    """`conversation.py` only ever set `request_text` when it was empty, so a
    user who refined the ask three times got their first sentence."""
    messages = [
        _Message("Give me a status report", at="2026-07-27T10:00:00Z"),
        _Message("Actually make it finance-focused", at="2026-07-27T10:05:00Z"),
        _Message("Please prepare a CFO budget deck", at="2026-07-27T10:09:00Z"),
    ]
    context = build(model, "Please prepare a CFO budget deck", messages=messages)
    assert context.user_request == "Please prepare a CFO budget deck"
    assert len(context.request_history) == 3
    assert context.request_history[0] == "Give me a status report"
    assert context.request_history[-1] == context.user_request


def test_relevant_chat_turns_are_selected_and_ordered_for_reading(model):
    messages = [
        _Message("Uploaded the trackers", at="2026-07-27T09:00:00Z"),
        _Message("The ERP migration is the thing I care about",
                 at="2026-07-27T09:30:00Z"),
        _Message("thanks", at="2026-07-27T09:40:00Z"),
    ]
    context = build(model, "report on the ERP migration", messages=messages)
    texts = [m.text for m in context.relevant_chat_messages]
    assert any("ERP migration" in t for t in texts)
    ats = [m.at for m in context.relevant_chat_messages]
    assert ats == sorted(ats), "excerpts must read chronologically"


def test_the_chat_summary_is_deterministic_and_needs_no_model(model):
    messages = [_Message("Please prepare a board update")]
    context = build(model, "Please prepare a board update", messages=messages)
    assert "Please prepare a board update" in context.chat_summary


# ==================================================== audience, format, visuals
@pytest.mark.parametrize("request_text,expected", [
    ("Prepare a pack for the Steering Committee", "Steering Committee"),
    ("A one-pager for the CFO please", "CFO"),
    ("Prepare a report for the CHRO", "CHRO"),
    ("Prepare a report for the Chief Human Resources Officer", "Chief Human Resources Officer"),
    ("Prepare a report for the HR Business Partner", "HR Business Partner"),
    ("Give the IMO a status update", None),
    ("board update on synergies", "board"),
])
def test_the_audience_is_kept_in_the_users_own_words(model, request_text, expected):
    """"For the CFO" and "for the Steering Committee" are different documents.

    Collapsing both onto one enum is what made every executive deck identical.
    """
    assert builder.requested_audience(request_text) == expected


def test_requested_visuals_and_format_are_recognised(model):
    context = build(model, "Build an interactive dashboard with a synergy "
                           "waterfall and a risk heatmap.")
    assert context.requested_output_format == "html"
    assert set(context.requested_visuals) >= {"dashboard", "waterfall", "heatmap"}


def test_a_deck_request_asks_for_pptx(model):
    assert build(model, "put together a short deck").requested_output_format == "pptx"


# ======================================================== user constraints
def test_hard_limits_are_captured_for_the_critic(model):
    context = build(model, "A one-pager for the CFO, in German, no charts.")
    kinds = {(c.kind, c.value) for c in context.user_constraints}
    assert ("max_pages", "1") in kinds
    assert ("language", "German") in kinds
    assert ("no_charts", "true") in kinds


def test_a_page_budget_is_read_from_several_phrasings(model):
    for text, expected in (("no more than 8 slides", "8"),
                           ("keep it to 5 pages", "5"),
                           ("a 3-page summary", "3")):
        found = [c.value for c in builder.user_constraints(text, KnowledgeDigest())
                 if c.kind == "max_pages"]
        assert found == [expected], text


def test_standing_project_instructions_apply_to_every_deliverable(model):
    digest = KnowledgeDigest(
        free_text="Always cite the source file for every figure.")
    context = build(model, "status update", digest=digest)
    standing = [c for c in context.user_constraints
                if c.source == "project_knowledge"]
    assert standing and "Always cite" in standing[0].value


# ========================================================= knowledge digest
def test_both_knowledge_stores_project_into_one_shape():
    digest = KnowledgeDigest(
        free_text="MedAxis SE is integrating NordCare GmbH.",
        confirmed_facts=["Day 1 is 1 October 2026."],
        assumptions=["Headcount synergies land in Q4."],
        decisions=["The user resolved a source conflict to 82."],
    )
    markdown = digest.as_markdown()
    assert "Project background" in markdown
    assert "Confirmed facts" in markdown
    assert "Assumptions (not evidenced)" in markdown

    pairs = dict((statement, origin) for origin, statement in
                 digest.as_evidence_pairs())
    assert pairs["Day 1 is 1 October 2026."] == "user_confirmed"
    assert pairs["Headcount synergies land in Q4."] == "user_assumption"
    assert pairs["MedAxis SE is integrating NordCare GmbH."] == "project_context"


def test_project_context_becomes_retrievable_evidence(model):
    digest = KnowledgeDigest(free_text="MedAxis SE is integrating NordCare GmbH.")
    context = build(model, "status", digest=digest)
    contextual = context.evidence.of_kind("context")
    assert contextual and "MedAxis SE" in contextual[0].statement


def test_an_assumption_stays_an_assumption_in_the_evidence(model):
    digest = KnowledgeDigest(assumptions=["Headcount synergies land in Q4."])
    context = build(model, "status", digest=digest)
    item = context.evidence.of_kind("assumption")[0]
    assert item.origin == "user_assumption"
    assert item.is_quotable_fact is False


# ============================================================ completeness
def test_nothing_to_report_on_blocks(model):
    context = build(PMIDataModel(), "give me a deck")
    gap = next(g for g in context.gaps if g.gap_id == "no_evidence")
    assert gap.severity == "block"
    assert context.is_blocked
    assert gap.remedy


def test_unresolved_critical_conflicts_block(model):
    model.conflicts.append(Conflict(
        check_id="PMI-002", entity_type="task", entity_key="ERP migration cutover",
        field="progress_percentage", severity=Severity.CRITICAL,
        evidence=[ConflictEvidence(
            source_reference=make_source("tracker.xlsx", XLSX), value="82"),
            ConflictEvidence(
                source_reference=make_source("weekly.pptx",
                                             SourceFormat.POWERPOINT),
                value="75")],
    ))
    context = build(model, "give me a deck")
    gap = next(g for g in context.gaps if g.gap_id == "unresolved_conflicts")
    assert gap.severity == "block"
    assert "ERP migration cutover" in gap.message
    assert "force" in gap.remedy


def test_a_missing_request_warns_but_does_not_block(model):
    context = build(model, "")
    gap = next(g for g in context.gaps if g.gap_id == "no_request")
    assert gap.severity == "warn"
    assert not context.is_blocked


def test_every_gap_says_what_to_do_about_it(model):
    context = build(PMIDataModel(), "")
    for gap in context.gaps:
        assert gap.message and gap.remedy, gap.gap_id


# =============================================================== the medium
def test_the_context_carries_the_template_and_brand(model):
    context = build(model, "a deck")
    assert context.template_reference is not None
    assert context.brand_system is not None
    assert context.brand_system.semantic["primary"] == "#046A38"


def test_day_1_arithmetic_is_done_in_python(model):
    """The model is never asked to work out how many days are left."""
    model.project.day_1_date = date(2026, 7, 27) + timedelta(days=66)
    context = build(model, "status")
    assert context.transaction.days_to_day_1 == 66


# ============================================================ both stacks
def test_the_two_stacks_produce_the_same_shape(tmp_path, monkeypatch):
    """Nothing downstream should have to know which stack it is serving."""
    monkeypatch.setattr(chat_store, "_db_path", lambda: tmp_path / "chats.db")
    project = chat_store.create_project("MedAxis / NordCare",
                                        knowledge="MedAxis SE is integrating "
                                                  "NordCare GmbH.")
    from app.storage import json_store

    monkeypatch.setattr(json_store, "_base", lambda: tmp_path / "sessions")

    project_ctx = builder.build_for_project(project.project_id,
                                            "Prepare a board update")
    session_ctx = builder.build_for_session(json_store.new_session(),
                                            "Prepare a board update")

    assert project_ctx.scope == "project" and session_ctx.scope == "session"
    assert type(project_ctx) is type(session_ctx)
    assert project_ctx.company_names.acquirer == "MedAxis SE"
    assert project_ctx.user_request == session_ctx.user_request


def test_a_session_chat_inherits_its_linked_project_context(
        tmp_path, monkeypatch, model):
    """A session id alone must still resolve the chat's project and corrections."""
    monkeypatch.setattr("app.config.settings.storage_dir", tmp_path)
    project = chat_store.create_project(
        "GlobalMed / MediTech",
        knowledge=("GlobalMed is integrating MediTech. Always use the Minto "
                   "Pyramid Principle and lead with decisions."),
    )
    from app.agent import knowledge
    from app.agent.knowledge import UserValue
    from app.storage import json_store
    from app.storage.json_store import SessionAnalysis

    session_id = json_store.new_session()
    chat = chat_store.create_chat(session_id, project_id=project.project_id)
    chat_store.add_message(chat.chat_id, "user", {
        "text": "Create a SteerCo deck."})
    json_store.save_analysis(SessionAnalysis(
        session_id=session_id, request_text="Create a SteerCo deck.",
        data_model=model))
    kb = knowledge.load(session_id)
    kb.record_value(UserValue(
        entity_type="task", entity_id="T1", label="ERP migration cutover",
        field="progress_percentage", value=78.0, raw="78%",
        old_value="40%"))
    knowledge.save(kb)

    context = builder.build_for_session(
        session_id, "Create a SteerCo deck.")

    assert context.project_id == project.project_id
    assert context.project_name == "GlobalMed / MediTech"
    assert "Minto Pyramid Principle" in context.project_context
    assert context.chat_id == chat.chat_id
    assert any(fact.value == "78.0"
               for fact in context.project_knowledge.confirmed_values)
    assert any(item.origin == "user_confirmed"
               and "78.0" in item.statement
               for item in context.evidence)
