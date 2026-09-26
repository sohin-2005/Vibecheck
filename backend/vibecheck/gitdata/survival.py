"""Blame-based survival of AI-written lines at 1/7/30 days. See SPEC §7.9."""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DB

from vibecheck.config import Config
from vibecheck.db.models import (
    Commit,
    CommitFile,
    LineSurvival,
    Project,
    SessionCommit,
    ToolCall,
)
from vibecheck.gitdata.attribution import (
    added_lines_from_diff,
    blame_lines,
    match_ai,
    normalize,
    pool,
)
from vibecheck.gitdata.gitcli import GitError, git_ok, run_git
from vibecheck.gitdata.linker import _norm_commit_path, rel_to_repo

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
    """Blame output per (snapshot, path); many commits share a snapshot within a run."""

    def __init__(self, repo: str):
        self.repo = repo
        self._cache: dict[tuple[str, str], list[tuple[str, str]]] = {}

    def lines(self, snapshot: str, path: str) -> list[tuple[str, str]]:
        key = (snapshot, path)
        if key not in self._cache:
            try:
                out = run_git(
                    self.repo, "blame", "--porcelain", "-M", "-C", "-w", snapshot, "--", path
                )
                self._cache[key] = blame_lines(out)
            except GitError:
                self._cache[key] = []
        return self._cache[key]


def commit_ai_lines(
    db: DB, repo: str, sha: str, files: list[CommitFile]
) -> dict[str, Counter[str]] | None:
    """Per file, the commit's added lines that linked sessions' edit tools wrote.

    None when no linked session recorded any edit content (e.g. trailer-only commits).
    """
    sessions = select(SessionCommit.session_id).where(SessionCommit.commit_sha == sha)
    edits = db.execute(
        select(ToolCall.file_path, ToolCall.added_text).where(
            ToolCall.session_id.in_(sessions),
            ToolCall.added_text.is_not(None),
            ToolCall.file_path.is_not(None),
        )
    ).all()
    if not edits:
        return None
    pools: dict[str, list[str]] = {}
    for path, text in edits:
        pools.setdefault(rel_to_repo(path, repo), []).append(text)
    out: dict[str, Counter[str]] = {}
    for f in files:
        texts = pools.get(_norm_commit_path(f.file_path))
        if not texts:
            out[f.file_path] = Counter()
            continue
        diff = run_git(repo, "show", "--format=", "-U0", "--no-color", sha, "--", f.file_path)
        out[f.file_path] = match_ai(added_lines_from_diff(diff), pool(texts))
    return out


def survival_for(
    repo: str,
    sha: str,
    snapshot: str,
    files: list[CommitFile],
    cache: _BlameCache,
    ai: dict[str, Counter[str]] | None = None,
) -> tuple[int, int | None]:
    """(surviving lines, surviving edit-matched AI lines or None)."""
    renames, deleted = path_changes(repo, sha, snapshot)
    surviving = 0
    ai_surviving = 0 if ai is not None else None
    for f in files:
        if f.file_path in deleted:
            continue
        path = renames.get(f.file_path, f.file_path)
        mine = [content for s, content in cache.lines(snapshot, path) if s == sha]
        surviving += min(len(mine), f.lines_added)
        if ai is not None and ai.get(f.file_path):
            alive = Counter(n for line in mine if (n := normalize(line)))
            ai_surviving += sum((alive & ai[f.file_path]).values())  # type: ignore[operator]
    return surviving, ai_surviving


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
        files = list(db.scalars(select(CommitFile).where(CommitFile.commit_sha == c.sha)))
        due = [
            d
            for d in cfg.survival_checkpoints_days
            if (c.sha, d) not in done and c.authored_at + timedelta(days=d) <= now
        ]
        if not due or branch is None:
            continue
        try:
            ai = commit_ai_lines(db, repo, c.sha, files)
        except GitError as e:
            log.warning("edit matching failed for %s: %s", c.sha[:8], e)
            ai = None
        ai_total = sum(sum(v.values()) for v in ai.values()) if ai is not None else None
        for d in due:
            at = c.authored_at + timedelta(days=d)
            row = LineSurvival(
                commit_sha=c.sha,
                days_after=d,
                lines_total=sum(f.lines_added for f in files),
                ai_lines_total=ai_total,
                computed_at=now,
            )
            try:
                snap = run_git(repo, "rev-list", "-1", f"--before={at.isoformat()}", branch).strip()
                if not snap or not git_ok(repo, "merge-base", "--is-ancestor", c.sha, snap):
                    row.status = "not_merged"
                    row.snapshot_sha = snap or None
                else:
                    row.snapshot_sha = snap
                    row.lines_surviving, row.ai_lines_surviving = survival_for(
                        repo, c.sha, snap, files, caches[repo], ai
                    )
            except GitError as e:
                log.warning("survival failed for %s@%sd: %s", c.sha[:8], d, e)
                continue
            db.add(row)
            written += 1
        db.commit()
    return written
