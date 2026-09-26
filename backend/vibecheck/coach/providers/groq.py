"""Groq (cloud, OpenAI-compatible; requires send_to_cloud_confirmed and GROQ_API_KEY)."""

from __future__ import annotations

import json
from typing import Any

import httpx

API = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None):
        self.model = model
        self._key = api_key
        self.client = client or httpx.Client(timeout=120)

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        r = self.client.post(
            API,
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
