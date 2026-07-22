"""Shared fixtures.

The important one is `fake_vision`: it lets the whole image pipeline — and therefore
the §20 acceptance scenario — run in CI with no API key and no cost, against a
recorded reading of a real risk-dashboard screenshot.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
FIXTURES = Path(__file__).parent / "fixtures"

sys.path.insert(0, str(ROOT))

from app import llm  # noqa: E402
from app.llm import tasks  # noqa: E402
from app.llm.base import NotConfigured  # noqa: E402
from app.llm.schemas import ImageExtraction  # noqa: E402


#: The §19 sample project. Every file, so the test suite exercises every extractor.
_GENERATORS = ("make_sample_data.py", "make_sample_extras.py", "make_sample_images.py")
_EXPECTED = (
    "integration_tracker.xlsx", "synergy_tracker.xlsx", "milestone_tracker.csv",
    "weekly_update.pptx", "steerco_meeting_notes.docx", "workstream_status_it.docx",
    "steerco_pack.pdf", "portal_dashboard_export.html",
    "risk_dashboard.png", "milestone_whiteboard.jpg", "workstream_dashboard.jpeg",
)


@pytest.fixture(scope="session", autouse=True)
def sample_files():
    if not all((SAMPLES / name).exists() for name in _EXPECTED):
        for script in _GENERATORS:
            subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True)
    return SAMPLES


@pytest.fixture(autouse=True)
def _no_live_provider(monkeypatch):
    """The suite must never reach a real provider.

    `Settings` reads `.env`, so a developer whose `.env` points at a working key
    had the tests quietly making **real, paid API calls** — the run went from 6s
    to 58s, three tests failed (`test_no_key_yields_null_client` asserts the
    *absence* of a client), and results depended on someone's local file.

    Individual tests still opt in to a fake with the `fake_vision` fixture, or
    to a provider by monkeypatching `llm_provider` themselves; this only removes
    the ambient one. Tests that genuinely need a live model do not belong here.
    """
    # The shared singleton most code reads.
    monkeypatch.setattr("app.config.settings.llm_provider", "none")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", None)
    monkeypatch.setattr("app.config.settings.openai_api_key", None)

    # ...and the ambient environment, because a few tests construct their own
    # `Settings()` to exercise the class. Without this the suite passes or fails
    # depending on what happens to be exported in the developer's shell, which
    # is the same class of problem as reading `.env` — just harder to notice.
    for name in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                 "LLM_MODEL", "VISION_MODEL", "FAST_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _clean_llm_state():
    """No test inherits another's client or warning buffer."""
    llm.reset_client()
    tasks.drain_warnings()
    yield
    llm.reset_client()
    tasks.drain_warnings()


class FakeVisionClient:
    """Replays a stored `ImageExtraction` instead of calling a model.

    The fixture is currently **hand-authored** to match the schema and the §20
    scenario — it has not yet been captured from a live model. Re-record it against
    a real Claude vision call with:

        ANTHROPIC_API_KEY=... python scripts/record_vision_fixture.py

    That matters: a hand-written fixture proves the *plumbing* (confidence scoring,
    region mapping, conflict detection, the deck picking up an image-sourced risk),
    but it cannot prove the model actually reads a heatmap correctly. Only the live
    run and `pytest -m live` do that.
    """

    name = "fake-vision"
    supports_vision = True

    def __init__(self, fixture: str = "risk_dashboard"):
        payload = json.loads((FIXTURES / "vision" / f"{fixture}.json").read_text())
        self.extraction = ImageExtraction.model_validate(payload)
        self.calls = 0

    def structured(self, *, output_model, **kwargs):
        if output_model is ImageExtraction:
            self.calls += 1
            return self.extraction

        # Every other task (request parsing, summary prose) declines, so `tasks.py`
        # answers it from the deterministic fallbacks. That is deliberate: this fixture
        # exists to test the *image* pipeline, and letting it also fake the summary
        # would hide whether the rest of the system works without a model.
        raise NotConfigured(
            f"FakeVisionClient only records ImageExtraction, not {output_model.__name__}"
        )


@pytest.fixture
def fake_vision():
    client = FakeVisionClient()
    llm.set_client(client)
    return client
