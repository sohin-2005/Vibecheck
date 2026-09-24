"""Adapter interface: each AI coding tool turns its own log format into parser ``Event``s."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from promptlens.config import Config
from promptlens.ingest.parser import Event

log = logging.getLogger(__name__)


class Adapter(Protocol):
    name: str
    #: True if files only ever grow by appended lines, so ingestion can resume mid-file.
    incremental: bool
    #: False for adapters built from documentation rather than real files.
    verified: bool

    def discover(self, cfg: Config, extra_dirs: list[Path]) -> list[Path]: ...

    def iter_events(
        self, path: Path, start_line: int = 0, interrupt_re: re.Pattern[str] | None = None
    ) -> Iterator[tuple[int, Event]]: ...


def json_lines(path: Path, start_line: int = 0) -> Iterator[tuple[int, dict[str, Any]]]:
    """(1-based line number, object) for well-formed JSON object lines after ``start_line``."""
    with path.open(encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, start=1):
            if n <= start_line or not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                log.warning("skipping malformed line %s:%d", path, n)
                continue
            if isinstance(obj, dict):
                yield n, obj


def added_lines_from_patch(patch: str) -> dict[str, list[str]]:
    """Added lines per file from a Codex-style ``*** Begin Patch`` block."""
    files: dict[str, list[str]] = {}
    current: str | None = None
    for line in patch.splitlines():
        m = re.match(r"\*\*\* (?:Update|Add) File: (.+)", line)
        if m:
            current = m.group(1).strip()
            files.setdefault(current, [])
        elif line.startswith("*** "):
            current = None if not line.startswith("*** Move to:") else current
        elif current and line.startswith("+"):
            files[current].append(line[1:])
    return files
