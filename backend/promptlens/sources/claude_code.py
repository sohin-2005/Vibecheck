"""Claude Code: ~/.claude/projects/<encoded-cwd>/<session>.jsonl (verified; see FORMAT_NOTES)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from promptlens.config import Config
from promptlens.ingest.parser import Event, iter_events


class ClaudeCodeAdapter:
    name = "claude-code"
    incremental = True
    verified = True

    def discover(self, cfg: Config, extra_dirs: list[Path]) -> list[Path]:
        root = cfg.claude_projects_dir
        return sorted(root.rglob("*.jsonl")) if root.exists() else []

    def iter_events(
        self, path: Path, start_line: int = 0, interrupt_re: re.Pattern[str] | None = None
    ) -> Iterator[tuple[int, Event]]:
        return iter_events(path, start_line=start_line, interrupt_re=interrupt_re)
