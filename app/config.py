"""Central configuration (spec §15, §21.9, §21.10).

Every model ID, threshold and policy knob lives here and nowhere else. The spec
is explicit: "Do not hard-code API keys" (§21.9) and "Do not hard-code model IDs"
(§21.10). `tests/test_config.py` enforces the second one with a grep.

Values are read from the environment / a local `.env` file. Nothing here requires
an API key: with no key configured the agent runs the deterministic fallback path
end to end (see `app/llm/fallbacks.py`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]

Provider = Literal["anthropic", "openai", "none"]
ConflictMode = Literal["A", "B", "C"]
Effort = Literal["low", "medium", "high"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- LLM
    #: Which backend to use. "none" forces the deterministic fallback path.
    llm_provider: Provider = "anthropic"

    anthropic_api_key: Optional[SecretStr] = None
    openai_api_key: Optional[SecretStr] = None

    #: Reasoning, summaries, report planning.
    llm_model: str = "claude-opus-4-8"
    #: Image interpretation (§5.6). Must be a vision-capable model.
    vision_model: str = "claude-opus-4-8"
    #: Cheap, high-volume classification (request parsing, table typing).
    fast_model: str = "claude-haiku-4-5"

    llm_max_tokens: int = 4096
    llm_effort: Effort = "medium"
    #: Adaptive thinking. Off by default — the semantic tasks here are small.
    llm_thinking: bool = False
    llm_timeout_s: float = 90.0
    llm_max_retries: int = 2

    # --------------------------------------------------- conflicts (§9)
    #: A = ask always, B = source priority always, C = hybrid (spec's recommended default).
    conflict_mode: ConflictMode = "C"

    #: Lower number = higher trust (§9). Images rank lowest: OCR/vision output is
    #: less reliable than a system-of-record tracker. User-overridable per project.
    source_priority: dict[str, int] = Field(
        default_factory=lambda: {
            "excel": 1,
            "csv": 1,
            "word": 2,
            "pdf": 2,
            "powerpoint": 3,
            "html": 4,
            "image": 5,
        }
    )

    # -------------------------------------------------- data quality (§5.6)
    #: Findings below this confidence are surfaced to the user for review.
    low_confidence_threshold: float = 0.6
    #: Claude downsamples above ~1568px on the long edge; larger just costs tokens.
    image_max_edge_px: int = 1568
    upload_max_mb: int = 25

    # ------------------------------------------------------------ paths
    storage_dir: Path = REPO_ROOT / "storage_data"
    output_dir: Path = REPO_ROOT / "output"
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"

    # ----------------------------------------------------------- helpers
    def api_key_for(self, provider: Provider) -> Optional[str]:
        key = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
        }.get(provider)
        return key.get_secret_value() if key else None

    def llm_configured(self) -> bool:
        """True when the selected provider has a usable key."""
        if self.llm_provider == "none":
            return False
        return bool(self.api_key_for(self.llm_provider))


class ModelChoice(BaseModel):
    """One model a user may pick, and what picking it means for this app."""

    id: str
    label: str
    provider: Provider
    #: Drives the chat's token budget (`app/agent/budget.py`), so it has to be
    #: right per model rather than a single global guess.
    context_window: int
    #: §5.6 reads risk heatmaps and whiteboard photos. A model that cannot see
    #: them does not fail — the extractor reports that it could not read the
    #: image — but the user should know that before choosing.
    vision: bool = True
    note: str = ""


#: The **only** place model IDs may appear (§21.10, enforced by a grep test over
#: `app/**/*.py`). The picker fetches this over HTTP rather than hard-coding a
#: list in JSX, so adding a model is a one-line change here and nowhere else.
MODEL_CATALOGUE: list[ModelChoice] = [
    ModelChoice(
        id="claude-opus-4-8", label="Claude Opus 4.8", provider="anthropic",
        context_window=1_000_000, vision=True,
        note="Most capable. Best on long, messy file sets.",
    ),
    ModelChoice(
        id="claude-sonnet-5", label="Claude Sonnet 5", provider="anthropic",
        context_window=1_000_000, vision=True,
        note="Faster and cheaper; strong on most weekly reporting.",
    ),
    ModelChoice(
        id="claude-haiku-4-5", label="Claude Haiku 4.5", provider="anthropic",
        context_window=200_000, vision=True,
        note="Cheapest. Good for classification, weaker on judgement.",
    ),
    ModelChoice(
        id="gpt-4o", label="GPT-4o", provider="openai",
        context_window=128_000, vision=True,
        note="Cannot read scanned PDFs natively — those fall back to text.",
    ),
    ModelChoice(
        id="gpt-4o-mini", label="GPT-4o mini", provider="openai",
        context_window=128_000, vision=True,
        note="Cheapest OpenAI option; weaker on conflicting sources.",
    ),
]


def model_choice(model_id: Optional[str]) -> Optional[ModelChoice]:
    return next((m for m in MODEL_CATALOGUE if m.id == model_id), None)


settings = Settings()


def get_settings() -> Settings:
    """Indirection so tests can monkeypatch settings without reimporting callers."""
    return settings
