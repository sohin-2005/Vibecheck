"""Lessons from past sessions: details from this project, habit numbers from all projects."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from vibecheck.coach.features import extract_features
from vibecheck.db.models import Insight, Message, Project, Session, ToolCall
from vibecheck.ingest.parser import EDIT_TOOLS, strip_pasted
from vibecheck.insights.digest import INSIGHT_THRESHOLD
from vibecheck.mcp.locate import same_dir
from vibecheck.mcp.render import bullets, relative, short
from vibecheck.metrics.struggle import EDIT_ALLOWANCE

TOP = 3


def project_ids(db: DB, project_dir: Path) -> list[int]:
    here = str(project_dir)
    return [
        p.id
        for p in db.scalars(select(Project))
        if same_dir(p.cwd, here) or same_dir(p.repo_root or "", here)
    ]


def _hot_files(db: DB, sids: list[str], project_dir: Path) -> list[str]:
    per_session: Counter[tuple[str, str]] = Counter()
    for sid, path in db.execute(
        select(ToolCall.session_id, ToolCall.file_path).where(
            ToolCall.session_id.in_(sids),
            ToolCall.tool_name.in_(EDIT_TOOLS),
            ToolCall.file_path.is_not(None),
        )
    ):
        per_session[(sid, path)] += 1
    hot_sessions: Counter[str] = Counter()
    edits: Counter[str] = Counter()
    for (_, path), n in per_session.items():
        if n > EDIT_ALLOWANCE:
            hot_sessions[path] += 1
            edits[path] += n
    return [
        f"{relative(p, project_dir)}: re-edited in {k} session(s), {edits[p]} edits"
        for p, k in hot_sessions.most_common(TOP)
    ]


def _failing_commands(db: DB, sids: list[str]) -> list[str]:
    rows = db.scalars(
        select(ToolCall.command).where(
            ToolCall.session_id.in_(sids),
            ToolCall.is_error.is_(True),
            ToolCall.command.is_not(None),
        )
    ).all()
    counts = Counter(short(c, 80) for c in rows)
    return [f"`{c}` failed {n} time(s)" for c, n in counts.most_common(TOP)]


def _commit_line(sessions: list[Session]) -> str:
    done = [s for s in sessions if s.has_commit]
    turns = [s.turns_to_commit for s in done if s.turns_to_commit is not None]
    line = f"{len(done)} of {len(sessions)} session(s) reached a commit"
    if turns:
        line += f", after a median of {median(turns):g} prompt(s)"
    return line + "."


def _first_prompt_gaps(db: DB, sids: list[str]) -> tuple[float, float] | None:
    """Share of sessions whose first prompt named no file, and gave no success criteria."""
    first: dict[str, str] = {}
    for sid, text in db.execute(
        select(Message.session_id, Message.text)
        .where(Message.session_id.in_(sids), Message.is_human_prompt.is_(True))
        .order_by(Message.session_id, Message.timestamp, Message.id)
    ):
        first.setdefault(sid, strip_pasted(text or ""))
    if not first:
        return None
    feats = [extract_features(t, is_first=True) for t in first.values()]
    n = len(feats)
    no_file = sum(not f["mentions_file"] for f in feats) / n
    no_done = sum(not f["has_success_criteria"] for f in feats) / n
    return no_file, no_done


def _tips(hot: bool, fails: bool, gaps: tuple[float, float] | None) -> list[str]:
    tips: list[str] = []
    if gaps and gaps[0] >= 0.5:
        tips.append("If the user hasn't named the file(s), ask which ones before searching.")
    if gaps and gaps[1] >= 0.5:
        tips.append('Agree on what "done" means (behaviour or a passing test) before editing.')
    if fails:
        tips.append("Confirm the exact build or test command with the user instead of guessing.")
    if hot:
        tips.append("For changes in the files above, write a short plan before the first edit.")
    return tips[:3]


def project_lessons(db: DB, project_dir: Path, days: int = 30, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    ids = project_ids(db, project_dir)
    sessions = (
        list(
            db.scalars(
                select(Session).where(
                    Session.project_id.in_(ids), Session.started_at >= now - timedelta(days=days)
                )
            )
        )
        if ids
        else []
    )
    if not sessions:
        return (
            f"## Project lessons\nNo sessions recorded for this project in the last {days} "
            "days. Run `vibecheck run` to import recent sessions."
        )
    sids = [s.id for s in sessions]
    lines = [f"## Project lessons (last {days} days, {len(sessions)} session(s))"]
    hot = _hot_files(db, sids, project_dir)
    if hot:
        lines += ["", "Files that kept being re-edited:", *bullets(hot)]
    fails = _failing_commands(db, sids)
    if fails:
        lines += ["", "Commands that often failed:", *bullets(fails)]
    lines += ["", _commit_line(sessions)]
    gaps = _first_prompt_gaps(db, sids)
    if gaps:
        lines.append(
            f"First prompts: {gaps[0]:.0%} named no file, {gaps[1]:.0%} gave no success criteria."
        )
    tips = _tips(bool(hot), bool(fails), gaps)
    if tips:
        lines += ["", "For this task:", *bullets(tips)]
    return "\n".join(lines)


def habits(db: DB) -> str:
    total = db.scalar(select(func.count()).select_from(Session)) or 0
    if total < INSIGHT_THRESHOLD:
        return (
            f"## Habits\nNot enough history yet: {total} of {INSIGHT_THRESHOLD} sessions "
            "needed for habit comparisons."
        )
    rows = db.scalars(select(Insight).order_by(Insight.id)).all()
    if not rows:
        return (
            "## Habits\nNo clear habit differences found yet. "
            "Run `vibecheck insights` after more sessions."
        )
    return "\n".join(
        [f"## Habits (across {total} sessions, all projects)", *bullets(r.title for r in rows)]
    )
