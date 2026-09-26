"""Collect commits and per-file line counts from the repos sessions ran in."""

from __future__ import annotations

import fnmatch
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from vibecheck.config import Config
from vibecheck.db.models import Commit, CommitFile, Project, Session
from vibecheck.gitdata.gitcli import GitError, run_git
from vibecheck.ingest.parser import parse_timestamp

log = logging.getLogger(__name__)

TRAILER_RE = re.compile(r"co-authored-by:\s*claude", re.IGNORECASE)
_BRACE_RENAME = re.compile(r"\{([^{}]*) => ([^{}]*)\}")
REC, FLD = "\x1e", "\x1f"


def is_ignored(path: str, globs: list[str]) -> bool:
    base = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(base, g) for g in globs)


def _new_path(path: str) -> str:
    if "{" in path and " => " in path:
        return re.sub(r"//+", "/", _BRACE_RENAME.sub(lambda m: m.group(2), path))
    if " => " in path:
        return path.split(" => ", 1)[1]
    return path


def parse_numstat(out: str) -> list[tuple[str, int, int]]:
    """Parse ``git show --numstat`` output; binary files (``-``) are skipped."""
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3 or parts[0] == "-" or parts[1] == "-":
            continue
        try:
            added, deleted = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        rows.append((_new_path(parts[2]), added, deleted))
    return rows


def repo_projects(db: DB) -> dict[str, list[Project]]:
    """Projects grouped by git root (several cwds can share one repo)."""
    groups: dict[str, list[Project]] = defaultdict(list)
    for p in db.scalars(select(Project).where(Project.repo_root.is_not(None)).order_by(Project.id)):
        groups[p.repo_root].append(p)  # type: ignore[index]
    return groups


def _log_commits(repo: str, since: datetime) -> list[tuple[str, datetime, int, str]]:
    out = run_git(
        repo,
        "log",
        "--all",
        f"--since={since.isoformat()}",
        f"--format=%H{FLD}%aI{FLD}%P{FLD}%B{REC}",
    )
    commits = []
    for rec in out.split(REC):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, date, parents, body = (rec.split(FLD, 3) + ["", "", ""])[:4]
        when = parse_timestamp(date)
        if when is None:
            continue
        commits.append((sha, when, len(parents.split()), body.strip()))
    return commits


def collect_repo(db: DB, cfg: Config, repo: str, projects: list[Project]) -> int:
    ids = [p.id for p in projects]
    earliest = db.scalar(select(func.min(Session.started_at)).where(Session.project_id.in_(ids)))
    if earliest is None:
        return 0
    try:
        commits = _log_commits(repo, earliest - timedelta(days=1))
    except (GitError, OSError) as e:
        log.warning("skipping %s: %s", repo, e)
        return 0
    known = set(db.scalars(select(Commit.sha).where(Commit.sha.in_([c[0] for c in commits]))))
    new = 0
    for sha, when, n_parents, body in commits:
        if sha in known:
            continue
        files = []
        if n_parents <= 1:
            numstat = run_git(repo, "show", "--numstat", "-M", "--format=", sha)
            files = [f for f in parse_numstat(numstat) if not is_ignored(f[0], cfg.ignore_globs)]
        db.add(
            Commit(
                sha=sha,
                project_id=projects[0].id,
                authored_at=when,
                message=body,
                is_merge=n_parents > 1,
                ai_coauthored=bool(TRAILER_RE.search(body)),
                lines_added=sum(f[1] for f in files),
                lines_deleted=sum(f[2] for f in files),
            )
        )
        merged: dict[str, list[int]] = {}
        for path, a, d in files:
            m = merged.setdefault(path, [0, 0])
            m[0] += a
            m[1] += d
        for path, (a, d) in merged.items():
            db.add(CommitFile(commit_sha=sha, file_path=path, lines_added=a, lines_deleted=d))
        new += 1
    db.commit()
    return new


def collect_all(cfg: Config, db: DB) -> int:
    return sum(collect_repo(db, cfg, repo, ps) for repo, ps in repo_projects(db).items())
