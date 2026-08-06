"""Export machine-scorable ground truth for the Dell-EMC v1.0 corpus.

Reads `case.py` (the fact base) and `error_key.py` (the injected-error rows) — the single
sources of truth already used to render every document — and writes two JSON files beside
this one's parent directory:

  ground_truth.json  the 6 designed conflicts (PLANTED_CONFLICTS in case.py), for the
                      `clean` condition and, unioned with errors.json, the `with_errors`
                      condition (see evaluation_study_design.md §2 "Conditions per agent")
  error_key.json      the 10 injected errors (ROWS in error_key.py), machine-readable

Nothing here is authored twice: every value is read from case.py / error_key.py, not
retyped, so the export cannot silently drift from the documents it describes (the property
`audit.py` already enforces for the corpus itself).

Run from anywhere:  python export_ground_truth.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import case as C          # noqa: E402
import error_key as EK     # noqa: E402

V1_0 = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- file mapping
# Which document states which side of each conflict. Traced by hand against the g2_*.py
# generators (grep for the constant, find the enclosing function, read its OUT.save /
# write_text target) rather than inferred from the free-text description in
# PLANTED_CONFLICTS, so this is a source-verified mapping, not a guess.
TRACKER_XLSX = "DellEMC_VCIO_Integration_Tracker_W3_2016-09-29.xlsx"
IT_ONEPAGER_PPTX = "DellEMC_VCIO_Workstream_Status_IT_W3_2016-09-28.pptx"
DASHBOARD_PNG = "DellEMC_VCIO_RAG_Dashboard_Screenshot_2016-09-29.png"
ROADMAP_PPTX = "DellEMC_VCIO_Integration_Roadmap_Day1_to_Day100_2016-09-16.pptx"
WOCHENPROTOKOLL_DOCX = "DellEMC_VCIO_Wochenprotokoll_KW39_2016-09-27.docx"
MAILVERLAUF_HTML = "DellEMC_VCIO_Eskalation_Mailverlauf_M-07_2016-09-28.html"
ROLLENKARTEN_DOCX = "DellEMC_VCIO_Rollenkarten_Integrationsorganisation_2016-08-01.docx"
RACI_HTML = "DellEMC_VCIO_RACI_Matrix_Integration_Hub_2016-09-23.html"
STEERCO_PPTX = "DellEMC_VCIO_SteerCo_Update_Session02_2016-09-29.pptx"
SYNERGY_TRACKER_XLSX = "DellEMC_VCIO_Synergy_Tracker_W3_2016-09-28.xlsx"
RAID_LOG_XLSX = "DellEMC_VCIO_RAID_Log_W3_2016-09-29.xlsx"
TEAMS_ESCALATION_PNG = "DellEMC_VCIO_Teams_Eskalation_R-02_2016-09-29.png"
STEERCO_MINUTES_PDF = "DellEMC_VCIO_SteerCo_Minutes_Session01_signed_2016-09-22.pdf"


def build_conflicts() -> list[dict]:
    return [
        {
            "id": "C1",
            "field": "WS3 IT workstream progress percent",
            "kind": "designed",
            "claims": [
                {"file": TRACKER_XLSX, "sheet": "Massnahmenplan",
                 "value": C.IT_PROGRESS_TRACKER,
                 "note": "average of the WS3 task rows' percent-complete column; "
                         "authoritative, not a separately typed figure"},
                {"file": IT_ONEPAGER_PPTX, "value": C.IT_PROGRESS_ONEPAGER,
                 "note": "workstream one-pager rounds up"},
                {"file": DASHBOARD_PNG, "value": C.IT_PROGRESS_DASHBOARD,
                 "note": "dashboard screenshot cached before the last tracker update"},
            ],
            "correct": C.IT_PROGRESS_TRACKER,
            "resolution_rule": "Excel wins, source priority 1",
            "must_escalate": True,
        },
        {
            "id": "C2",
            "field": "Milestone M-07 (ERP consolidation blueprint) forecast date",
            "kind": "designed",
            "claims": [
                {"file": ROADMAP_PPTX, "value": C.iso(C.M07_ROADMAP),
                 "note": "still carries the original baseline, not the current forecast"},
                {"file": WOCHENPROTOKOLL_DOCX, "value": C.iso(C.M07_MINUTES),
                 "note": "records the first slip"},
                {"file": MAILVERLAUF_HTML, "value": C.iso(C.M07_MAIL),
                 "note": "most recent; explicitly supersedes the Wochenprotokoll date in "
                         "the same thread; matches the tracker"},
            ],
            "correct": C.iso(C.M07_MAIL),
            "resolution_rule": "most recent dated source, which matches the tracker",
            "must_escalate": True,
        },
        {
            "id": "C3",
            "field": "Human Capital (WS4) workstream lead",
            "kind": "designed",
            "claims": [
                {"file": ROLLENKARTEN_DOCX, "value": C.nm("hc_prev"),
                 "note": "role card not updated after the handover"},
                {"file": RACI_HTML, "value": C.nm("WS4"),
                 "note": "states itself authoritative for current staffing"},
            ],
            "correct": C.nm("WS4"),
            "resolution_rule": "RACI page, which states itself to be authoritative for "
                                "staffing",
            "must_escalate": True,
        },
        {
            "id": "C4",
            "field": "Secured synergy run-rate (USD m)",
            "kind": "designed",
            "claims": [
                {"file": STEERCO_PPTX, "value": C.SYN_SECURED_DECK,
                 "note": "rounds up and counts initiatives Finance has not validated"},
                {"file": SYNERGY_TRACKER_XLSX, "sheet": "Summary",
                 "value": C.SYN_SECURED_TRACKER, "note": "exact sum of the register"},
                {"file": SYNERGY_TRACKER_XLSX, "sheet": "Summary",
                 "value": C.SYN_SECURED_VALIDATED,
                 "note": "sum restricted to rows flagged Finance-validated ('Yes'); not a "
                         "separately stated headline figure, derived from the tracker's own "
                         "validated column per decision B-06"},
            ],
            "correct": C.SYN_SECURED_VALIDATED,
            "resolution_rule": "Finance-validated figure only, per decision B-06",
            "must_escalate": True,
        },
        {
            "id": "C5",
            "field": "Severity of risk R-02 (works council consultation)",
            "kind": "designed",
            "claims": [
                {"file": RAID_LOG_XLSX, "sheet": "Risks",
                 "value": f"{C.R02_SEVERITY_REGISTER} ({C.band(C.R02_SEVERITY_REGISTER)})",
                 "note": "likelihood 4 x impact 3, per the register's own columns"},
                {"file": TEAMS_ESCALATION_PNG,
                 "value": f"{C.R02_SEVERITY_CHAT} ({C.band(C.R02_SEVERITY_CHAT)})",
                 "note": "escalated in a Teams thread captured in this screenshot; never "
                         "entered into the RAID log"},
            ],
            "correct": None,
            "resolution_rule": None,
            "expected_behaviour": "flag_stale",
            "must_escalate": True,
            "note": "No resolvable 'correct' value — the point is that the register is "
                    "out of date and the escalation never reached it. Silently keeping "
                    "either number is a failure; the only correct behaviour is to flag "
                    "the register as stale (see evaluation_study_design.md P2).",
        },
        {
            "id": "C6",
            "field": "Owner of action OP-01 (circulate the dependency map)",
            "kind": "designed",
            "claims": [
                {"file": STEERCO_MINUTES_PDF, "value": C.nm(C.OP01_OWNER_MINUTES),
                 "note": "signed minutes; never amended"},
                {"file": MAILVERLAUF_HTML, "value": C.nm(C.OP01_OWNER_MAIL),
                 "note": "reassigned by e-mail after the meeting"},
            ],
            "correct": C.nm(C.OP01_OWNER_MAIL),
            "resolution_rule": "later source, but the divergence itself must be flagged: "
                                "the signed minutes were never amended to match",
            "expected_behaviour": "flag_stale",
            "must_escalate": True,
        },
    ]


def build_errors() -> list[dict]:
    """Reuses error_key.py's ROWS verbatim — the workbook and this export must never diverge."""
    out = []
    for row in EK.ROWS:
        (eid, etype, severity, file_, where, correct, injected, detectable, crosscheck) = row
        out.append({
            "id": eid,
            "class": etype,
            "kind": "injected",
            "severity": severity,
            "file": file_,
            "location": where,
            "correct_value": correct,
            "injected_value": injected,
            "detectability": detectable,
            "cross_check_source": crosscheck,
            "expected_behaviour": (
                "report_unreadable" if eid == "E-01" else "detect_and_report"
            ),
        })
    return out


