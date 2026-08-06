"""(Re)freeze MANIFEST.sha256 for the v1.0 corpus.

Only run this when deliberately updating a frozen corpus version (and bump the version
string in ground_truth.json / error_key.json / DATASHEET.md to match — a manifest rebuild
is what unlocks the freeze, so it should never happen silently). Verification is
`corpus_integrity.py`, run standalone or via `tests/test_corpus_dellemc.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus_integrity import MANIFESTED_ROOTS, write_manifest  # noqa: E402

if __name__ == "__main__":
    write_manifest()
    print(f"MANIFEST.sha256 written, covering {', '.join(MANIFESTED_ROOTS)}/ "
          "and the ground-truth/error-key files.")
