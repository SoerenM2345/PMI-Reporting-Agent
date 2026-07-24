"""P0: configuration and the swappable LLM provider layer (spec §15, §11, §21.9-21.10)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app import llm
from app.config import Settings
from app.llm import tasks
from app.llm.base import LLMError, NotConfigured
from app.llm.null_client import NullClient
from app.llm.schemas import RequestParse, SummaryBullets
from app.models.pmi import Audience, PMIDataModel

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_client():
    """Every test starts with a fresh client and an empty warning buffer."""
    llm.reset_client()
    tasks.drain_warnings()
    yield
    llm.reset_client()
    tasks.drain_warnings()


# --------------------------------------------------------------- §21.10
def test_no_hard_coded_model_ids_outside_config():
    """Spec §21.10: 'Do not hard-code model IDs.'

    config.py is the only module allowed to name a model. Prompts and docs may
    mention them in prose; Python source may not.
    """
    model_id = re.compile(r"claude-[a-z0-9.\-]*\d|gpt-[0-9]")
    offenders: list[str] = []

    for path in (ROOT / "app").rglob("*.py"):
        if path.name == "config.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if model_id.search(line):
                rel = path.relative_to(ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offenders, "model IDs must live only in app/config.py:\n" + "\n".join(offenders)


# --------------------------------------------------------------- settings
def test_settings_defaults_to_anthropic_and_hybrid_conflicts():
    s = Settings(_env_file=None)
    assert s.llm_provider == "anthropic"
    assert s.conflict_mode == "C"  # §9 recommended default
    assert s.llm_model and s.vision_model  # both configured, both overridable


def test_images_rank_lowest_in_source_priority():
    """§9: images are least trusted — OCR/vision output is less reliable than a tracker."""
    p = Settings(_env_file=None).source_priority
    assert p["excel"] < p["word"] < p["powerpoint"] < p["html"] < p["image"]
    assert p["image"] == max(p.values())


def test_llm_configured_is_false_without_a_key():
    assert Settings(_env_file=None, anthropic_api_key=None).llm_configured() is False
    assert Settings(_env_file=None, anthropic_api_key="sk-test").llm_configured() is True
    # "none" ignores any key that happens to be present
    assert Settings(
        _env_file=None, llm_provider="none", anthropic_api_key="sk-test"
    ).llm_configured() is False


# ------------------------------------------------------- provider selection
def test_no_key_yields_null_client(monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", None)
    assert llm.get_client().name == "none"
    assert llm.llm_available() is False


def test_null_client_raises_rather_than_faking_an_answer():
    """A silent empty answer would be indistinguishable from 'the model found nothing'."""
    with pytest.raises(NotConfigured):
        NullClient().structured(
            system="s", user="u", output_model=RequestParse
        )


# ----------------------------------------------------------- task fallback
def test_parse_request_falls_back_and_records_a_warning(monkeypatch):
    """The bug this replaces: `except Exception: pass` made a broken key look like a
    working one. A fallback must now leave a trace the user can see."""
    monkeypatch.setattr("app.config.settings.anthropic_api_key", None)

    parsed = tasks.parse_request("Create a SteerCo PowerPoint")

    assert parsed.output_type == "powerpoint"
    assert parsed.audience == Audience.EXECUTIVE
    warnings = tasks.drain_warnings()
    assert len(warnings) == 1
    assert "deterministic fallback" in warnings[0]


def test_task_uses_the_model_when_one_is_configured():
    class FakeClient:
        name = "fake"
        supports_vision = True

        def structured(self, *, output_model, **kw):
            return output_model(output_type="excel", audience=Audience.FINANCE,
                                topic="synergies")

    llm.set_client(FakeClient())
    parsed = tasks.parse_request("anything at all")

    assert parsed.output_type == "excel"
    assert parsed.audience == Audience.FINANCE
    assert tasks.drain_warnings() == []  # no fallback => no warning


def test_provider_failure_degrades_instead_of_crashing():
    class BrokenClient:
        name = "broken"
        supports_vision = False

        def structured(self, **kw):
            raise LLMError("502 upstream exploded")

    llm.set_client(BrokenClient())
    parsed = tasks.parse_request("Create a risk chart")

    assert parsed.output_type == "chart"  # heuristic still answered
    assert "502 upstream exploded" in tasks.drain_warnings()[0]


# --------------------------------------------------------- prompt payloads
def test_large_model_is_trimmed_to_valid_json_not_sliced_mid_token():
    """The bug this replaces: `model_dump_json()[:12000]` handed the model corrupt
    JSON. Truncated-but-parseable beats complete-but-broken."""
    import json

    from app.models.pmi import SourceFormat, SourceReference, Task

    ref = SourceReference(file_name="big.xlsx", file_type=SourceFormat.EXCEL)
    model = PMIDataModel(
        tasks=[
            Task(task_id=f"T{i:03d}", title="x" * 200, source_references=[ref])
            for i in range(400)
        ]
    )

    payload = tasks._serialize_for_llm(model, budget_chars=5_000)

    json_part = payload[payload.index("{"):]
    json.loads(json_part)  # must parse — this is the whole point
    assert len(payload) < 20_000
    assert "truncated for size" in payload
    assert "exceeded the prompt budget" in tasks.drain_warnings()[0]


def test_small_model_is_passed_through_untouched():
    import json

    from app.models.pmi import PMIProject

    model = PMIDataModel(project=PMIProject(project_id="p1", project_name="Prj"))
    payload = tasks._serialize_for_llm(model)

    assert json.loads(payload)["project"]["project_name"] == "Prj"
    assert tasks.drain_warnings() == []
