"""Drive the §20 acceptance scenario against a running server, and collect the outputs.

The automated test (`tests/test_acceptance.py`) proves the plumbing using a stored vision
fixture, with no API key. That is the right thing for CI, but it cannot prove the model
actually reads a risk heatmap.

This script closes that gap. It runs the same fifteen steps against a live server with a
real key, prints a §20 checklist, and copies the artefacts into `example_outputs/` —
which is where §18's deliverables 14-19 (the example deck, dashboard, charts, conflict
report and data-quality report) come from.

    docker compose up -d                  # or: uvicorn app.main:app
    ANTHROPIC_API_KEY=... python scripts/demo_acceptance.py
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
EXAMPLES = ROOT / "example_outputs"

UPLOADS = ("integration_tracker.xlsx", "weekly_update.pptx", "risk_dashboard.png")
REQUEST = "Create a Steering Committee presentation for the current PMI status."

PASS, FAIL, INFO = "✓", "✗", "·"
_failures: list[str] = []


def check(ok: bool, step: str) -> bool:
    print(f"  {PASS if ok else FAIL} {step}")
    if not ok:
        _failures.append(step)
    return ok


def main(base: str, allow_keyless: bool = False) -> int:
    client = httpx.Client(base_url=base, timeout=300.0)

    print(f"\nPMI Reporting Agent — §20 acceptance scenario against {base}\n")

    # This script exists to exercise the LIVE vision path — the one thing the automated
    # test cannot prove, because it replays a stored fixture. Without a key that path
    # cannot run, and reporting steps 6 and 8 as "FAILED" would be misleading: nothing
    # is broken, the model simply was not there.
    if not _vision_available(client) and not allow_keyless:
        print("The server has no vision-capable model configured, so §20 steps 6 and 8")
        print("(interpreting the risk dashboard) cannot run.\n")
        print("  Set ANTHROPIC_API_KEY in .env and restart the server, then re-run.")
        print("  Or pass --allow-keyless to run the rest of the scenario anyway and see")
        print("  how the agent reports an image it could not read.\n")
        return 2

    # -- 1 ------------------------------------------------------------------
    print("1-2. Create a project and upload the files")
    session = client.post("/api/session").json()["session_id"]
    client.post("/api/project", json={
        "session_id": session,
        "project_name": "Project Aurora",
        "reporting_date": "2026-07-01",
        "day_1_date": "2026-06-15",
    })

    files = [
        ("files", (name, (SAMPLES / name).read_bytes(), "application/octet-stream"))
        for name in UPLOADS
    ]
    saved = client.post(f"/api/upload?session_id={session}", files=files).json()["saved"]
    check(set(saved) == set(UPLOADS), f"uploaded {', '.join(UPLOADS)}")

    # -- 3-8 ----------------------------------------------------------------
    print("\n3-8. Analyse")
    analysis = client.post("/api/analyze", json={
        "session_id": session, "request_text": REQUEST,
    }).json()

    if analysis.get("needs_audience"):
        print(f"  {FAIL} the agent could not infer the audience")
        return 1

    check(analysis["audience"] == "Executive", "detected the Executive audience (§20.4)")

    stats = analysis["stats"]
    print(f"  {INFO} extracted: "
          + ", ".join(f"{v} {k}" for k, v in stats.items() if v))
    check(all(stats.get(k, 0) > 0 for k in ("tasks", "milestones", "risks")),
          "extracted tasks, milestones and risks (§20.5)")

    review = analysis["low_confidence_items"]
    image_risks = [i for i in review if i["type"] == "risk"]

    if check(bool(image_risks), "interpreted the risk-dashboard image (§20.6)"):
        for item in review:
            print(f"  {INFO} read from the image: {item['label'][:56]} "
                  f"({item['confidence']:.0%} confidence)")

        # The honest question, and the one the stored fixture cannot answer: did the
        # model actually read the heatmap, or did it hallucinate something plausible?
        check(any("GDPR" in i["label"] for i in image_risks),
              "found the critical risk that exists ONLY in the image (§20.8)")
        print(f"  {INFO} ^ compare these against data/samples/risk_dashboard.png by eye. "
              f"A confident\n      reading that is WRONG is worse than no reading at all.")
    else:
        for warning in analysis.get("warnings", []):
            if "image" in warning.casefold() or "interpret" in warning.casefold():
                print(f"  {INFO} {warning[:100]}")

    progress = next(
        (c for c in analysis["conflicts"] if "progress" in c["entity_key"].casefold()),
        None,
    )
    if not check(progress is not None, "detected the 82-vs-75 progress conflict (§20.8)"):
        return 1

    print(f"  {INFO} {progress['values']}")

    # -- 9 ------------------------------------------------------------------
    print("\n9. The system asks the user")
    check(progress["severity"] == "critical",
          "the progress conflict is CRITICAL (topic rule, not magnitude — §9)")
    check(progress["conflict_id"] in analysis["blocking_conflicts"],
          "it blocks generation")

    refused = client.post("/api/generate", json={"session_id": session})
    check(refused.status_code == 409,
          "generation is REFUSED while it is unresolved (§20.9)")

    # -- 10 -----------------------------------------------------------------
    print("\n10. The user selects 82%")
    resolved = client.post(
        f"/api/conflicts/{session}/resolve",
        json={"choices": {progress["conflict_id"]: "integration_tracker.xlsx"}},
    ).json()
    winner = next(c for c in resolved["conflicts"]
                  if c["conflict_id"] == progress["conflict_id"])
    check(winner["resolved_value"] == "82", "resolved to 82% (§20.10)")
    check(resolved["blocking_conflicts"] == [], "nothing is blocking any more")

    # -- 11-14 --------------------------------------------------------------
    print("\n11-14. Generate")
    generated = client.post("/api/generate", json={"session_id": session})
    if not check(generated.status_code == 200, "the deck was produced (§20.11)"):
        print(generated.text)
        return 1

    body = generated.json()
    outputs = body["outputs"]
    for line in body.get("summary", []):
        print(f"  {INFO} {line}")

    check(any(o.endswith(".pptx") for o in outputs), "an editable .pptx (§20.11)")
    check(any("data_quality_report" in o for o in outputs),
          "a data-quality report (§20.14)")
    check(any("conflict_report" in o for o in outputs), "a conflict report")

    # -- 15 -----------------------------------------------------------------
    print("\n15. Download")
    EXAMPLES.mkdir(exist_ok=True)
    for name in outputs:
        response = client.get(f"/api/download/{session}/{name}")
        if response.status_code != 200:
            check(False, f"download {name}")
            continue
        (EXAMPLES / name).write_bytes(response.content)
        print(f"  {PASS} {name}  ->  example_outputs/{name}")

    # Charts, for §18 deliverable 17.
    charts = client.post("/api/report", json={
        "session_id": session,
        "request_text": "Create a risk heatmap for the integration.",
        "audience": "Executive",
    }).json()
    for name in charts.get("outputs", []):
        if name.endswith(".png"):
            response = client.get(f"/api/download/{session}/{name}")
            if response.status_code == 200:
                (EXAMPLES / name).write_bytes(response.content)
                print(f"  {PASS} {name}  ->  example_outputs/{name}")

    # -- verdict ------------------------------------------------------------
    print()
    if _failures:
        print(f"{FAIL} {len(_failures)} step(s) FAILED:")
        for failure in _failures:
            print(f"    - {failure}")
        return 1

    print(f"{PASS} The §20 acceptance scenario passes end to end.")
    print(f"  Artefacts in {EXAMPLES.relative_to(ROOT)}/")
    print("\n  Now read them. In particular, check the data-quality report against what")
    print("  the deck actually claims — that comparison is the real test.")
    return 0


def _vision_available(client: httpx.Client) -> bool:
    """Probe the server: does a run report that it could not read an image?"""
    session = client.post("/api/session").json()["session_id"]
    name = "risk_dashboard.png"
    client.post(
        f"/api/upload?session_id={session}",
        files=[("files", (name, (SAMPLES / name).read_bytes(), "image/png"))],
    )
    analysis = client.post("/api/analyze", json={
        "session_id": session, "request_text": REQUEST,
    }).json()

    warnings = " ".join(analysis.get("warnings", []))
    return "Could NOT interpret" not in warnings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000",
                        help="the running server")
    parser.add_argument("--allow-keyless", action="store_true",
                        help="run without a vision model; steps 6 and 8 will not pass")
    args = parser.parse_args()

    try:
        sys.exit(main(args.base, allow_keyless=args.allow_keyless))
    except httpx.ConnectError:
        print(f"Could not reach {args.base}. Start the server first:\n"
              f"  docker compose up\n"
              f"  # or: uvicorn app.main:app", file=sys.stderr)
        sys.exit(1)
