"""Drive the Dell-EMC v1.0 corpus through the real API, exactly as the front end does, and
record everything that happened in one `run.json`.

    POST /api/session  ->  POST /api/project  ->  POST /api/upload (x21, fixed order)
       ->  POST /api/analyze
       ->  GET  /api/conflicts/{sid}          # record what was detected, BEFORE resolution
       ->  POST /api/generate                 # MUST be 409 while critical conflicts are open
       ->  POST /api/conflicts/{sid}/resolve   # apply ground-truth resolutions (C1-C4 style)
       ->  POST /api/generate  force=true      # now expect 200; C5/C6-style findings, which
                                                # have no resolvable "correct" value, are left
                                                # open on purpose (see PROTOCOL.md)
       ->  GET  /api/quality/{sid}, /api/issues/{sid}, download every output artefact

Per evaluation_study_design.md §5, everything that must be fixed and logged for a run to
count as reproducible goes into run.json: run ID, git SHA, corpus version + manifest hash,
corpus condition, upload order, every API status code (the 409 above all), the full
conflict payload before and after resolution, the quality report, and wall-clock.

Known gaps, not fabricated: the API does not currently surface temperature, seed, token
counts or cost — these are recorded as null with a note rather than invented. Provider and
model ID are read from GET /api/models, which reports which providers are configured but
not which exact model answered a given call — see PROTOCOL.md "parameters not yet
loggable" for the follow-up this implies before a paid run.

    .venv/bin/python scripts/eval/run_corpus.py --condition clean
    .venv/bin/python scripts/eval/run_corpus.py --condition with_errors --repeat-index 2
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
CORPUS_V1_0 = ROOT / "data" / "corpus" / "dellemc_vcio" / "v1.0"
RUNS_DIR = Path(__file__).resolve().parent / "runs"

DEFAULT_REQUEST_TEXT = "Create a Steering Committee presentation for the current PMI status."


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _manifest_hash() -> str:
    """One combined hash over MANIFEST.sha256 itself, so a run can cite a single string
    for "which exact corpus state" rather than 61 lines."""
    import hashlib

    return hashlib.sha256((CORPUS_V1_0 / "MANIFEST.sha256").read_bytes()).hexdigest()


def _load_ground_truth() -> dict:
    return json.loads((CORPUS_V1_0 / "ground_truth.json").read_text())


def _corpus_files(condition: str) -> list[Path]:
    folder = CORPUS_V1_0 / condition
    # Fixed, deterministic order — the protocol requires this be pinned, not left to
    # filesystem iteration order, which can vary by platform.
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.name != "README.md"),
        key=lambda p: p.name,
    )


def _resolvable_choices(ground_truth: dict) -> dict[str, dict]:
    """Ground-truth resolutions for conflicts that HAVE a correct value (C1-C4 style).

    Conflicts with `correct: null` (C5, C6 — `expected_behaviour: flag_stale`) are
    deliberately excluded: the point under test is whether the agent flags them as stale
    rather than resolving them, so the harness must not resolve them either. These are
    matched by `field` text against the agent's own conflicts (see score.py), since the
    agent mints its own conflict_id and has no way to know our C-IDs.
    """
    return {
        c["id"]: {"value": str(c["correct"])}
        for c in ground_truth["conflicts"]
        if c.get("correct") is not None
    }


def run(base: str, condition: str, repeat_index: int, request_text: str,
        agent_config: str) -> Path:
    client = httpx.Client(base_url=base, timeout=600.0)
    ground_truth = _load_ground_truth()
    files_on_disk = _corpus_files(condition)

    run_id = f"{condition}_{agent_config}_{repeat_index}_{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    record: dict = {
        "run_id": run_id,
        "started_at": started_at,
        "git_sha": _git_sha(),
        "corpus_version": ground_truth["corpus_version"],
        "corpus_manifest_sha256": _manifest_hash(),
        "corpus_condition": condition,
        "agent_config": agent_config,  # "X" (full agent) today; Y/Z are a documented gap
        "repeat_index": repeat_index,
        "upload_order": [p.name for p in files_on_disk],
        "request_text": request_text,
        "api_base": base,
        "steps": [],
        "not_yet_loggable": [
            "temperature", "seed", "token_counts", "cost_usd",
            "exact_model_id_per_call (GET /api/models reports configured providers, "
            "not which model answered a specific request)",
        ],
    }

    def step(name: str, response: httpx.Response, **extra) -> dict:
        entry = {
            "step": name,
            "status_code": response.status_code,
            "elapsed_s": round(time.monotonic() - t0, 3),
            **extra,
        }
        try:
            entry["body"] = response.json()
        except ValueError:
            entry["body"] = response.text[:2000]
        record["steps"].append(entry)
        return entry

    # -- 1. session + project -------------------------------------------------
    resp = client.post("/api/session")
    session_id = resp.json()["session_id"]
    step("create_session", resp)

    resp = client.post("/api/project", json={
        "session_id": session_id,
        "project_name": f"eval-{run_id}",
        "reporting_date": "2016-09-29",
        "day_1_date": "2016-09-07",
    })
    step("set_project", resp)

    # -- 2. upload, fixed order -------------------------------------------------
    files_payload = [
        ("files", (p.name, p.read_bytes(), "application/octet-stream"))
        for p in files_on_disk
    ]
    resp = client.post(f"/api/upload?session_id={session_id}", files=files_payload)
    upload_entry = step("upload", resp)
    saved = set(upload_entry["body"].get("saved", []))
    if saved != set(record["upload_order"]):
        print(f"WARNING: uploaded {len(saved)}/{len(record['upload_order'])} files; "
              f"rejected: {upload_entry['body'].get('rejected')}", file=sys.stderr)

    # -- 3. analyze -------------------------------------------------------------
    resp = client.post("/api/analyze", json={
        "session_id": session_id, "request_text": request_text,
    })
    analyze_entry = step("analyze", resp)
    if analyze_entry["body"].get("needs_audience"):
        record["outcome"] = "failed_audience_detection"
        return _write(record)

    # -- 4. conflicts BEFORE resolution ------------------------------------------
    resp = client.get(f"/api/conflicts/{session_id}")
    step("conflicts_pre_resolution", resp)

    # -- 5. generate WITHOUT force: the 409 assertion ----------------------------
    # The single most important line in the harness (corpus_integration_plan.md §4):
    # it is the difference between a system that escalates and one that merely logs.
    resp = client.post("/api/generate", json={"session_id": session_id})
    gate_entry = step("generate_pre_resolution", resp)
    record["escalation_gate"] = {
        "status_code": gate_entry["status_code"],
        "expected_409_if_critical_conflicts_present": (
            len(analyze_entry["body"].get("blocking_conflicts", [])) > 0
        ),
        "actually_409": gate_entry["status_code"] == 409,
    }

    # -- 6. resolve the ground-truth-resolvable conflicts ------------------------
    choices = _resolvable_choices(ground_truth)
    resp = client.post(f"/api/conflicts/{session_id}/resolve", json={"choices": choices})
    step("resolve_conflicts", resp, choices_applied=choices)

    # -- 7. generate, forced: C5/C6-style findings are deliberately left open ----
    resp = client.post("/api/generate", json={"session_id": session_id, "force": True})
    generate_entry = step("generate_final", resp)

    # -- 8. quality, issues, and every output artefact ---------------------------
    resp = client.get(f"/api/quality/{session_id}")
    step("quality", resp)

    resp = client.get(f"/api/issues/{session_id}")
    step("issues", resp)

    out_dir = RUNS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for filename in generate_entry["body"].get("outputs", []):
        resp = client.get(f"/api/download/{session_id}/{filename}")
        if resp.status_code == 200:
            (out_dir / filename).write_bytes(resp.content)
            downloaded.append(filename)
    record["downloaded_artefacts"] = downloaded

    record["outcome"] = "completed"
    record["wall_clock_s"] = round(time.monotonic() - t0, 3)
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    return _write(record, out_dir)


def _write(record: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (RUNS_DIR / record["run_id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "run.json"
    path.write_text(json.dumps(record, indent=2, default=str) + "\n")
    print(f"wrote {path}")
    return path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--condition", choices=["clean", "with_errors"], required=True)
    p.add_argument("--repeat-index", type=int, default=1)
    p.add_argument("--request-text", default=DEFAULT_REQUEST_TEXT)
    p.add_argument("--agent-config", default="X",
                   help="X = full agent (default; only condition currently wired). "
                        "Y (LLM w/o consistency layer) and Z (keyless deterministic "
                        "baseline) are follow-up work — see PROTOCOL.md.")
    args = p.parse_args()

    run(args.base, args.condition, args.repeat_index, args.request_text, args.agent_config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
