"""Capture a real vision reading into tests/fixtures/vision/ (spec §5.6).

The test suite replays a stored `ImageExtraction` so the image pipeline — and the
§20 acceptance scenario — runs in CI with no key and no cost. That proves the
plumbing. It does not prove the model can actually read a risk heatmap.

This script closes that gap: it calls the real model and writes down what it said.
Run it whenever the sample images or the prompt change, and commit the result.

    ANTHROPIC_API_KEY=... python scripts/record_vision_fixture.py

Read the diff before committing. If the model missed the GDPR risk or scored it at
0.95 confidence, that is a finding about the prompt, not a test to be patched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.llm import ImagePart, get_client, llm_available  # noqa: E402
from app.llm.prompts import load as load_prompt  # noqa: E402
from app.llm.schemas import ImageExtraction  # noqa: E402
from app.utils.images import prepare  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "vision"
SAMPLES = ROOT / "data" / "samples"

TARGETS = {
    "risk_dashboard": SAMPLES / "risk_dashboard.png",
    "milestone_whiteboard": SAMPLES / "milestone_whiteboard.jpg",
    "workstream_dashboard": SAMPLES / "workstream_dashboard.jpeg",
}


def record(name: str, image_path: Path) -> None:
    prepared = prepare(image_path)
    result: ImageExtraction = get_client().structured(
        system=load_prompt("interpret_pmi_image"),
        user=(
            "Read this image and extract every Post-Merger Integration fact you can "
            "actually see. Leave out anything you cannot read."
        ),
        output_model=ImageExtraction,
        model=get_settings().vision_model,
        images=[ImagePart(b64=prepared.b64, media_type=prepared.media_type)],
    )

    FIXTURES.mkdir(parents=True, exist_ok=True)
    out = FIXTURES / f"{name}.json"
    out.write_text(json.dumps(result.model_dump(mode="json"), indent=2) + "\n")

    print(f"\n{image_path.name} -> {out.relative_to(ROOT)}")
    print(f"  content types : {', '.join(result.content_types) or '(none)'}")
    print(f"  legibility    : {result.legibility}"
          f"{' handwritten' if result.is_handwritten else ''}"
          f"{' cropped' if result.is_cropped else ''}")
    print(f"  items         : {len(result.items)}")
    for item in result.items:
        print(f"    [{item.type:9}] {item.title[:56]:56} "
              f"model_confidence={item.model_confidence:.2f}")
    for note in result.notes:
        print(f"  note: {note}")


def main() -> int:
    if not llm_available():
        print("No LLM provider configured. Set ANTHROPIC_API_KEY (see .env.example).",
              file=sys.stderr)
        return 1
    if not get_client().supports_vision:
        print(f"Provider {get_client().name!r} is not vision-capable.", file=sys.stderr)
        return 1

    missing = [p for p in TARGETS.values() if not p.exists()]
    if missing:
        print("Missing sample images. Run: python scripts/make_sample_images.py",
              file=sys.stderr)
        return 1

    for name, path in TARGETS.items():
        record(name, path)

    print("\nDone. Review the diff before committing — a missed risk or an inflated "
          "confidence score is a prompt bug, not a test to update.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
