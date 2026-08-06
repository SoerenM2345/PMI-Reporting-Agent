"""Keyless smoke tests for the frozen Dell-EMC v1.0 evaluation corpus.

Marked `corpus` (see pyproject.toml); deselected by default with `-m "not corpus"` so the
main suite's count is unaffected — this corpus is a research fixture, not a regression
target for every commit. Everything in this file runs with no API key and no live server:
manifest integrity, ground-truth self-consistency, and the app's own deterministic
extractors are enough to catch corpus drift long before a paid run would.

The full metric-suite run (`scripts/eval/run_corpus.py` against a live server, scored by
`scripts/eval/score.py`) is deliberately not exercised here — that is Phase 3-4 of
PROTOCOL.md, gated behind an explicit, costed decision to run it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V1_0 = ROOT / "data" / "corpus" / "dellemc_vcio" / "v1.0"

sys.path.insert(0, str(V1_0 / "generators"))
import corpus_integrity  # noqa: E402

pytestmark = pytest.mark.corpus

_CORRUPTED_FILE = "DellEMC_VCIO_Merger_Agreement_Key_Terms_2015-10-12.pdf"


def test_manifest_matches_disk():
    """The corpus's whole value depends on it not silently changing underneath a study
    (corpus_integration_plan.md Step 3) — if someone opens a workbook in Excel and saves
    it, this is what notices."""
    problems = corpus_integrity.verify_manifest()
    assert not problems, "\n".join(problems)


def test_with_errors_differs_from_clean_in_exactly_the_right_files():
    problems = corpus_integrity.verify_error_diff_count()
    assert not problems, "\n".join(problems)


def test_ground_truth_self_consistent():
    gt = json.loads((V1_0 / "ground_truth.json").read_text())
    clean_files = {p.name for p in (V1_0 / "clean").glob("*") if p.is_file()}

    assert len(gt["conflicts"]) == 6
    for conflict in gt["conflicts"]:
        for claim in conflict["claims"]:
            assert claim["file"] in clean_files, (
                f"{conflict['id']} cites a file not present in clean/: {claim['file']}")

    assert gt["conditions"]["clean"]["count"] == 6
    assert gt["conditions"]["with_errors"]["count"] == 16, (
        "with_errors is a copy of clean, so both the 6 designed conflicts and the 10 "
        "injected errors are findable — 16, not 10 (corpus_integration_plan.md Part 2)")


def test_error_key_self_consistent():
    ek = json.loads((V1_0 / "error_key.json").read_text())
    with_errors_files = {p.name for p in (V1_0 / "with_errors").glob("*") if p.is_file()}

    assert len(ek["errors"]) == 10
    for error in ek["errors"]:
        assert error["file"] in with_errors_files, (
            f"{error['id']} cites a file not present in with_errors/: {error['file']}")
    assert any(e["id"] == "E-01" and e["expected_behaviour"] == "report_unreadable"
               for e in ek["errors"])


@pytest.mark.parametrize("condition", ["clean", "with_errors"])
def test_every_file_parses_with_the_apps_own_extractors(condition):
    """No API key needed: extraction is deterministic Python for every format here, and
    the three images degrade gracefully with no vision model configured (they do not
    raise) — see app/extractors/image.py's keyless fallback path. The one file that is
    SUPPOSED to fail (E-01's truncated PDF) is asserted on its own, below."""
    from app.extractors import extract_file

    folder = V1_0 / condition
    supported = {".docx", ".pptx", ".xlsx", ".pdf", ".html", ".png", ".jpg", ".jpeg"}
    failures = {}
    for path in sorted(folder.glob("*")):
        if not path.is_file() or path.suffix.lower() not in supported:
            continue
        if condition == "with_errors" and path.name == _CORRUPTED_FILE:
            continue
        try:
            extract_file(path)
        except Exception as exc:  # noqa: BLE001 - collecting every failure, not just the first
            failures[path.name] = str(exc)
    assert not failures, failures


def test_e01_reported_as_unreadable_not_silently_skipped():
    """E-01 truncates the file to 5,112 bytes with no EOF marker. Empirically (verified
    by hand before writing this assertion — do not assume, PyMuPDF is more lenient than
    a naive reader): it does NOT raise. Page 1 survives intact; the truncation lands on
    page 2, which comes back with too little text to be real content, is treated as a
    possible scanned page, and — with no vision model reachable — comes back as an
    explicit `is_warning` record saying it could not be interpreted, not as a blank page.
    That per-page honesty is the property under test, not a whole-file exception.

    MASTER.md's own distinction — "there was nothing in it" vs. "I could not open it" —
    and only the second is honest (§21.17); this is where that distinction actually shows
    up in the record stream for E-01, so assert it there rather than assuming a raise
    that does not happen."""
    from app.extractors import extract_file

    path = V1_0 / "with_errors" / _CORRUPTED_FILE
    records = extract_file(path)
    warnings = [r for r in records if r.get("is_warning")]
    assert warnings, (
        "expected at least one is_warning record flagging unreadable/uninterpretable "
        f"content for the truncated page; got {records}")
    assert any("could not" in w.get("text", "").lower() for w in warnings), warnings
