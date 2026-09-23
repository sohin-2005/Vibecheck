"""Blame-based survival of AI-written lines at 1/7/30 days. See SPEC §7.9."""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DB

from promptlens.config import Config
from promptlens.db.models import Commit, CommitFile, LineSurvival, Project, SessionCommit
from promptlens.gitdata.gitcli import GitError, git_ok, run_git

log = logging.getLogger(__name__)

_HEADER = re.compile(r"^([0-9a-f]{40}) \d+ \d+")


def count_blame(porcelain: str) -> Counter[str]:
    """Lines per commit sha from ``git blame --porcelain`` output."""
    counts: Counter[str] = Counter()
    current = None
    for line in porcelain.splitlines():
        if line.startswith("\t"):
            if current:
                counts[current] += 1
            continue
        m = _HEADER.match(line)
        if m:
            current = m.group(1)
    return counts


def default_branch(repo: str) -> str | None:
    try:
        ref = run_git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()
        if ref:
            return ref.removeprefix("refs/remotes/")
    except GitError:
        pass
    for name in ("main", "master"):
        if git_ok(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
            return name
    try:
        return run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() or None
    except GitError:
        return None


def path_changes(repo: str, sha: str, snapshot: str) -> tuple[dict[str, str], set[str]]:
    """Renames (old -> new) and deletions between a commit and a snapshot."""
    out = run_git(repo, "diff", "--name-status", "-M", sha, snapshot)
    renames: dict[str, str] = {}
    deleted: set[str] = set()
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0].startswith("R") and len(parts) == 3:
            renames[parts[1]] = parts[2]
        elif parts[0] == "D" and len(parts) == 2:
            deleted.add(parts[1])
    return renames, deleted


class _BlameCache:
    def __init__(self, repo: str):
        self.repo = repo
        self._cache: dict[tuple[str, str], Counter[str]] = {}

    def get(self, snapshot: str, path: str) -> Counter[str]:
        key = (snapshot, path)
        if key not in self._cache:
            try:
                out = run_git(
                    self.repo, "blame", "--porcelain", "-M", "-C", "-w", snapshot, "--", path
                )
                self._cache[key] = count_blame(out)
            except GitError:
                self._cache[key] = Counter()
        return self._cache[key]


def survival_for(
    repo: str, sha: str, snapshot: str, files: list[CommitFile], cache: _BlameCache
) -> int:
    renames, deleted = path_changes(repo, sha, snapshot)
    surviving = 0
    for f in files:
        if f.file_path in deleted:
            continue
        path = renames.get(f.file_path, f.file_path)
        surviving += min(cache.get(snapshot, path)[sha], f.lines_added)
    return surviving


def compute_survival(cfg: Config, db: DB, now: datetime | None = None) -> int:
    """Compute missing, due checkpoints. Returns the number of rows written."""
    now = now or datetime.now(UTC)
    linked = select(SessionCommit.commit_sha)
    commits = db.scalars(
        select(Commit).where(
            Commit.is_merge.is_(False),
            or_(Commit.ai_coauthored.is_(True), Commit.sha.in_(linked)),
        )
    ).all()
    done = set(db.execute(select(LineSurvival.commit_sha, LineSurvival.days_after)).tuples())
    repos = {p.id: p.repo_root for p in db.scalars(select(Project))}
    caches: dict[str, _BlameCache] = {}
    branches: dict[str, str | None] = {}
    written = 0
    for c in commits:
        repo = repos.get(c.project_id)
        if not repo:
            continue
        if repo not in branches:
            branches[repo] = default_branch(repo)
            caches[repo] = _BlameCache(repo)
        branch = branches[repo]
        files = db.scalars(select(CommitFile).where(CommitFile.commit_sha == c.sha)).all()
        for d in cfg.survival_checkpoints_days:
            at = c.authored_at + timedelta(days=d)
            if (c.sha, d) in done or at > now or branch is None:
                continue
            row = LineSurvival(
                commit_sha=c.sha,
                days_after=d,
                lines_total=sum(f.lines_added for f in files),
                computed_at=now,
            )
            try:
                snap = run_git(repo, "rev-list", "-1", f"--before={at.isoformat()}", branch).strip()
                if not snap or not git_ok(repo, "merge-base", "--is-ancestor", c.sha, snap):
                    row.status = "not_merged"
                    row.snapshot_sha = snap or None
                else:
                    row.snapshot_sha = snap
                    row.lines_surviving = survival_for(repo, c.sha, snap, list(files), caches[repo])
            except GitError as e:
                log.warning("survival failed for %s@%sd: %s", c.sha[:8], d, e)
                continue
            db.add(row)
            written += 1
        db.commit()
    return written
