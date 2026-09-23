"""Survival, tool usage, prompt coach and insights endpoints."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session as DB

from promptlens.api.deps import Filters, filters, get_db
from promptlens.coach.rubric import RUBRIC_VERSION
from promptlens.db.models import (
    Commit,
    CommitFile,
    Insight,
    LineSurvival,
    Message,
    Project,
    PromptFeatures,
    PromptScore,
    Session,
    SessionCommit,
    ToolCall,
)

router = APIRouter()


def _rate(alive: int, total: int) -> float | None:
    return round(100 * alive / total, 1) if total else None


def _session_ids(db: DB, f: Filters) -> list[str]:
    return list(db.scalars(f.apply(select(Session.id))))


@router.get("/survival")
def survival(
    f: Filters = Depends(filters),
    group_by: Literal["project", "file_ext"] = "project",
    db: DB = Depends(get_db),
) -> dict[str, Any]:
    q = (
        select(LineSurvival, Commit)
        .join(Commit, Commit.sha == LineSurvival.commit_sha)
        .where(Commit.is_merge.is_(False))
    )
    if f.start or f.end or f.project_id is not None:
        linked = select(SessionCommit.commit_sha).where(
            SessionCommit.session_id.in_(_session_ids(db, f))
        )
        q = q.where(Commit.sha.in_(linked))
    rows = db.execute(q).all()
    names = {p.id: p.name for p in db.scalars(select(Project))}

    checkpoints: dict[int, dict[str, int]] = defaultdict(
        lambda: {"lines_total": 0, "lines_surviving": 0, "commits": 0, "not_merged": 0}
    )
    groups: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    commit_rows: dict[str, dict[str, Any]] = {}
    ok_shas = set()
    for ls, c in rows:
        cp = checkpoints[ls.days_after]
        if ls.status != "ok":
            cp["not_merged"] += 1
            continue
        cp["commits"] += 1
        cp["lines_total"] += ls.lines_total
        cp["lines_surviving"] += ls.lines_surviving
        ok_shas.add(c.sha)
        if group_by == "project":
            g = groups[(names.get(c.project_id, "?"), ls.days_after)]
            g[0] += ls.lines_total
            g[1] += ls.lines_surviving
        if ls.days_after == 7 and ls.lines_total:
            commit_rows[c.sha] = {
                "sha": c.sha,
                "subject": c.message.splitlines()[0] if c.message else "",
                "project": names.get(c.project_id, "?"),
                "authored_at": c.authored_at,
                "lines_total": ls.lines_total,
                "survival_7d": _rate(ls.lines_surviving, ls.lines_total),
            }

    if group_by == "file_ext" and ok_shas:
        # Attribute each commit's surviving lines to extensions pro rata by lines added.
        files: dict[str, list[CommitFile]] = defaultdict(list)
        for cf in db.scalars(select(CommitFile).where(CommitFile.commit_sha.in_(ok_shas))):
            files[cf.commit_sha].append(cf)
        for ls, c in rows:
            if ls.status != "ok" or not ls.lines_total:
                continue
            share = ls.lines_surviving / ls.lines_total
            for cf in files.get(c.sha, []):
                name = cf.file_path.rsplit("/", 1)[-1]
                ext = "." + name.rsplit(".", 1)[-1] if "." in name else "(none)"
                g = groups[(ext, ls.days_after)]
                g[0] += cf.lines_added
                g[1] += round(cf.lines_added * share)

    by_group: dict[str, dict[str, Any]] = defaultdict(dict)
    for (key, days), (total, alive) in groups.items():
        by_group[key]["key"] = key
        by_group[key][f"d{days}"] = _rate(alive, total)
        by_group[key][f"lines_d{days}"] = total

    return {
        "checkpoints": [
            {"days": d, **v, "rate": _rate(v["lines_surviving"], v["lines_total"])}
            for d, v in sorted(checkpoints.items())
        ],
        "groups": sorted(by_group.values(), key=lambda g: -(g.get("lines_d7") or 0)),
        "lowest_commits": sorted(commit_rows.values(), key=lambda r: r["survival_7d"] or 0)[:15],
    }


@router.get("/tools")
def tools(f: Filters = Depends(filters), db: DB = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(
        ToolCall.tool_name,
        func.count(),
        func.sum(case((ToolCall.is_error.is_(True), 1), else_=0)),
    ).group_by(ToolCall.tool_name)
    if f.start or f.end or f.project_id is not None:
        q = q.where(ToolCall.session_id.in_(_session_ids(db, f)))
    out = [
        {
            "tool_name": name,
            "calls": n,
            "errors": int(e or 0),
            "error_rate": round(100 * int(e or 0) / n, 1),
        }
        for name, n, e in db.execute(q)
    ]
    return sorted(out, key=lambda r: -r["calls"])


def _prompt_rows(db: DB, f: Filters) -> list[Any]:
    q = (
        select(Message, PromptFeatures, PromptScore)
        .join(Session, Session.id == Message.session_id)
        .outerjoin(PromptFeatures, PromptFeatures.message_id == Message.id)
        .outerjoin(
            PromptScore,
            (PromptScore.message_id == Message.id) & (PromptScore.rubric_version == RUBRIC_VERSION),
        )
        .where(Message.is_human_prompt.is_(True))
    )
    return list(db.execute(f.apply(q)))


@router.get("/coach/summary")
def coach_summary(f: Filters = Depends(filters), db: DB = Depends(get_db)) -> dict[str, Any]:
    rows = _prompt_rows(db, f)
    scored = [(m, pf, ps) for m, pf, ps in rows if ps is not None]
    spec_dist = {str(k): 0 for k in range(1, 6)}
    cats: dict[str, int] = defaultdict(int)
    scopes: dict[str, int] = defaultdict(int)
    for _, _, ps in scored:
        spec_dist[str(ps.specificity)] += 1
        cats[ps.category] += 1
        scopes[ps.scope] += 1

    weekly: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"prompts": 0, "spec_sum": 0, "scored": 0, "context": 0, "criteria": 0}
    )
    for m, pf, ps in rows:
        if m.timestamp is None:
            continue
        iso = m.timestamp.isocalendar()
        w = weekly[f"{iso.year}-W{iso.week:02d}"]
        w["prompts"] += 1
        ctx = ps.has_context if ps else bool(pf and (pf.mentions_file or pf.has_error_text))
        crit = ps.has_success_criteria if ps else bool(pf and pf.has_success_criteria)
        w["context"] += ctx
        w["criteria"] += crit
        if ps:
            w["scored"] += 1
            w["spec_sum"] += ps.specificity

    def pct(n: int, d: int) -> float | None:
        return round(100 * n / d, 1) if d else None

    feats = [pf for _, pf, _ in rows if pf is not None]
    return {
        "prompts": len(rows),
        "scored": len(scored),
        "rubric_version": RUBRIC_VERSION,
        "avg_specificity": round(sum(ps.specificity for *_, ps in scored) / len(scored), 2)
        if scored
        else None,
        "pct_context": pct(sum(ps.has_context for *_, ps in scored), len(scored)),
        "pct_success_criteria": pct(sum(ps.has_success_criteria for *_, ps in scored), len(scored)),
        "features": {
            "pct_mentions_file": pct(sum(p.mentions_file for p in feats), len(feats)),
            "pct_error_text": pct(sum(p.has_error_text for p in feats), len(feats)),
            "pct_code_block": pct(sum(p.has_code_block for p in feats), len(feats)),
            "pct_success_criteria": pct(sum(p.has_success_criteria for p in feats), len(feats)),
            "median_chars": sorted(p.char_len for p in feats)[len(feats) // 2] if feats else None,
        },
        "specificity_distribution": spec_dist,
        "categories": dict(cats),
        "scopes": dict(scopes),
        "weekly": [
            {
                "week": k,
                "prompts": v["prompts"],
                "avg_specificity": round(v["spec_sum"] / v["scored"], 2) if v["scored"] else None,
                "pct_context": pct(v["context"], v["prompts"]),
                "pct_success_criteria": pct(v["criteria"], v["prompts"]),
            }
            for k, v in sorted(weekly.items())
        ],
    }


@router.get("/coach/prompts")
def coach_prompts(
    f: Filters = Depends(filters),
    category: str | None = None,
    max_specificity: int | None = Query(None, ge=1, le=5),
    only_suggestions: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: DB = Depends(get_db),
) -> dict[str, Any]:
    items = []
    for m, pf, ps in _prompt_rows(db, f):
        if category and (ps is None or ps.category != category):
            continue
        if max_specificity and (ps is None or ps.specificity > max_specificity):
            continue
        if only_suggestions and (ps is None or not ps.suggestion):
            continue
        items.append(
            {
                "message_id": m.id,
                "session_id": m.session_id,
                "timestamp": m.timestamp,
                "text": (m.text or "")[:600],
                "char_len": pf.char_len if pf else len(m.text or ""),
                "mentions_file": pf.mentions_file if pf else None,
                "specificity": ps.specificity if ps else None,
                "has_context": ps.has_context if ps else None,
                "has_success_criteria": ps.has_success_criteria if ps else None,
                "scope": ps.scope if ps else None,
                "category": ps.category if ps else None,
                "suggestion": ps.suggestion if ps else None,
            }
        )
    items.sort(key=lambda i: i["timestamp"] or 0, reverse=True)
    start = (page - 1) * page_size
    return {"total": len(items), "items": items[start : start + page_size]}


@router.get("/insights")
def insights(db: DB = Depends(get_db)) -> list[dict[str, Any]]:
    return [
        {
            "id": i.id,
            "generated_at": i.generated_at,
            "kind": i.kind,
            "title": i.title,
            "detail": i.detail,
            "n_a": i.n_a,
            "n_b": i.n_b,
        }
        for i in db.scalars(select(Insight).order_by((Insight.n_a + Insight.n_b).desc()))
    ]
