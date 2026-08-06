"""Load the Dell-EMC v1.0 corpus into the app as two interactive chat projects, for
exploring the agent's behaviour by hand in the UI. Optional and low priority — not used by
the scored evaluation, which drives the session API directly (`scripts/eval/run_corpus.py`).
This is purely a "poke around in the actual app" convenience.

Creates two projects via the project/chat API (POST /api/projects,
POST /api/projects/{id}/files) — the same endpoints the frontend's "New project" +
drag-and-drop upload use:

    "PMI Case (Demo) - Clean"        <- data/corpus/dellemc_vcio/v1.0/clean/
    "PMI Case (Demo) - With Errors"  <- data/corpus/dellemc_vcio/v1.0/with_errors/

Ground truth (ground_truth.json, error_key.json, 00_ERROR_KEY.xlsx) is never uploaded —
only the 21 case documents per corpus — so opening the project's chat and asking it
questions is a fair test, not an open-book one.

    .venv/bin/uvicorn app.main:app --reload          # terminal 1
    .venv/bin/python scripts/load_synthetic_corpus.py  # terminal 2
"""
from __future__ import annotations

import argparse
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS_V1_0 = ROOT / "data" / "corpus" / "dellemc_vcio" / "v1.0"

PROJECTS = (
    ("PMI Case (Demo) - Clean", "clean", "📁"),
    ("PMI Case (Demo) - With Errors", "with_errors", "⚠️"),
)


def _corpus_files(folder: str) -> list[Path]:
    return sorted(
        p for p in (CORPUS_V1_0 / folder).iterdir()
        if p.is_file() and p.name != "README.md"
    )


def _existing_project_id(client: httpx.Client, name: str) -> str | None:
    for project in client.get("/api/projects").json()["projects"]:
        if project["name"] == name:
            return project["project_id"]
    return None


def load_one(client: httpx.Client, name: str, folder: str, icon: str, force: bool) -> None:
    existing = _existing_project_id(client, name)
    if existing is not None:
        if not force:
            print(f"'{name}' already exists (project_id={existing}); pass --force to "
                  f"recreate it. Skipping.")
            return
        client.delete(f"/api/projects/{existing}")
        print(f"deleted existing '{name}' ({existing}) — note: this unfiles its chats, "
              f"it does not purge its on-disk knowledge/sources (harmless orphaned dir).")

    project = client.post("/api/projects", json={"name": name, "icon": icon}).json()["project"]
    project_id = project["project_id"]

    files = _corpus_files(folder)
    payload = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in files]
    result = client.post(f"/api/projects/{project_id}/files", files=payload).json()

    knowledge = client.get(f"/api/projects/{project_id}/knowledge").json()
    print(f"'{name}' (project_id={project_id}): "
          f"{len(result['ingested'])}/{len(files)} files ingested, "
          f"{len(result['rejected'])} rejected, "
          f"knowledge entity_count={knowledge.get('entity_count')}")
    if result["rejected"]:
        print(f"  rejected: {result['rejected']}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--force", action="store_true",
                   help="Delete and recreate the demo projects if they already exist.")
    args = p.parse_args()

    client = httpx.Client(base_url=args.base, timeout=300.0)
    for name, folder, icon in PROJECTS:
        load_one(client, name, folder, icon, args.force)

    print("\nOpen the app and look for these two projects in the sidebar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
