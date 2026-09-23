"""Score human prompts with an LLM: batching, caching and validation. See SPEC §7.11."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from promptlens.coach.providers.base import LLMProvider
from promptlens.coach.rubric import (
    MAX_PROMPT_CHARS,
    RESPONSE_SCHEMA,
    RUBRIC_VERSION,
    SYSTEM_PROMPT,
    PromptScoreBatch,
    PromptScoreItem,
)
from promptlens.config import Config
from promptlens.db.models import Message, PromptScore

log = logging.getLogger(__name__)


@dataclass
class ScoreResult:
    scored: int = 0
    cached: int = 0
    llm_calls: int = 0
    failed: int = 0


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BatchError(Exception):
    pass


def _parse(raw: dict[str, Any], expected: set[str]) -> dict[str, PromptScoreItem]:
    batch = PromptScoreBatch.model_validate(raw)
    got = {r.id: r for r in batch.results}
    missing = expected - set(got)
    if missing:
        raise BatchError(f"missing results for ids {sorted(missing)}")
    return got


class _Scorer:
    def __init__(self, provider: LLMProvider, res: ScoreResult):
        self.provider, self.res = provider, res

    def call(self, texts: list[str], error: str | None = None) -> dict[str, PromptScoreItem]:
        payload: dict[str, Any] = {
            "prompts": [{"id": str(i), "text": t[:MAX_PROMPT_CHARS]} for i, t in enumerate(texts)]
        }
        if error:
            payload["error"] = f"Your previous answer was invalid: {error}. Return valid JSON."
        self.res.llm_calls += 1
        raw = self.provider.complete_json(SYSTEM_PROMPT, json.dumps(payload), RESPONSE_SCHEMA)
        return _parse(raw, {str(i) for i in range(len(texts))})

    def score_batch(self, texts: list[str]) -> list[PromptScoreItem | None]:
        """Try the batch, retry once with the error, then fall back to one-at-a-time."""
        error = None
        for attempt in range(2):
            try:
                got = self.call(texts, error if attempt else None)
                return [got[str(i)] for i in range(len(texts))]
            except (ValidationError, BatchError, ValueError, KeyError, TypeError) as e:
                error = str(e)[:500]
            except Exception as e:  # noqa: BLE001 - network errors etc.
                error = str(e)[:500]
                log.warning("LLM call failed: %s", e)
        out: list[PromptScoreItem | None] = []
        for t in texts:
            try:
                out.append(self.call([t])["0"])
            except Exception as e:  # noqa: BLE001
                log.warning("single prompt scoring failed: %s", e)
                out.append(None)
        return out


def score_prompts(
    db: DB, cfg: Config, provider: LLMProvider, limit: int | None = None
) -> ScoreResult:
    res = ScoreResult()
    scored_ids = select(PromptScore.message_id).where(PromptScore.rubric_version == RUBRIC_VERSION)
    pending = [
        (mid, text)
        for mid, text in db.execute(
            select(Message.id, Message.text)
            .where(Message.is_human_prompt.is_(True), Message.id.not_in(scored_ids))
            .order_by(Message.timestamp, Message.id)
        )
        if text and len(text) >= cfg.min_prompt_chars
    ]
    if limit is not None:
        pending = pending[:limit]
    if not pending:
        return res

    cache: dict[str, PromptScore] = {
        s.text_hash: s
        for s in db.scalars(
            select(PromptScore).where(
                PromptScore.rubric_version == RUBRIC_VERSION,
                PromptScore.model_used == provider.model,
            )
        )
    }
    now = datetime.now(UTC)

    def store(mid: int, h: str, item: PromptScoreItem | PromptScore) -> None:
        row = PromptScore(
            message_id=mid,
            rubric_version=RUBRIC_VERSION,
            model_used=provider.model,
            text_hash=h,
            specificity=item.specificity,
            has_context=item.has_context,
            has_success_criteria=item.has_success_criteria,
            scope=item.scope,
            category=item.category,
            suggestion=item.suggestion or "",
            created_at=now,
        )
        db.add(row)
        cache.setdefault(h, row)
        res.scored += 1

    # Identical texts share one LLM result.
    todo: dict[str, list[int]] = {}
    texts: dict[str, str] = {}
    for mid, text in pending:
        h = text_hash(text)
        if h in cache:
            store(mid, h, cache[h])
            res.cached += 1
        else:
            todo.setdefault(h, []).append(mid)
            texts[h] = text

    scorer = _Scorer(provider, res)
    hashes = list(todo)
    for i in range(0, len(hashes), cfg.llm_batch_size):
        chunk = hashes[i : i + cfg.llm_batch_size]
        items = scorer.score_batch([texts[h] for h in chunk])
        for h, item in zip(chunk, items, strict=True):
            if item is None:
                res.failed += len(todo[h])
                continue
            first, *rest = todo[h]
            store(first, h, item)
            for mid in rest:
                store(mid, h, item)
                res.cached += 1
        db.commit()
    return res
