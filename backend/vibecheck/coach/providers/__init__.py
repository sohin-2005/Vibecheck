"""Provider factory."""

from __future__ import annotations

import os

from vibecheck.coach.providers.base import CloudNotConfirmedError, LLMProvider
from vibecheck.config import Config

CLOUD = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}

__all__ = ["CloudNotConfirmedError", "LLMProvider", "get_provider"]


def get_provider(cfg: Config) -> LLMProvider:
    name = cfg.llm_provider
    if name == "ollama":
        from vibecheck.coach.providers.ollama import OllamaProvider

        return OllamaProvider(cfg.ollama_url, cfg.llm_model)
    if name not in CLOUD:
        raise ValueError(f"Unknown LLM provider {name!r} (use ollama, gemini or groq)")
    if not cfg.send_to_cloud_confirmed:
        raise CloudNotConfirmedError(
            f"Provider {name!r} sends your (redacted) prompts to a cloud API. "
            "Set [llm] send_to_cloud_confirmed = true in config to allow it."
        )
    key = os.environ.get(CLOUD[name])
    if not key:
        raise RuntimeError(f"Set the {CLOUD[name]} environment variable to use {name}.")
    if name == "gemini":
        from vibecheck.coach.providers.gemini import GeminiProvider

        return GeminiProvider(key, cfg.llm_model)
    from vibecheck.coach.providers.groq import GroqProvider

    return GroqProvider(key, cfg.llm_model)
