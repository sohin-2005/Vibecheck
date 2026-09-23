"""Find session JSONL files and decide which need (re)processing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from promptlens.db.models import IngestState


@dataclass(frozen=True)
class SessionFile:
    path: Path
    size: int
    mtime: datetime


def discover_files(root: Path) -> list[SessionFile]:
    if not root.exists():
        return []
    out = []
    for p in sorted(root.rglob("*.jsonl")):
        st = p.stat()
        out.append(SessionFile(p, st.st_size, datetime.fromtimestamp(st.st_mtime, UTC)))
    return out


def plan_file(f: SessionFile, state: IngestState | None) -> int | None:
    """Return the line offset to resume from, or None if the file is unchanged.

    0 means process from scratch (new file, or it shrank / went back in time).
    """
    if state is None:
        return 0
    if f.size == state.file_size and f.mtime == state.mtime:
        return None
    if f.size < state.file_size or f.mtime < state.mtime:
        return 0
    return state.lines_processed
