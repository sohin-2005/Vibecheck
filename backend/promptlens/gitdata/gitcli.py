"""Thin wrapper around the git CLI (argument lists only, never shell=True)."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def run_git(repo: str | Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def git_ok(repo: str | Path, *args: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True).returncode == 0


def resolve_repo_root(cwd: str) -> str | None:
    """Git top-level for a directory, or None if it isn't (or no longer is) a repo."""
    if not Path(cwd).is_dir():
        return None
    try:
        out = run_git(cwd, "rev-parse", "--show-toplevel").strip()
    except (GitError, OSError):
        return None
    return str(Path(out)) if out else None