def main() -> None:
    conflicts = build_conflicts()
    errors = build_errors()

    ground_truth = {
        "corpus_version": "dellemc_vcio_v1.0",
        "generated_from": ["case.py", "error_key.py"],
        "conditions": {
            "clean": {"findable": [c["id"] for c in conflicts], "count": len(conflicts)},
            "with_errors": {
                "findable": [c["id"] for c in conflicts] + [e["id"] for e in errors],
                "count": len(conflicts) + len(errors),
                "note": "the with_errors corpus is a copy of clean, so both the 6 designed "
                        "conflicts and the 10 injected errors are present and findable — "
                        "16 total, not 10 (corpus_integration_plan.md Part 2)",
            },
        },
        "conflicts": conflicts,
        "known_gaps": [
            "Per-entity `stated_in` provenance for the full entity set (milestones, "
            "tasks, risks, synergies, decisions, actions, dependencies, assumptions, "
            "issues) is not yet exported here — only the 6 planted conflicts and 10 "
            "injected errors are. Full entity-level export would require tracing every "
            "field through the g2_*.py generators the way this script's conflict "
            "mapping was traced, and is needed before metric S1 (extraction recall) "
            "can be scored per-entity. The gate metrics (P1-P5) and detection metrics "
            "(S2, S3) do not need it.",
        ],
    }

    error_key = {
        "corpus_version": "dellemc_vcio_v1.0",
        "generated_from": "error_key.py",
        "reference_corpus": "clean",
        "note": "Everything not listed here is byte-identical to clean/. These 10 errors "
                "are additional to, and distinct from, the 6 designed conflicts in "
                "ground_truth.json (see conflicts vs errors, corpus_integration_plan.md).",
        "errors": errors,
    }

    (V1_0 / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2) + "\n")
    (V1_0 / "error_key.json").write_text(json.dumps(error_key, indent=2) + "\n")
    print(f"wrote {V1_0 / 'ground_truth.json'} ({len(conflicts)} conflicts)")
    print(f"wrote {V1_0 / 'error_key.json'} ({len(errors)} errors)")


if __name__ == "__main__":
    main()
