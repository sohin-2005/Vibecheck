"""Team mode: share anonymized weekly aggregates, never raw data.

An export holds, per ISO week, only counts, rates and medians. It never contains prompt or
reply text, file paths, commands, commit messages or session ids, and project names are
hashed unless the member opts in to sharing them.
"""

from __future__ import annotations

import hashlib
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from vibecheck.coach.rubric import RUBRIC_VERSION
from vibecheck.db.models import (
    Commit,
    LineSurvival,
    Message,
    Project,
    PromptFeatures,
    PromptScore,
    Session,
    SessionCommit,
    TeamSnapshot,
    ToolCall,
)
from vibecheck.db.upsert import upsert

SCHEMA = "vibecheck.team.v1"
LEGACY_SCHEMAS = {"promptlens.team.v1"}  # exports made before the rename


class WeekAggregate(BaseModel):
    week: str = Field(pattern=r"^\d{4}-W\d{2}$")
    sessions: int = Field(ge=0)
    prompts: int = Field(ge=0)
    active_hours: float = Field(ge=0)
    tokens: int = Field(ge=0)
    cost_usd: float | None = None
    commit_rate: float | None = None
    median_struggle: float | None = None
    tool_error_rate: float | None = None
    survival_7d: float | None = None
    survival_basis: str | None = None
    avg_specificity: float | None = None
    pct_context: float | None = None
    tools: dict[str, int] = {}
    projects: dict[str, int] = {}


class TeamExport(BaseModel):
    schema_: str = Field(alias="schema")
    member: str = Field(min_length=1, max_length=80)
    generated_at: datetime
    weeks: list[WeekAggregate]


def _week(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _pct(n: float, d: float) -> float | None:
    return round(100 * n / d, 1) if d else None


def _project_label(name: str, include: bool) -> str:
    return name if include else "project-" + hashlib.sha1(name.encode()).hexdigest()[:6]


def build_export(
    db: DB,
    member: str,
    weeks: int = 8,
    include_projects: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    since = now - timedelta(weeks=weeks)
    names = {p.id: p.name for p in db.scalars(select(Project))}
    sessions = list(
        db.scalars(select(Session).where(Session.started_at >= since, Session.started_at <= now))
    )
    by_week: dict[str, list[Session]] = defaultdict(list)
    for s in sessions:
        by_week[_week(s.started_at)].append(s)  # type: ignore[arg-type]

    ids = [s.id for s in sessions]
    calls: dict[str, list[bool]] = defaultdict(list)
    for sid, err in db.execute(
        select(ToolCall.session_id, ToolCall.is_error).where(ToolCall.session_id.in_(ids))
    ):
        calls[sid].append(bool(err))
    prompts: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
    for sid, pf, ps in db.execute(
        select(Message.session_id, PromptFeatures, PromptScore)
        .outerjoin(PromptFeatures, PromptFeatures.message_id == Message.id)
        .outerjoin(
            PromptScore,
            (PromptScore.message_id == Message.id) & (PromptScore.rubric_version == RUBRIC_VERSION),
        )
        .where(Message.session_id.in_(ids), Message.is_human_prompt.is_(True))
    ):
        prompts[sid].append((pf, ps))

    survival: dict[str, list[LineSurvival]] = defaultdict(list)
    for c, ls in db.execute(
        select(Commit, LineSurvival)
        .join(LineSurvival, LineSurvival.commit_sha == Commit.sha)
        .where(
            Commit.sha.in_(
                select(SessionCommit.commit_sha).where(SessionCommit.session_id.in_(ids))
            ),
            LineSurvival.days_after == 7,
            LineSurvival.status == "ok",
        )
    ):
        survival[_week(c.authored_at)].append(ls)

    out = []
    for week in sorted(by_week):
        ss = by_week[week]
        errs = [e for s in ss for e in calls[s.id]]
        ps_all = [p for s in ss for p in prompts[s.id]]
        scored = [ps for _, ps in ps_all if ps is not None]
        ctx = [
            ps.has_context
            if ps is not None
            else bool(pf and (pf.mentions_file or pf.has_error_text))
            for pf, ps in ps_all
        ]
        raws = [
            float(s.struggle_signals["raw_score"])
            for s in ss
            if s.struggle_signals and "raw_score" in s.struggle_signals
        ]
        costs = [float(s.est_cost_usd) for s in ss if s.est_cost_usd is not None]
        rows = survival.get(week, [])
        ai_rows = [r for r in rows if r.ai_lines_total]
        if ai_rows:
            surv = _pct(
                sum(r.ai_lines_surviving or 0 for r in ai_rows),
                sum(r.ai_lines_total or 0 for r in ai_rows),
            )
            basis = "edit-matched"
        else:
            surv = _pct(sum(r.lines_surviving for r in rows), sum(r.lines_total for r in rows))
            basis = "whole-commit" if rows else None
        out.append(
            WeekAggregate(
                week=week,
                sessions=len(ss),
                prompts=len(ps_all),
                active_hours=round(sum(float(s.active_minutes or 0) for s in ss) / 60, 1),
                tokens=sum(s.input_tokens + s.output_tokens for s in ss),
                cost_usd=round(sum(costs), 2) if costs else None,
                commit_rate=_pct(sum(1 for s in ss if s.has_commit), len(ss)),
                median_struggle=round(statistics.median(raws), 2) if raws else None,
                tool_error_rate=_pct(sum(errs), len(errs)),
                survival_7d=surv,
                survival_basis=basis,
                avg_specificity=round(sum(p.specificity for p in scored) / len(scored), 2)
                if scored
                else None,
                pct_context=_pct(sum(ctx), len(ctx)),
                tools=dict(Counter(s.tool for s in ss)),
                projects=dict(
                    Counter(
                        _project_label(names.get(s.project_id or -1, "none"), include_projects)
                        for s in ss
                    )
                ),
            ).model_dump()
        )
    return {"schema": SCHEMA, "member": member, "generated_at": now.isoformat(), "weeks": out}


def import_export(db: DB, payload: dict[str, Any]) -> int:
    """Validate and upsert a teammate's export. Returns the number of weeks stored."""
    try:
        data = TeamExport.model_validate(payload)
    except ValidationError as e:
        raise ValueError(f"not a valid Vibecheck team export: {e}") from e
    if data.schema_ != SCHEMA and data.schema_ not in LEGACY_SCHEMAS:
        raise ValueError(f"unsupported export schema {data.schema_!r}; expected {SCHEMA}")
    now = datetime.now(UTC)
    rows = [
        {"member": data.member, "week": w.week, "payload": w.model_dump(), "received_at": now}
        for w in data.weeks
    ]
    upsert(db, TeamSnapshot, rows, keys=["member", "week"], update=["payload", "received_at"])
    db.commit()
    return len(rows)


def team_table(db: DB) -> dict[str, Any]:
    snaps = list(db.scalars(select(TeamSnapshot).order_by(TeamSnapshot.week)))
    return {
        "members": sorted({s.member for s in snaps}),
        "weeks": sorted({s.week for s in snaps}),
        "rows": [{"member": s.member, **s.payload, "received_at": s.received_at} for s in snaps],
    }
