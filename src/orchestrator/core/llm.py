"""LLM factory.

Centralizes chat-model construction so stages depend on this module instead of a
specific provider. Provider is selected at runtime via env vars; swap providers
without touching stage code.

Env vars:
- LLM_PROVIDER: "ollama" (default) or "openai"
- LLM_MODEL: model id; defaults to "gemma4:e2b" (ollama) or "gpt-4o-mini" (openai)
- OLLAMA_BASE_URL: defaults to http://localhost:11434
- LLM_TEMPERATURE: float, default 0.0
"""

from __future__ import annotations

import os
from typing import Optional

from langchain_core.language_models import BaseChatModel


_DEFAULT_MODELS = {
    "ollama": "gemma4:e2b",
    "openai": "gpt-4o-mini",
}


def get_chat_model(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    **kwargs,
) -> BaseChatModel:
    provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).lower()
    model = model or os.getenv("LLM_MODEL") or _DEFAULT_MODELS.get(provider)
    temperature = temperature if temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0.0"))

    if model is None:
        raise ValueError(f"No default model configured for provider '{provider}'")

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return ChatOllama(model=model, temperature=temperature, base_url=base_url, **kwargs)

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, temperature=temperature, **kwargs)

    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r} (expected 'ollama' or 'openai')")
