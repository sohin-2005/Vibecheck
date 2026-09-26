"""Session list, detail and timeline replay."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session as DB

from vibecheck.api.deps import Filters, filters, get_db, num
from vibecheck.db.models import (
    Commit,
    LineSurvival,
    Message,
    Project,
    Session,
    SessionCommit,
    ToolCall,
)

router = APIRouter()

SORTS = {
    "started_at": Session.started_at,
    "struggle_score": Session.struggle_score,
    "cost": Session.est_cost_usd,
    "turns": Session.human_turns,
    "tokens": Session.output_tokens,
}


def session_summary(s: Session, project: str | None) -> dict[str, Any]:
    return {
        "id": s.id,
        "tool": s.tool,
        "title": s.title,
        "project_id": s.project_id,
        "project": project,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
        "active_minutes": num(s.active_minutes),
        "human_turns": s.human_turns,
        "assistant_turns": s.assistant_turns,
        "input_tokens": s.input_tokens,
        "output_tokens": s.output_tokens,
        "cache_write_tokens": s.cache_write_tokens,
        "cache_read_tokens": s.cache_read_tokens,
        "cost_usd": num(s.est_cost_usd),
        "models": s.models,
        "struggle_score": num(s.struggle_score),
        "has_commit": s.has_commit,
        "turns_to_commit": s.turns_to_commit,
    }


@router.get("/sessions")
def list_sessions(
    f: Filters = Depends(filters),
    sort: Literal["started_at", "struggle_score", "cost", "turns", "tokens"] = "started_at",
    order: Literal["asc", "desc"] = "desc",
    has_commit: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: DB = Depends(get_db),
) -> dict[str, Any]:
    q = f.apply(select(Session, Project.name).outerjoin(Project, Project.id == Session.project_id))
    if has_commit is not None:
        q = q.where(Session.has_commit.is_(has_commit))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    col = SORTS[sort]
    col = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
    rows = db.execute(q.order_by(col, Session.id).offset((page - 1) * page_size).limit(page_size))
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [session_summary(s, name) for s, name in rows],
    }


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, db: DB = Depends(get_db)) -> dict[str, Any]:
    s = db.get(Session, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    project = db.get(Project, s.project_id) if s.project_id else None
    commits = []
    for c, link in db.execute(
        select(Commit, SessionCommit)
        .join(SessionCommit, SessionCommit.commit_sha == Commit.sha)
        .where(SessionCommit.session_id == session_id)
        .order_by(Commit.authored_at)
    ):
        surv = {
            r.days_after: (
                round(100 * r.lines_surviving / r.lines_total, 1)
                if r.status == "ok" and r.lines_total
                else None
            )
            for r in db.scalars(select(LineSurvival).where(LineSurvival.commit_sha == c.sha))
        }
        ai_surv = {
            r.days_after: round(100 * (r.ai_lines_surviving or 0) / r.ai_lines_total, 1)
            for r in db.scalars(select(LineSurvival).where(LineSurvival.commit_sha == c.sha))
            if r.status == "ok" and r.ai_lines_total
        }
        commits.append(
            {
                "sha": c.sha,
                "subject": c.message.splitlines()[0] if c.message else "",
                "authored_at": c.authored_at,
                "link_method": link.link_method,
                "confidence": float(link.confidence),
                "ai_coauthored": c.ai_coauthored,
                "lines_added": c.lines_added,
                "lines_deleted": c.lines_deleted,
                "survival": surv,
                "ai_survival": ai_surv,
            }
        )
    tools = db.execute(
        select(
            ToolCall.tool_name,
            func.count(),
            func.sum(case((ToolCall.is_error.is_(True), 1), else_=0)),
        )
        .where(ToolCall.session_id == session_id)
        .group_by(ToolCall.tool_name)
        .order_by(func.count().desc())
    ).all()
    return {
        **session_summary(s, project.name if project else None),
        "git_branch": s.git_branch,
        "cc_version": s.cc_version,
        "cwd": project.cwd if project else None,
        "struggle_signals": s.struggle_signals,
        "commits": commits,
        "tools": [{"tool_name": t, "calls": n, "errors": int(e or 0)} for t, n, e in tools],
    }


@router.get("/sessions/{session_id}/timeline")
def timeline(session_id: str, db: DB = Depends(get_db)) -> list[dict[str, Any]]:
    if db.get(Session, session_id) is None:
        raise HTTPException(404, "session not found")
    items: list[dict[str, Any]] = []
    for m in db.scalars(select(Message).where(Message.session_id == session_id)):
        if m.role == "assistant" and not m.text:
            continue  # tool-only blocks are shown as tool chips
        items.append(
            {
                "kind": "prompt"
                if m.is_human_prompt
                else "interrupt"
                if m.is_interrupt
                else "assistant",
                "timestamp": m.timestamp,
                "text": m.text,
                "model": m.model,
                "is_sidechain": m.is_sidechain,
            }
        )
    for t in db.scalars(select(ToolCall).where(ToolCall.session_id == session_id)):
        items.append(
            {
                "kind": "tool",
                "timestamp": t.timestamp,
                "tool_name": t.tool_name,
                "file_path": t.file_path,
                "command": t.command,
                "is_error": t.is_error,
                "is_sidechain": t.is_sidechain,
            }
        )
    items.sort(key=lambda i: (i["timestamp"] is None, i["timestamp"] or 0))
    return items
