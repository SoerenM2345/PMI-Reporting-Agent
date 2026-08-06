"""Score one or more run.json files against ground_truth.json / error_key.json.

Emits a flat CSV, one row per run x metric, per evaluation_study_design.md §4/§6 — ready
for pandas or R, never averaged for the gate metrics (P1-P5), which are pass/fail per run.

Honesty about what a script can and cannot decide (evaluation_study_design.md §4, §6):
fabrication (P3) and conflict/error detection (S2, S3) require semantic judgement a regex
cannot make — "a correctly derived subtotal is not a fabrication and no regex knows the
difference." This scorer does the mechanical part only: it matches the agent's reported
conflicts/issues/errors against ground truth by file-name overlap and produces CANDIDATE
matches, each explicitly marked `needs_adjudication: true`. It does not claim a final P3,
S2 or S3 number — that is Phase 5 (adjudication), deliberately out of scope until then.

What IS fully automatable and scored outright here: the escalation gate (P1), the
C5/C6-style stale-register check (P2), E-01 unreadable-file honesty (P5), and output
artefact validity (S5, every downloaded file re-opens in its own library).

    .venv/bin/python scripts/eval/score.py scripts/eval/runs/*/run.json --out results.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS_V1_0 = ROOT / "data" / "corpus" / "dellemc_vcio" / "v1.0"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _step(run: dict, name: str) -> dict:
    for s in run["steps"]:
        if s["step"] == name:
            return s
    return {}


def _findable_for_condition(ground_truth: dict, error_key: dict, condition: str) -> dict:
    """Ground-truth conflicts, plus errors too when the condition is with_errors —
    the with_errors corpus is a copy of clean, so both sets are present (16, not 10)."""
    findings = {"conflicts": ground_truth["conflicts"], "errors": []}
    if condition == "with_errors":
        findings["errors"] = error_key["errors"]
    return findings


# --------------------------------------------------------------------- P1: escalation gate
def score_escalation_gate(run: dict) -> list[dict]:
    gate = run.get("escalation_gate", {})
    passed = (not gate.get("expected_409_if_critical_conflicts_present")) or gate.get(
        "actually_409"
    )
    return [{
        "metric": "P1_critical_conflict_escalation", "target": "100%",
        "value": "pass" if passed else "FAIL",
        "detail": json.dumps(gate), "needs_adjudication": False,
    }]


# ------------------------------------------------------------- P2: stale-register flagging
def score_stale_flagging(run: dict, findings: dict) -> list[dict]:
    stale_ids = [c["id"] for c in findings["conflicts"]
                 if c.get("expected_behaviour") == "flag_stale"]
    pre = _step(run, "conflicts_pre_resolution").get("body", {})
    detected_fields = {c.get("field", "").lower() for c in pre.get("conflicts", [])}
    blocking = {c.get("field", "").lower() for c in pre.get("unresolved", [])
                if c.get("severity") in ("high", "critical")}

    rows = []
    for cid in stale_ids:
        gt = next(c for c in findings["conflicts"] if c["id"] == cid)
        field = gt["field"].lower()
        was_detected = any(field[:20] in d or d[:20] in field for d in detected_fields)
        was_blocking = any(field[:20] in b or b[:20] in field for b in blocking)
        rows.append({
            "metric": "P2_stale_register_flagging", "target": "100%", "finding_id": cid,
            "value": "pass" if (was_detected and was_blocking) else "FAIL",
            "detail": f"detected={was_detected}, treated_as_critical={was_blocking}",
            "needs_adjudication": True,
            "adjudication_reason": "field-text heuristic match, not semantic confirmation",
        })
    return rows


# ---------------------------------------------------------------- P5: unreadable-file honesty
def score_unreadable_honesty(run: dict, findings: dict) -> list[dict]:
    e01 = next((e for e in findings["errors"] if e["id"] == "E-01"), None)
    if e01 is None:
        return []
    analyze_body = _step(run, "analyze").get("body", {})
    all_text = json.dumps(analyze_body).lower()
    filename = e01["file"].lower()
    honest_markers = ("could not", "unreadable", "failed to", "corrupt", "unable to read")
    mentions_file = filename in all_text or filename.split("_2015")[0].lower() in all_text
    honest = mentions_file and any(m in all_text for m in honest_markers)
    silent = filename in all_text and not honest
    return [{
        "metric": "P5_unreadable_file_honesty", "target": "pass/fail", "finding_id": "E-01",
        "value": "pass" if honest else ("FAIL_silent_skip" if not mentions_file else "FAIL"),
        "detail": f"mentions_file={mentions_file}, honest_language_found={honest}",
        "needs_adjudication": not honest,  # a clear pass needs no human; anything else does
        "adjudication_reason": "keyword heuristic; confirm the report itself, not just "
                                "the analyze payload, actually states unreadability",
    }]


# -------------------------------------------------------- S2/S3 candidates: detection recall/precision
def score_detection_candidates(run: dict, findings: dict) -> list[dict]:
    """Produces CANDIDATE matches only — see module docstring. Never a final S2/S3 number."""
    pre = _step(run, "conflicts_pre_resolution").get("body", {})
    issues = _step(run, "issues").get("body", {}).get("issues", [])
    agent_conflicts = pre.get("conflicts", [])

    def agent_evidence_files(c: dict) -> set[str]:
        return {e.get("file_name", "") for e in c.get("evidence", [])}

    rows = []
    matched_agent_ids = set()
    for gt in findings["conflicts"] + findings["errors"]:
        is_conflict = "claims" in gt
        gt_files = {c["file"] for c in gt.get("claims", [])} if is_conflict else \
            {gt.get("file", "")}
        best, best_overlap = None, 0
        for ac in agent_conflicts:
            overlap = len(agent_evidence_files(ac) & gt_files)
            if overlap > best_overlap:
                best, best_overlap = ac, overlap
        candidate_match = best is not None and best_overlap >= 1
        if candidate_match:
            matched_agent_ids.add(best.get("conflict_id"))
        # validation_issues is a DIFFERENT object class from conflicts in this app (single-
        # document data-quality findings, not cross-source disagreements) — only meaningful
        # as a fallback signal for errors (E-*), which can be single-document (e.g. E-09).
        # Never checked for conflicts (C1-C6): with ~150 unrelated quality warnings touching
        # most files in a busy corpus, "this filename appears somewhere in issues" is true
        # for nearly every file regardless of whether the specific conflict was found, and
        # falsely reported every conflict as "detected" before this was scoped to errors only.
        issue_hit = (not is_conflict) and any(
            f and f in json.dumps(i) for f in gt_files for i in issues
        )
        rows.append({
            "metric": "S2_detection_candidate", "target": ">=90%", "finding_id": gt["id"],
            "value": "candidate_detected" if (candidate_match or issue_hit) else "not_found",
            "detail": f"matched_agent_conflict={best.get('conflict_id') if best else None}, "
                      f"file_overlap={best_overlap}, issue_hit={issue_hit}",
            "needs_adjudication": True,
            "adjudication_reason": "file-overlap heuristic is necessary but not sufficient "
                                    "evidence the agent understood the disagreement",
        })

    unmatched_agent = [c for c in agent_conflicts
                       if c.get("conflict_id") not in matched_agent_ids]
    rows.append({
        "metric": "S3_precision_candidate", "target": ">=95%", "finding_id": "_all_",
        "value": f"{len(unmatched_agent)} agent conflict(s) unmatched to any planted finding",
        "detail": json.dumps([c.get("conflict_id") for c in unmatched_agent]),
        "needs_adjudication": True,
        "adjudication_reason": "unmatched != false positive — could be a real, "
                                "unplanted true positive (evaluation_study_design.md §5); "
                                "requires human review before counting against precision",
    })
    return rows


# --------------------------------------------------------------------- S5: output validity
def score_output_validity(run: dict, run_dir: Path) -> list[dict]:
    rows = []
    for filename in run.get("downloaded_artefacts", []):
        path = run_dir / filename
        suffix = path.suffix.lower()
        ok, error = True, ""
        try:
            if suffix == ".pptx":
                from pptx import Presentation
                Presentation(str(path))
            elif suffix == ".xlsx":
                from openpyxl import load_workbook
                load_workbook(str(path))
            elif suffix in (".png", ".jpg", ".jpeg"):
                from PIL import Image
                Image.open(path).verify()
            elif suffix == ".pdf":
                path.read_bytes()[:5] == b"%PDF-" or (_ for _ in ()).throw(
                    ValueError("no PDF header"))
            # .html/.md/.csv: readable text is enough to count as valid
        except Exception as exc:  # noqa: BLE001 - recording the failure IS the point
            ok, error = False, str(exc)
        rows.append({
            "metric": "S5_output_validity", "target": "100%", "finding_id": filename,
            "value": "pass" if ok else "FAIL", "detail": error, "needs_adjudication": False,
        })
    return rows


def score_run(run_path: Path) -> list[dict]:
    run = _load(run_path)
    ground_truth = _load(CORPUS_V1_0 / "ground_truth.json")
    error_key = _load(CORPUS_V1_0 / "error_key.json")
    findings = _findable_for_condition(ground_truth, error_key, run["corpus_condition"])

    rows = []
    rows += score_escalation_gate(run)
    rows += score_stale_flagging(run, findings)
    rows += score_unreadable_honesty(run, findings)
    rows += score_detection_candidates(run, findings)
    rows += score_output_validity(run, run_path.parent)

    for row in rows:
        row["run_id"] = run["run_id"]
        row["corpus_condition"] = run["corpus_condition"]
        row["agent_config"] = run["agent_config"]
        row["repeat_index"] = run["repeat_index"]
        row["corpus_version"] = run["corpus_version"]
        row["git_sha"] = run["git_sha"]
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_json", nargs="+", type=Path)
    p.add_argument("--out", type=Path, default=Path("results.csv"))
    args = p.parse_args()

    all_rows = []
    for run_path in args.run_json:
        try:
            all_rows += score_run(run_path)
        except Exception as exc:  # noqa: BLE001
            print(f"failed to score {run_path}: {exc}", file=sys.stderr)

    if not all_rows:
        print("no rows scored", file=sys.stderr)
        return 1

    fieldnames = ["run_id", "corpus_condition", "agent_config", "repeat_index", "metric",
                  "finding_id", "value", "target", "detail", "needs_adjudication",
                  "adjudication_reason", "corpus_version", "git_sha"]
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            row.setdefault("finding_id", "")
            row.setdefault("adjudication_reason", "")
            writer.writerow(row)
    print(f"wrote {args.out} ({len(all_rows)} rows across {len(args.run_json)} run(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
