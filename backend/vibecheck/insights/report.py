"""Weekly markdown report. See SPEC §7.13."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from vibecheck.coach.rubric import RUBRIC_VERSION
from vibecheck.db.models import (
    Commit,
    Insight,
    LineSurvival,
    Message,
    Project,
    PromptFeatures,
    PromptScore,
    Session,
)


@dataclass
class WeekStats:
    sessions: int
    active_hours: float
    tokens: int
    cost: float | None
    unpriced: int


def week_bounds(d: date) -> tuple[datetime, datetime]:
    monday = d - timedelta(days=d.weekday())
    start = datetime.combine(monday, time.min, tzinfo=UTC)
    return start, start + timedelta(days=7)


def _sessions(db: DB, start: datetime, end: datetime) -> list[Session]:
    return list(
        db.scalars(select(Session).where(Session.started_at >= start, Session.started_at < end))
    )


def week_stats(sessions: list[Session]) -> WeekStats:
    costs = [float(s.est_cost_usd) for s in sessions if s.est_cost_usd is not None]
    return WeekStats(
        sessions=len(sessions),
        active_hours=round(sum(float(s.active_minutes or 0) for s in sessions) / 60, 1),
        tokens=sum(s.input_tokens + s.output_tokens for s in sessions),
        cost=round(sum(costs), 2) if costs else None,
        unpriced=len(sessions) - len(costs),
    )


def _delta(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return "n/a"
    if prev == 0:
        return "new" if cur else "0%"
    return f"{(cur - prev) / prev * 100:+.0f}%"


def _habits(db: DB, start: datetime, end: datetime) -> tuple[float | None, float | None, int]:
    rows = db.execute(
        select(PromptFeatures, PromptScore.specificity, PromptScore.has_context)
        .join(Message, Message.id == PromptFeatures.message_id)
        .outerjoin(
            PromptScore,
            (PromptScore.message_id == Message.id) & (PromptScore.rubric_version == RUBRIC_VERSION),
        )
        .where(Message.timestamp >= start, Message.timestamp < end)
    ).all()
    if not rows:
        return None, None, 0
    specs = [s for _, s, _ in rows if s is not None]
    ctx = [
        c if c is not None else (f.mentions_file or f.has_error_text or f.has_code_block)
        for f, _, c in rows
    ]
    avg_spec = round(sum(specs) / len(specs), 2) if specs else None
    return avg_spec, round(100 * sum(ctx) / len(ctx), 1), len(rows)


def render_weekly_report(db: DB, today: date) -> tuple[str, str]:
    start, end = week_bounds(today)
    prev_start = start - timedelta(days=7)
    iso = start.isocalendar()
    label = f"{iso.year}-W{iso.week:02d}"
    cur_sessions = _sessions(db, start, end)
    cur, prev = week_stats(cur_sessions), week_stats(_sessions(db, prev_start, start))
    names = {p.id: p.name for p in db.scalars(select(Project))}

    lines = [
        f"# Vibecheck weekly report: {label}",
        "",
        f"{start.date()} to {(end - timedelta(days=1)).date()}. Generated {today}.",
        "",
        "## Summary",
        "",
        "| Metric | This week | Change vs previous week |",
        "|---|---|---|",
        f"| Sessions | {cur.sessions} | {_delta(cur.sessions, prev.sessions)} |",
        f"| Active hours | {cur.active_hours} | {_delta(cur.active_hours, prev.active_hours)} |",
        f"| Tokens (in+out) | {cur.tokens:,} | {_delta(cur.tokens, prev.tokens)} |",
        "| API-equivalent cost | "
        + (f"${cur.cost:,.2f}" if cur.cost is not None else "n/a")
        + f" | {_delta(cur.cost, prev.cost)} |",
        "",
    ]
    if cur.unpriced:
        plural = "s" if cur.unpriced != 1 else ""
        lines += [f"_{cur.unpriced} session{plural} used models with no configured price._", ""]

    lines += ["## Highest-struggle sessions", ""]
    top = sorted(
        (s for s in cur_sessions if s.struggle_score is not None),
        key=lambda s: float(s.struggle_score or 0),
        reverse=True,
    )[:3]
    if not top:
        lines.append("No scored sessions this week.")
    for s in top:
        sig = s.struggle_signals or {}
        why = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sig.items() if k != "raw_score")
        title = s.title or s.id[:8]
        lines.append(
            f"- **{title}** ({names.get(s.project_id or -1, '?')}, "
            f"{s.started_at:%a %d %b}): score {float(s.struggle_score or 0):.0f}. {why}"
        )
    lines.append("")

    lines += ["## Code survival", ""]
    surv = db.execute(
        select(LineSurvival.lines_total, LineSurvival.lines_surviving)
        .join(Commit, Commit.sha == LineSurvival.commit_sha)
        .where(
            Commit.authored_at >= prev_start,
            Commit.authored_at < start,
            LineSurvival.days_after == 7,
            LineSurvival.status == "ok",
        )
    ).all()
    total = sum(t for t, _ in surv)
    if total:
        alive = sum(a for _, a in surv)
        lines.append(
            f"7-day survival for AI commits from last week: **{100 * alive / total:.1f}%** "
            f"({alive:,} of {total:,} lines across {len(surv)} commits)."
        )
    else:
        lines.append("No AI-linked commits from last week have a 7-day checkpoint yet.")
    lines.append("")

    spec, ctx, n = _habits(db, start, end)
    pspec, pctx, _ = _habits(db, prev_start, start)
    lines += ["## Prompt habits", ""]
    if n:
        lines += [
            f"- Prompts this week: {n}",
            f"- Average specificity: {spec if spec is not None else 'not scored yet'}"
            + (f" (previous week {pspec})" if pspec is not None else ""),
            f"- Prompts with context: {ctx}%"
            + (f" (previous week {pctx}%)" if pctx is not None else ""),
        ]
    else:
        lines.append("No prompts this week.")
    lines.append("")

    lines += ["## Top insights", ""]
    found = db.scalars(select(Insight).order_by(Insight.n_a + Insight.n_b)).all()
    if found:
        lines += [f"- {i.title}" for i in list(reversed(found))[:3]]
        lines.append("")
        lines.append("_Correlations only; they don't prove the habit caused the outcome._")
    else:
        lines.append("Not enough sessions yet for comparisons (10 per group needed).")
    lines.append("")
    return label, "\n".join(lines)


def write_weekly_report(db: DB, out_dir: Path, today: date | None = None) -> Path:
    label, text = render_weekly_report(db, today or datetime.now(UTC).date())
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{label}.md"
    path.write_text(text, encoding="utf-8")
    return path
