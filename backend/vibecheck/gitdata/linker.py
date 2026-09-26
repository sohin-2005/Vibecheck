"""Link sessions to the commits they produced. See SPEC §7.6."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as DB

from vibecheck.config import Config
from vibecheck.db.models import Commit, CommitFile, Message, Session, SessionCommit, ToolCall
from vibecheck.gitdata.collector import repo_projects
from vibecheck.ingest.parser import EDIT_TOOLS

BASH_WINDOW = timedelta(minutes=2)
BASH_SLACK = timedelta(seconds=5)  # clocks and second-resolution author dates
CONFIDENCE = {"bash_commit": 0.95, "trailer": 0.9, "timestamp": 0.5}


@dataclass(frozen=True)
class Candidate:
    session_id: str
    sha: str
    method: str
    distance: float  # seconds between session activity and commit

    @property
    def confidence(self) -> float:
        return CONFIDENCE[self.method]


def rel_to_repo(file_path: str, repo_root: str) -> str:
    """Normalize a session file path to a repo-relative, comparable path."""
    root = os.path.normcase(os.path.normpath(repo_root))
    p = os.path.normcase(os.path.normpath(file_path))
    if p.startswith(root + os.sep):
        p = p[len(root) + 1 :]
    return p.replace("\\", "/")


def _norm_commit_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)).replace("\\", "/")


def session_candidates(
    session: Session,
    commits: list[Commit],
    commit_files: dict[str, set[str]],
    bash_times: list[datetime],
    edited: set[str],
    window: timedelta,
) -> list[Candidate]:
    if session.started_at is None or session.ended_at is None:
        return []
    start, end = session.started_at, session.ended_at + window
    out = []
    for c in commits:
        t = c.authored_at
        if c.is_merge:
            continue
        after = [t - b for b in bash_times if -BASH_SLACK <= t - b <= BASH_WINDOW]
        if after:
            out.append(Candidate(session.id, c.sha, "bash_commit", min(after).total_seconds()))
        elif not start <= t <= end:
            continue
        elif c.ai_coauthored:
            out.append(
                Candidate(session.id, c.sha, "trailer", (t - session.ended_at).total_seconds())
            )
        elif edited & commit_files.get(c.sha, set()):
            out.append(
                Candidate(session.id, c.sha, "timestamp", (t - session.ended_at).total_seconds())
            )
    return out


def choose_links(cands: list[Candidate]) -> list[Candidate]:
    """One session per commit: highest confidence, then closest in time."""
    best: dict[str, Candidate] = {}
    for c in cands:
        cur = best.get(c.sha)
        if cur is None or (-c.confidence, abs(c.distance)) < (-cur.confidence, abs(cur.distance)):
            best[c.sha] = c
    return list(best.values())


def link_all(cfg: Config, db: DB) -> int:
    window = timedelta(minutes=cfg.commit_link_window_minutes)
    chosen: list[Candidate] = []
    for repo, projects in repo_projects(db).items():
        pids = [p.id for p in projects]
        sessions = db.scalars(select(Session).where(Session.project_id.in_(pids))).all()
        commits = db.scalars(select(Commit).where(Commit.project_id == projects[0].id)).all()
        files: dict[str, set[str]] = {}
        for sha, path in db.execute(
            select(CommitFile.commit_sha, CommitFile.file_path).where(
                CommitFile.commit_sha.in_([c.sha for c in commits])
            )
        ):
            files.setdefault(sha, set()).add(_norm_commit_path(path))
        cands: list[Candidate] = []
        for s in sessions:
            tools = db.execute(
                select(
                    ToolCall.tool_name, ToolCall.command, ToolCall.file_path, ToolCall.timestamp
                ).where(ToolCall.session_id == s.id)
            ).all()
            bash = [
                t.timestamp
                for t in tools
                if t.command and "git commit" in t.command and t.timestamp
            ]
            edited = {
                rel_to_repo(t.file_path, repo)
                for t in tools
                if t.tool_name in EDIT_TOOLS and t.file_path
            }
            cands += session_candidates(s, list(commits), files, bash, edited, window)
        chosen += choose_links(cands)

    db.execute(delete(SessionCommit))
    for c in chosen:
        db.add(
            SessionCommit(
                session_id=c.session_id,
                commit_sha=c.sha,
                link_method=c.method,
                confidence=Decimal(str(c.confidence)),
            )
        )
    db.flush()
    _update_session_commit_fields(db)
    db.commit()
    return len(chosen)


def _update_session_commit_fields(db: DB) -> None:
    first_commit: dict[str, datetime] = {}
    for sid, when in db.execute(
        select(SessionCommit.session_id, Commit.authored_at).join(
            Commit, Commit.sha == SessionCommit.commit_sha
        )
    ):
        if sid not in first_commit or when < first_commit[sid]:
            first_commit[sid] = when
    db.execute(update(Session).values(has_commit=False, turns_to_commit=None))
    for sid, when in first_commit.items():
        prompts = db.scalars(
            select(Message.timestamp).where(
                Message.session_id == sid, Message.is_human_prompt.is_(True)
            )
        ).all()
        turns = sum(1 for t in prompts if t is not None and t <= when)
        db.execute(
            update(Session).where(Session.id == sid).values(has_commit=True, turns_to_commit=turns)
        )
