"""The LLM rubric for scoring prompts. Bump RUBRIC_VERSION whenever SYSTEM_PROMPT changes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RUBRIC_VERSION = "v1"
MAX_PROMPT_CHARS = 1500

SYSTEM_PROMPT = """You evaluate prompts a developer gave to an AI coding assistant.
For each prompt, return JSON with:
- id: the id you were given
- specificity: 1-5 (1 = vague like "fix it", 5 = precise target, constraints and expected behavior)
- has_context: true if it mentions files, errors, examples or relevant code
- has_success_criteria: true if it states what done looks like
- scope: "small" | "medium" | "too_large" (too_large = several unrelated tasks or a whole
  feature in one request)
- category: "bugfix" | "feature" | "refactor" | "explain" | "test" | "other"
- suggestion: one short sentence on how to improve this prompt, or "" if it is already good
Return only a JSON object: {"results": [...]} with one entry per prompt."""


class PromptScoreItem(BaseModel):
    id: str
    specificity: int = Field(ge=1, le=5)
    has_context: bool
    has_success_criteria: bool
    scope: Literal["small", "medium", "too_large"]
    category: Literal["bugfix", "feature", "refactor", "explain", "test", "other"]
    suggestion: str = ""


class PromptScoreBatch(BaseModel):
    results: list[PromptScoreItem]


RESPONSE_SCHEMA = PromptScoreBatch.model_json_schema()
