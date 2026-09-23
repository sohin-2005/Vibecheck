"""Struggle score: weighted friction signals, ranked 0-100 across the user's sessions."""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from promptlens.config import Config
from promptlens.db.models import Message, Session, ToolCall
from promptlens.ingest.parser import EDIT_TOOLS

EDIT_ALLOWANCE = 3  # edits to the same file beyond this count as "repeated"


def compute_signals(
    prompts: list[str],
    interrupts: int,
    tool_errors: int,
    edit_paths: list[str],
    correction_patterns: list[str],
) -> dict[str, int]:
    regexes = [re.compile(p, re.IGNORECASE) for p in correction_patterns]
    corrections = sum(1 for p in prompts if any(r.search(p) for r in regexes))
    repeated = sum(max(0, n - EDIT_ALLOWANCE) for n in Counter(edit_paths).values())
    return {
        "interrupts": interrupts,
        "corrections": corrections,
        "tool_errors": tool_errors,
        "repeated_edits": repeated,
        "turns": len(prompts),
    }


def raw_score(signals: dict[str, int], weights: dict[str, float]) -> float:
    return float(sum(weights.get(k, 0.0) * v for k, v in signals.items()))


def percentile_ranks(raw: dict[str, float]) -> dict[str, float]:
    """Share of other sessions with a strictly lower raw score, scaled to 0-100."""
    n = len(raw)
    if n <= 1:
        return {k: 0.0 for k in raw}
    values = sorted(raw.values())
    out = {}
    for k, v in raw.items():
        below = sum(1 for x in values if x < v)
        out[k] = round(below / (n - 1) * 100, 2)
    return out


def compute_struggle(db: DB, cfg: Config) -> int:
    sessions = db.scalars(select(Session.id)).all()
    prompts: dict[str, list[str]] = {s: [] for s in sessions}
    interrupts: Counter[str] = Counter()
    for sid, text, is_human, is_int in db.execute(
        select(Message.session_id, Message.text, Message.is_human_prompt, Message.is_interrupt)
    ):
        if is_human:
            prompts[sid].append(text or "")
        elif is_int:
            interrupts[sid] += 1
    errors = dict(
        db.execute(
            select(ToolCall.session_id, func.count())
            .where(ToolCall.is_error.is_(True))
            .group_by(ToolCall.session_id)
        ).all()
    )
    edits: dict[str, list[str]] = {}
    for sid, path in db.execute(
        select(ToolCall.session_id, ToolCall.file_path).where(
            ToolCall.tool_name.in_(EDIT_TOOLS), ToolCall.file_path.is_not(None)
        )
    ):
        edits.setdefault(sid, []).append(path)

    signals = {
        s: compute_signals(
            prompts[s], interrupts[s], errors.get(s, 0), edits.get(s, []), cfg.correction_patterns
        )
        for s in sessions
    }
    raws = {s: raw_score(sig, cfg.weights) for s, sig in signals.items()}
    ranks = percentile_ranks(raws)
    for s in sessions:
        obj = db.get(Session, s)
        obj.struggle_signals = {**signals[s], "raw_score": raws[s]}  # type: ignore[union-attr]
        obj.struggle_score = Decimal(str(ranks[s]))  # type: ignore[union-attr]
    db.commit()
    return len(sessions)
