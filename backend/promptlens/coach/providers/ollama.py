"""Local models via Ollama (http://localhost:11434)."""

from __future__ import annotations

import json
from typing import Any

import httpx


class OllamaProvider:
    name = "ollama"

    def __init__(self, url: str, model: str, client: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.model = model
        self.client = client or httpx.Client(timeout=300)

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        r = self.client.post(
            f"{self.url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "format": schema or "json",
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        r.raise_for_status()
        return json.loads(r.json()["message"]["content"])
