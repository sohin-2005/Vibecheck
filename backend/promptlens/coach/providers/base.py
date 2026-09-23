"""LLM provider interface."""

from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class CloudNotConfirmedError(RuntimeError):
    pass
