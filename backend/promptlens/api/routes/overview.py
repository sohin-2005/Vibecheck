"""Overview totals, daily series and projects."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from promptlens.api.deps import Filters, filters, get_db, num
from promptlens.db.models import Commit, LineSurvival, Project, Session, SessionCommit

router = APIRouter()


@router.get("/overview")
def overview(f: Filters = Depends(filters), db: DB = Depends(get_db)) -> dict[str, Any]:
    sessions = db.scalars(f.apply(select(Session))).all()
    names = {p.id: p.name for p in db.scalars(select(Project))}
    daily: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"sessions": 0, "tokens": 0, "cost": 0.0, "active_minutes": 0.0}
    )
    per_project: dict[str, int] = defaultdict(int)
    for s in sessions:
        if s.started_at is None:
            continue
        d = daily[s.started_at.date().isoformat()]
        d["sessions"] += 1
        d["tokens"] += s.input_tokens + s.output_tokens
        d["cost"] += float(s.est_cost_usd or 0)
        d["active_minutes"] += float(s.active_minutes or 0)
        per_project[names.get(s.project_id or -1, "unknown")] += 1

    ids = [s.id for s in sessions]
    surv = db.execute(
        select(
            func.coalesce(func.sum(LineSurvival.lines_total), 0),
            func.coalesce(func.sum(LineSurvival.lines_surviving), 0),
        )
        .join(Commit, Commit.sha == LineSurvival.commit_sha)
        .join(SessionCommit, SessionCommit.commit_sha == Commit.sha)
        .where(
            SessionCommit.session_id.in_(ids),
            LineSurvival.days_after == 7,
            LineSurvival.status == "ok",
        )
    ).one()
    priced = [s for s in sessions if s.est_cost_usd is not None]
    return {
        "totals": {
            "sessions": len(sessions),
            "active_hours": round(sum(float(s.active_minutes or 0) for s in sessions) / 60, 1),
            "prompts": sum(s.human_turns for s in sessions),
            "input_tokens": sum(s.input_tokens for s in sessions),
            "output_tokens": sum(s.output_tokens for s in sessions),
            "cache_write_tokens": sum(s.cache_write_tokens for s in sessions),
            "cache_read_tokens": sum(s.cache_read_tokens for s in sessions),
            "cost_usd": round(sum(float(s.est_cost_usd or 0) for s in priced), 2)
            if priced
            else None,
            "unpriced_sessions": len(sessions) - len(priced),
            "sessions_with_commit": sum(1 for s in sessions if s.has_commit),
            "survival_7d": round(100 * surv[1] / surv[0], 1) if surv[0] else None,
        },
        "daily": [
            {"date": k, **{kk: round(v, 4) if isinstance(v, float) else v for kk, v in d.items()}}
            for k, d in sorted(daily.items())
        ],
        "by_project": [
            {"project": k, "sessions": v}
            for k, v in sorted(per_project.items(), key=lambda kv: -kv[1])
        ],
    }


@router.get("/sources")
def sources(db: DB = Depends(get_db)) -> list[dict[str, Any]]:
    from promptlens.sources import ADAPTERS

    counts = dict(db.execute(select(Session.tool, func.count()).group_by(Session.tool)).all())
    return [
        {"tool": name, "sessions": counts.get(name, 0), "verified": a.verified}
        for name, a in ADAPTERS.items()
    ]


@router.get("/projects")
def projects(db: DB = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Project, func.count(Session.id), func.sum(Session.est_cost_usd))
        .outerjoin(Session, Session.project_id == Project.id)
        .group_by(Project.id)
        .order_by(Project.name)
    ).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "cwd": p.cwd,
            "repo_root": p.repo_root,
            "sessions": n,
            "cost_usd": num(cost),
        }
        for p, n, cost in rows
    ]
