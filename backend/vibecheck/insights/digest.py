"""Day-one digest: your worst recent session, what went wrong, and what to try next.

Unlike insights (which need dozens of sessions), this works from a single session: it
explains one session's struggle signals in concrete terms, using the actual prompts,
failing commands and files involved.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from vibecheck.coach.features import extract_features
from vibecheck.config import Config
from vibecheck.db.models import Message, Project, Session, ToolCall
from vibecheck.ingest.parser import EDIT_TOOLS, strip_pasted
from vibecheck.metrics.struggle import (
    EDIT_ALLOWANCE,
    collect_signals,
    correction_text,
    raw_score,
)

FALLBACK_SESSIONS = 10
INSIGHT_THRESHOLD = 20  # roughly two groups of 10


def _short(text: str, n: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path)[-1]


def _went_wrong(db: DB, cfg: Config, sid: str, signals: dict[str, int]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    w = cfg.weights
    if signals["corrections"]:
        regexes = [re.compile(p, re.IGNORECASE) for p in cfg.correction_patterns]
        prompts = db.scalars(
            select(Message.text)
            .where(Message.session_id == sid, Message.is_human_prompt.is_(True))
            .order_by(Message.timestamp)
        ).all()
        first = next(
            (p for p in prompts if p and any(r.search(correction_text(p)) for r in regexes)), ""
        )
        items.append(
            {
                "kind": "corrections",
                "points": signals["corrections"] * w.get("corrections", 0),
                "headline": f"You corrected the AI {signals['corrections']} time(s)",
                "detail": f'First correction: "{_short(strip_pasted(first))}"' if first else "",
            }
        )
    if signals["tool_errors"]:
        failed = db.execute(
            select(ToolCall.tool_name, ToolCall.command, ToolCall.file_path).where(
                ToolCall.session_id == sid, ToolCall.is_error.is_(True)
            )
        ).all()
        by_tool = Counter(t for t, _, _ in failed)
        tool, n = by_tool.most_common(1)[0]
        example = next((c or _basename(f) for t, c, f in failed if t == tool and (c or f)), None)
        detail = f"Mostly {tool} ({n})"
        if example:
            detail += f", e.g. `{_short(example, 80)}`"
        items.append(
            {
                "kind": "tool_errors",
                "points": signals["tool_errors"] * w.get("tool_errors", 0),
                "headline": f"{signals['tool_errors']} tool call(s) failed",
                "detail": detail,
            }
        )
    if signals["repeated_edits"]:
        paths = db.scalars(
            select(ToolCall.file_path).where(
                ToolCall.session_id == sid,
                ToolCall.tool_name.in_(EDIT_TOOLS),
                ToolCall.file_path.is_not(None),
            )
        ).all()
        path, n = Counter(paths).most_common(1)[0]
        items.append(
            {
                "kind": "repeated_edits",
                "points": signals["repeated_edits"] * w.get("repeated_edits", 0),
                "headline": "The same file was edited over and over",
                "detail": f"{_basename(path)} was edited {n} times "
                f"({n - EDIT_ALLOWANCE} more than a typical change needs)",
            }
        )
    if signals["interrupts"]:
        items.append(
            {
                "kind": "interrupts",
                "points": signals["interrupts"] * w.get("interrupts", 0),
                "headline": f"You interrupted the AI {signals['interrupts']} time(s)",
                "detail": "It was heading somewhere you didn't want.",
            }
        )
    if signals["turns"] >= 8:
        items.append(
            {
                "kind": "turns",
                "points": signals["turns"] * w.get("turns", 0),
                "headline": f"A long back-and-forth: {signals['turns']} prompts",
                "detail": "Long sessions tend to drift as context piles up.",
            }
        )
    items.sort(key=lambda i: -i["points"])
    return items


def _tips(
    first_prompt: str, went_wrong: list[dict[str, Any]], failed_tool: str | None
) -> list[str]:
    feats = extract_features(first_prompt, is_first=True)
    kinds = [i["kind"] for i in went_wrong]
    tips: list[str] = []
    if not feats["mentions_file"]:
        tips.append(
            "Name the file(s) in your first prompt, so the AI doesn't have to search or guess."
        )
    if ("corrections" in kinds or "turns" in kinds) and not feats["has_success_criteria"]:
        tips.append(
            'Say what "done" looks like up front (expected behaviour, or which test should pass).'
        )
    if "tool_errors" in kinds and failed_tool in ("Bash", "PowerShell", "shell", "RUN_COMMAND"):
        tips.append(
            "Tell the AI the exact command to build or test your project, instead of "
            "letting it guess."
        )
    if "repeated_edits" in kinds:
        tips.append("For a change that keeps touching one file, ask for a short plan before edits.")
    if "interrupts" in kinds:
        tips.append("Split the task into smaller steps so there's less to stop and redirect.")
    if "turns" in kinds:
        tips.append("When a session drifts, start fresh with a two-line summary of where you are.")
    return tips[:3]


def _summary(
    s: Session, project: str | None, raw: float, signals: dict[str, int]
) -> dict[str, Any]:
    return {
        "id": s.id,
        "title": s.title,
        "tool": s.tool,
        "project": project,
        "started_at": s.started_at,
        "prompts": signals["turns"],
        "raw_score": raw,
        "has_commit": s.has_commit,
    }


def build_digest(db: DB, cfg: Config, now: datetime | None = None, days: int = 7) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    window = list(
        db.scalars(select(Session).where(Session.started_at >= since, Session.started_at <= now))
    )
    fallback = False
    pool = window
    if not window:
        pool = list(
            db.scalars(
                select(Session)
                .where(Session.started_at.is_not(None))
                .order_by(Session.started_at.desc())
                .limit(FALLBACK_SESSIONS)
            )
        )
        fallback = bool(pool)
    total_sessions = db.scalar(select(func.count()).select_from(Session)) or 0
    out: dict[str, Any] = {
        "days": days,
        "sessions": len(window),
        "fallback": fallback,
        "prompts": 0,
        "active_hours": round(sum(float(s.active_minutes or 0) for s in window) / 60, 1),
        "sessions_with_commit": sum(1 for s in window if s.has_commit),
        "tools": dict(Counter(s.tool for s in window)),
        "worst": None,
        "best": None,
        "tips": [],
        "insights_progress": {"sessions": total_sessions, "needed": INSIGHT_THRESHOLD},
    }
    signals = collect_signals(db, cfg, [s.id for s in pool])
    pool = [s for s in pool if signals[s.id]["turns"] > 0]
    if not pool:
        return out
    out["prompts"] = sum(signals[s.id]["turns"] for s in window if s.id in signals)
    names = {p.id: p.name for p in db.scalars(select(Project))}
    raws = {s.id: raw_score(signals[s.id], cfg.weights) for s in pool}
    worst = max(pool, key=lambda s: raws[s.id])
    went_wrong = _went_wrong(db, cfg, worst.id, signals[worst.id])
    first_prompt = (
        db.scalar(
            select(Message.text)
            .where(Message.session_id == worst.id, Message.is_human_prompt.is_(True))
            .order_by(Message.timestamp)
            .limit(1)
        )
        or ""
    )
    failed_tool = db.scalar(
        select(ToolCall.tool_name)
        .where(ToolCall.session_id == worst.id, ToolCall.is_error.is_(True))
        .group_by(ToolCall.tool_name)
        .order_by(func.count().desc())
        .limit(1)
    )
    out["worst"] = {
        **_summary(worst, names.get(worst.project_id or -1), raws[worst.id], signals[worst.id]),
        "first_prompt": _short(strip_pasted(first_prompt), 240),
        "went_wrong": [{k: v for k, v in i.items() if k != "points"} for i in went_wrong[:3]],
    }
    out["tips"] = _tips(first_prompt, went_wrong, failed_tool) if went_wrong else []
    others = [s for s in pool if s.id != worst.id and raws[s.id] < raws[worst.id]]
    if others:
        best = min(others, key=lambda s: raws[s.id])
        out["best"] = _summary(
            best, names.get(best.project_id or -1), raws[best.id], signals[best.id]
        )
    return out
