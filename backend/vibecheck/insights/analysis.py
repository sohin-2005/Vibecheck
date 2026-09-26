"""Group comparisons between first-prompt habits and session outcomes. See SPEC §7.12.

Rules: medians (rates for booleans), at least MIN_GROUP sessions per group, always report n,
and phrase results as correlations, never as causes.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DB

from vibecheck.coach.rubric import RUBRIC_VERSION
from vibecheck.db.models import (
    Commit,
    Insight,
    LineSurvival,
    Message,
    PromptFeatures,
    PromptScore,
    Session,
    SessionCommit,
)

MIN_GROUP = 10


@dataclass
class SessionRow:
    session_id: str
    mentions_file: bool
    has_context: bool | None
    has_error_text: bool
    category: str | None
    scope: str | None
    specificity: int | None
    turns_to_commit: int | None
    struggle_score: float | None
    survival_7d: float | None
    has_commit: bool


@dataclass
class Found:
    kind: str
    title: str
    detail: dict[str, Any]
    n_a: int
    n_b: int


Pred = Callable[[SessionRow], bool | None]  # None = not in either group


@dataclass(frozen=True)
class Comparison:
    key: str
    describe: str  # completes "Sessions where your first prompt ..."
    group: Pred


COMPARISONS = [
    Comparison(
        "has_context",
        "included context (files, errors or code)",
        lambda r: r.has_context,
    ),
    Comparison("mentions_file", "referenced a specific file", lambda r: r.mentions_file),
    Comparison(
        "has_error_text",
        "included the error text (bugfix sessions)",
        lambda r: r.has_error_text if r.category == "bugfix" else None,
    ),
    Comparison(
        "scope",
        "was small or medium in scope (not too large)",
        lambda r: None if r.scope is None else r.scope != "too_large",
    ),
    Comparison(
        "specificity",
        "was specific (4-5 out of 5, vs 1-2)",
        lambda r: None if r.specificity is None or r.specificity == 3 else r.specificity >= 4,
    ),
]

OUTCOMES: dict[str, tuple[Callable[[SessionRow], Any], str, bool]] = {
    # name: (getter, phrase template, lower_is_better)
    "turns_to_commit": (
        lambda r: r.turns_to_commit,
        "a median of {a} turns to commit vs {b}",
        True,
    ),
    "struggle_score": (lambda r: r.struggle_score, "a median struggle score of {a} vs {b}", True),
    "survival_7d": (
        lambda r: r.survival_7d,
        "a median 7-day code survival of {a}% vs {b}%",
        False,
    ),
    "has_commit": (lambda r: r.has_commit, "{a}% ended in a commit vs {b}%", False),
}


def _fmt(x: float) -> str:
    return f"{x:g}" if float(x).is_integer() else f"{x:.1f}"


def median_diff_ci(
    a: list[float], b: list[float], n_boot: int = 1000, seed: int = 7
) -> tuple[float, float]:
    """95% bootstrap interval for median(a) - median(b)."""
    rng = random.Random(seed)
    diffs = sorted(
        statistics.median(rng.choices(a, k=len(a))) - statistics.median(rng.choices(b, k=len(b)))
        for _ in range(n_boot)
    )
    return diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot) - 1]


def compare_groups(rows: list[SessionRow]) -> list[Found]:
    found = []
    for comp in COMPARISONS:
        for name, (get, phrase, lower_better) in OUTCOMES.items():
            a_rows, b_rows = [], []
            for r in rows:
                g = comp.group(r)
                v = get(r)
                if g is None or v is None:
                    continue
                (a_rows if g else b_rows).append(v)
            if len(a_rows) < MIN_GROUP or len(b_rows) < MIN_GROUP:
                continue
            detail: dict[str, Any] = {"outcome": name, "comparison": comp.key}
            if name == "has_commit":
                va = round(100 * sum(a_rows) / len(a_rows), 1)
                vb = round(100 * sum(b_rows) / len(b_rows), 1)
                detail.update(rate_a=va, rate_b=vb)
            else:
                va = round(statistics.median(a_rows), 2)
                vb = round(statistics.median(b_rows), 2)
                lo, hi = median_diff_ci([float(x) for x in a_rows], [float(x) for x in b_rows])
                detail.update(median_a=va, median_b=vb, ci95_diff=[round(lo, 2), round(hi, 2)])
            if va == vb:
                continue
            detail["a_is_better"] = (va < vb) == lower_better
            title = (
                f"Sessions where your first prompt {comp.describe} had "
                f"{phrase.format(a=_fmt(va), b=_fmt(vb))} otherwise "
                f"(n={len(a_rows)} vs n={len(b_rows)})."
            )
            found.append(Found(f"{comp.key}:{name}", title, detail, len(a_rows), len(b_rows)))
    return found


def load_rows(db: DB) -> list[SessionRow]:
    first: dict[str, int] = {}
    for mid, sid in db.execute(
        select(PromptFeatures.message_id, Message.session_id)
        .join(Message, Message.id == PromptFeatures.message_id)
        .where(PromptFeatures.is_first_in_session.is_(True))
    ):
        first[sid] = mid
    feats = {f.message_id: f for f in db.scalars(select(PromptFeatures))}
    scores = {
        s.message_id: s
        for s in db.scalars(select(PromptScore).where(PromptScore.rubric_version == RUBRIC_VERSION))
    }
    surv: dict[str, list[tuple[int, int]]] = {}
    for sid, total, alive in db.execute(
        select(SessionCommit.session_id, LineSurvival.lines_total, LineSurvival.lines_surviving)
        .join(Commit, Commit.sha == SessionCommit.commit_sha)
        .join(LineSurvival, LineSurvival.commit_sha == Commit.sha)
        .where(LineSurvival.days_after == 7, LineSurvival.status == "ok")
    ):
        surv.setdefault(sid, []).append((total, alive))

    rows = []
    for s in db.scalars(select(Session)):
        mid = first.get(s.id)
        if mid is None:
            continue
        f, sc = feats[mid], scores.get(mid)
        rule_context = f.mentions_file or f.has_error_text or f.has_code_block
        pairs = surv.get(s.id, [])
        total = sum(t for t, _ in pairs)
        rows.append(
            SessionRow(
                session_id=s.id,
                mentions_file=f.mentions_file,
                has_context=sc.has_context if sc else rule_context,
                has_error_text=f.has_error_text,
                category=sc.category if sc else None,
                scope=sc.scope if sc else None,
                specificity=sc.specificity if sc else None,
                turns_to_commit=s.turns_to_commit,
                struggle_score=float(s.struggle_score) if s.struggle_score is not None else None,
                survival_7d=round(100 * sum(a for _, a in pairs) / total, 1) if total else None,
                has_commit=s.has_commit,
            )
        )
    return rows


def compute_insights(db: DB) -> list[Found]:
    found = compare_groups(load_rows(db))
    now = datetime.now(UTC)
    db.execute(delete(Insight))
    for f in found:
        db.add(
            Insight(
                generated_at=now, kind=f.kind, title=f.title, detail=f.detail, n_a=f.n_a, n_b=f.n_b
            )
        )
    db.commit()
    return found
