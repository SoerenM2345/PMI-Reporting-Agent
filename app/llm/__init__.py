"""LLM provider layer.

Lives outside `app/agent/` deliberately: the image extractor (§5.6) needs the
vision client, and an extractor importing from `app.agent` would invert the
dependency direction and risk an import cycle.

The client is resolved once and cached. `reset_client()` exists for tests, which
swap providers (and inject a fake vision client) between cases.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from app.config import ModelRoles, get_settings
from app.llm.base import (
    DocumentPart,
    ImagePart,
    LLMClient,
    LLMError,
    NotConfigured,
)

log = logging.getLogger("pmi.llm")

#: An explicit override wins over everything — this is how tests inject a fake.
_override: LLMClient | None = None
#: Otherwise one client per provider. Keyed rather than singular because a chat
#: may choose its own provider, and a single global would mean the last chat to
#: be opened silently decided which backend every other chat used.
_clients: dict[str, LLMClient] = {}

#: The provider + three model roles for the run in flight, set once per chat turn
#: by `use_selection`. A `ContextVar` rather than a module global on purpose: a
#: global is exactly the cross-session bleed CLAUDE.md warns about for the §9
#: override — one chat's choice of backend would govern every concurrent request
#: until the next one overwrote it. A context var is isolated per request/thread,
#: so `get_client()` and the `*_model()` helpers below see only *this* turn's pick
#: and fall back to `get_settings()` when nothing set it (the wizard API, tests).
_selection: ContextVar[Optional[ModelRoles]] = ContextVar("llm_selection", default=None)


@contextmanager
def use_selection(selection: Optional[ModelRoles]) -> Iterator[None]:
    """Scope every LLM call in the block to `selection`'s provider and models.

    Wrapping a whole chat turn is enough: classification, extraction, summaries
    and generation all resolve their client and model through the helpers here,
    so the one context var reaches the whole pipeline without threading a
    provider argument through every node and extractor signature."""
    token = _selection.set(selection)
    try:
        yield
    finally:
        _selection.reset(token)


def current_selection() -> Optional[ModelRoles]:
    return _selection.get()


def reasoning_model() -> str:
    """Model for summaries / planning (§11), honouring the active selection."""
    sel = _selection.get()
    return sel.reasoning if sel else get_settings().llm_model


def vision_model() -> str:
    """Model for §5.6 image / scanned-PDF interpretation."""
    sel = _selection.get()
    return sel.vision if sel else get_settings().vision_model


def fast_model() -> str:
    """Model for cheap per-table / per-request classification."""
    sel = _selection.get()
    return sel.fast if sel else get_settings().fast_model


def get_client(provider: str | None = None) -> LLMClient:
    if _override is not None:
        return _override

    if provider is None:
        sel = _selection.get()
        provider = sel.provider if sel else get_settings().llm_provider
    if provider not in _clients:
        _clients[provider] = _build_client(provider)
    return _clients[provider]


def set_client(client: LLMClient | None) -> None:
    """Inject a client (tests) or force a rebuild on the next call (`None`)."""
    global _override
    _override = client
    if client is None:
        _clients.clear()


def reset_client() -> None:
    set_client(None)


def llm_available(provider: str | None = None) -> bool:
    """True when a real provider is wired up (i.e. not the NullClient)."""
    return get_client(provider).name != "none"


def _build_client(provider: str) -> LLMClient:
    from app.llm.null_client import NullClient

    settings = get_settings()

    if provider == "none":
        return NullClient("LLM_PROVIDER=none")

    key = settings.api_key_for(provider)
    if not key:
        env_var = f"{provider.upper()}_API_KEY"
        log.info("%s is not set — running in deterministic fallback mode", env_var)
        return NullClient(f"{env_var} is not set")

    try:
        if provider == "anthropic":
            from app.llm.anthropic_client import AnthropicClient

            return AnthropicClient(key)
        if provider == "openai":
            from app.llm.openai_client import OpenAIClient

            return OpenAIClient(key)
    except NotConfigured as exc:
        log.warning("could not initialise %s: %s", provider, exc)
        return NullClient(str(exc))

    return NullClient(f"unknown provider {provider!r}")


__all__ = [
    "DocumentPart",
    "ImagePart",
    "LLMClient",
    "LLMError",
    "NotConfigured",
    "current_selection",
    "fast_model",
    "get_client",
    "llm_available",
    "reasoning_model",
    "reset_client",
    "set_client",
    "use_selection",
    "vision_model",
]
