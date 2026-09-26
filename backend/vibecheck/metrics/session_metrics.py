"""Per-session aggregates: turns, deduplicated tokens, API-equivalent cost, active time."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from vibecheck.config import Config, ModelPrice
from vibecheck.db.models import Message, RawEvent, Session

ACTIVE_GAP = timedelta(minutes=30)


@dataclass
class UsageRow:
    api_message_id: str | None
    model: str | None
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class ModelUsage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_write + self.cache_read


def dedupe_usage(rows: Iterable[UsageRow]) -> dict[str, ModelUsage]:
    """Sum usage per model, counting each API message id once (streamed lines repeat usage).

    When rows sharing an id differ (e.g. a text row plus a usage-only row), the one with the
    most tokens wins.
    """
    unique: dict[str, UsageRow] = {}
    anonymous: list[UsageRow] = []

    def total(r: UsageRow) -> int:
        return r.input + r.output + r.cache_write + r.cache_read

    for r in rows:
        if r.api_message_id:
            cur = unique.get(r.api_message_id)
            if cur is None or total(r) >= total(cur):
                unique[r.api_message_id] = r
        else:
            anonymous.append(r)
    out: dict[str, ModelUsage] = {}
    for r in [*unique.values(), *anonymous]:
        m = out.setdefault(r.model or "unknown", ModelUsage())
        m.input += r.input
        m.output += r.output
        m.cache_write += r.cache_write
        m.cache_read += r.cache_read
    return out


def estimate_cost(per_model: dict[str, ModelUsage], prices: dict[str, ModelPrice]) -> float | None:
    """API-equivalent USD. None if no usage was recorded (some tools don't log tokens) or if
    any model that used tokens has no configured price."""
    if not any(u.total for u in per_model.values()):
        return None
    total = 0.0
    for model, u in per_model.items():
        if u.total == 0:
            continue
        p = prices.get(model)
        if p is None:
            return None
        total += (
            u.input * p.input
            + u.output * p.output
            + u.cache_write * p.cache_write
            + u.cache_read * p.cache_read
        ) / 1_000_000
    return round(total, 4)


def active_minutes(timestamps: Sequence[datetime], max_gap: timedelta = ACTIVE_GAP) -> float:
    """Session time with idle gaps longer than ``max_gap`` removed."""
    ts = sorted(timestamps)
    active = timedelta()
    for a, b in zip(ts, ts[1:], strict=False):
        if b - a <= max_gap:
            active += b - a
    return round(active.total_seconds() / 60, 2)


def recompute_session(db: DB, session_id: str, cfg: Config) -> None:
    s = db.get(Session, session_id)
    if s is None:
        return
    msgs = db.execute(
        select(
            Message.role,
            Message.is_human_prompt,
            Message.api_message_id,
            Message.model,
            Message.input_tokens,
            Message.output_tokens,
            Message.cache_write_tokens,
            Message.cache_read_tokens,
            Message.timestamp,
            Message.is_sidechain,
        ).where(Message.session_id == session_id)
    ).all()
    main = [m for m in msgs if cfg.include_sidechains or not m.is_sidechain]
    assistant = [m for m in main if m.role == "assistant"]
    per_model = dedupe_usage(
        UsageRow(m.api_message_id, m.model, m[4], m[5], m[6], m[7]) for m in assistant
    )
    s.human_turns = sum(1 for m in main if m.is_human_prompt)
    s.assistant_turns = len({m.api_message_id or id(m) for m in assistant})
    s.input_tokens = sum(u.input for u in per_model.values())
    s.output_tokens = sum(u.output for u in per_model.values())
    s.cache_write_tokens = sum(u.cache_write for u in per_model.values())
    s.cache_read_tokens = sum(u.cache_read for u in per_model.values())
    s.models = sorted(m for m, u in per_model.items() if u.total > 0)
    cost = estimate_cost(per_model, cfg.pricing)
    s.est_cost_usd = Decimal(str(cost)) if cost is not None else None

    first, last = db.execute(
        select(func.min(RawEvent.timestamp), func.max(RawEvent.timestamp)).where(
            RawEvent.session_id == session_id
        )
    ).one()
    s.started_at, s.ended_at = first, last
    stamps = [m.timestamp for m in main if m.timestamp]
    s.active_minutes = active_minutes(stamps)
    if not s.title:  # tools without a title event: use the first prompt
        first = db.scalar(
            select(Message.text)
            .where(Message.session_id == session_id, Message.is_human_prompt.is_(True))
            .order_by(Message.timestamp)
            .limit(1)
        )
        if first:
            flat = " ".join(first.split())
            s.title = flat if len(flat) <= 70 else flat[:69] + "…"
