"""Google Gemini (cloud; requires send_to_cloud_confirmed and GEMINI_API_KEY)."""

from __future__ import annotations

import json
from typing import Any

import httpx

API = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None):
        self.model = model
        self._key = api_key
        self.client = client or httpx.Client(timeout=120)

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        r = self.client.post(
            f"{API}/{self.model}:generateContent",
            headers={"x-goog-api-key": self._key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
            },
        )
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
