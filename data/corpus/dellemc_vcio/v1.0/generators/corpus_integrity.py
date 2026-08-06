"""Shared integrity logic for the frozen v1.0 corpus.

Two properties matter and both silently break if someone opens a workbook in Excel and
saves it, or fixes a typo directly in a generated file instead of regenerating it:

1. Every manifested file still hashes to what MANIFEST.sha256 recorded when the corpus
   was frozen.
2. `with_errors/` still differs from `clean/` in exactly the files error_key.json says it
   does, and is byte-identical everywhere else.

Used by `build_manifest.py` (CLI, to (re)freeze a version) and by
`tests/test_corpus_dellemc.py` (keyless smoke tier, to catch drift automatically).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

V1_0 = Path(__file__).resolve().parents[1]
MANIFEST_PATH = V1_0 / "MANIFEST.sha256"

#: relative to V1_0. Documentation prose (README_CORPUS.md, BACKLOG.md, DATASHEET.md) is
#: deliberately excluded — those may get typo fixes without bumping the corpus version.
MANIFESTED_ROOTS = ("clean", "with_errors", "generators")
MANIFESTED_FILES = ("ground_truth.json", "error_key.json", "00_ERROR_KEY.xlsx")


def _iter_manifested_paths():
    for root in MANIFESTED_ROOTS:
        for path in sorted((V1_0 / root).rglob("*")):
            # README.md inside with_errors/ is prose about the corpus, not corpus data —
            # excluded for the same reason README_CORPUS.md/BACKLOG.md/DATASHEET.md are:
            # it may get a typo fix without forcing a version bump.
            if path.is_file() and path.name != "README.md":
                yield path.relative_to(V1_0)
    for name in MANIFESTED_FILES:
        yield Path(name)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def compute_manifest() -> dict[str, str]:
    return {str(rel): sha256_of(V1_0 / rel) for rel in _iter_manifested_paths()}


def write_manifest() -> None:
    manifest = compute_manifest()
    lines = [f"{digest}  {rel}" for rel, digest in sorted(manifest.items())]
    MANIFEST_PATH.write_text("\n".join(lines) + "\n")


def load_manifest() -> dict[str, str]:
    manifest: dict[str, str] = {}
    for line in MANIFEST_PATH.read_text().splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        manifest[rel] = digest
    return manifest


def verify_manifest() -> list[str]:
    """Returns a list of problems; empty means the corpus matches MANIFEST.sha256 exactly."""
    if not MANIFEST_PATH.exists():
        return [f"{MANIFEST_PATH} does not exist — run build_manifest.py"]
    recorded = load_manifest()
    current = compute_manifest()
    problems = []
    for rel, digest in recorded.items():
        if rel not in current:
            problems.append(f"missing (was manifested, no longer on disk): {rel}")
        elif current[rel] != digest:
            problems.append(f"modified since freeze: {rel}")
    for rel in current:
        if rel not in recorded:
            problems.append(f"new file not in manifest: {rel}")
    return problems


def verify_error_diff_count() -> list[str]:
    """The whole value of the flawed corpus rests on differing from clean/ in exactly the
    files error_key.json names, and nowhere else. Confirms that empirically, by hash, not
    by trusting the key's own bookkeeping."""
    error_key = json.loads((V1_0 / "error_key.json").read_text())
    expected_changed_files = {e["file"] for e in error_key["errors"]}

    clean_files = {p.name: sha256_of(p) for p in (V1_0 / "clean").glob("*") if p.is_file()}
    error_files = {p.name: sha256_of(p) for p in (V1_0 / "with_errors").glob("*")
                   if p.is_file() and p.name != "README.md"}

    problems = []

    # names present in with_errors/ but not clean/ (renames) must have byte-identical
    # content to some file in clean/ (E-02: filename changed, content untouched).
    only_in_errors = set(error_files) - set(clean_files)
    only_in_clean = set(clean_files) - set(error_files)
    renamed_ok = 0
    for name in only_in_errors:
        if error_files[name] in clean_files.values():
            renamed_ok += 1
        else:
            problems.append(f"renamed in with_errors/ but content not found in clean/: {name}")
    if len(only_in_errors) != len(only_in_clean):
        problems.append(
            f"rename mismatch: {len(only_in_clean)} names only in clean/, "
            f"{len(only_in_errors)} only in with_errors/ (should be equal, one rename)")

    shared_names = set(clean_files) & set(error_files)
    actually_changed = {n for n in shared_names if clean_files[n] != error_files[n]}
    actually_unchanged_but_listed = expected_changed_files & shared_names - actually_changed

    if actually_changed != (expected_changed_files & shared_names):
        problems.append(
            f"content changed in files error_key.json does not list, or vice versa: "
            f"changed-but-unlisted={actually_changed - expected_changed_files}, "
            f"listed-but-unchanged={actually_unchanged_but_listed}")

    total_touched = len(actually_changed) + len(only_in_errors)
    if total_touched != len(expected_changed_files):
        problems.append(
            f"expected {len(expected_changed_files)} files touched (by content or rename), "
            f"found {total_touched}")

    return problems


if __name__ == "__main__":
    import sys

    problems = verify_manifest() + verify_error_diff_count()
    if problems:
        print("CORPUS INTEGRITY: FAIL")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("CORPUS INTEGRITY: PASS")
