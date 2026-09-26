"""Find the Claude Code session file for a project directory."""

from __future__ import annotations

import json
import re
from pathlib import Path

FIRST_LINES = 50  # cwd appears on the first user or assistant line


def encode_project_dir(path: str | Path) -> str:
    """Claude Code's folder name for a working directory: non-alphanumerics become '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def same_dir(a: str, b: str) -> bool:
    def norm(p: str) -> str:
        return p.replace("\\", "/").rstrip("/").lower()

    return bool(a) and norm(a) == norm(b)


def first_cwd(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f):
                if n >= FIRST_LINES:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("cwd"), str):
                    return obj["cwd"]
    except OSError:
        return None
    return None


def find_session_file(
    projects_dir: Path, project_dir: Path, session_id: str | None = None
) -> Path | None:
    """The newest session file for ``project_dir``, or the one named ``session_id``."""
    if not projects_dir.is_dir():
        return None
    wanted = encode_project_dir(project_dir).lower()
    folder = next(
        (d for d in projects_dir.iterdir() if d.is_dir() and d.name.lower() == wanted), None
    )
    if folder is not None:
        candidates = list(folder.glob("*.jsonl"))
    else:
        candidates = [
            p
            for p in projects_dir.rglob("*.jsonl")
            if same_dir(first_cwd(p) or "", str(project_dir))
        ]
    if session_id:
        candidates = [p for p in candidates if p.stem == session_id]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)
