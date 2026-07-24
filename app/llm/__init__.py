"""LLM provider layer.

Lives outside `app/agent/` deliberately: the image extractor (§5.6) needs the
vision client, and an extractor importing from `app.agent` would invert the
dependency direction and risk an import cycle.

The client is resolved once and cached. `reset_client()` exists for tests, which
swap providers (and inject a fake vision client) between cases.
"""
from __future__ import annotations

import logging

from app.config import get_settings
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


def get_client(provider: str | None = None) -> LLMClient:
    if _override is not None:
        return _override

    provider = provider or get_settings().llm_provider
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
    "get_client",
    "llm_available",
    "reset_client",
    "set_client",
]
