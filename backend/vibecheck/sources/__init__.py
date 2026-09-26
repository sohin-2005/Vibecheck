"""Source adapters for AI coding tools."""

from __future__ import annotations

from pathlib import Path

from vibecheck.config import Config
from vibecheck.ingest.discover import SessionFile, stat_file
from vibecheck.sources.aider import AiderAdapter
from vibecheck.sources.antigravity import AntigravityAdapter
from vibecheck.sources.base import Adapter
from vibecheck.sources.claude_code import ClaudeCodeAdapter
from vibecheck.sources.codex import CodexAdapter

ADAPTERS: dict[str, Adapter] = {
    a.name: a for a in (ClaudeCodeAdapter(), AntigravityAdapter(), CodexAdapter(), AiderAdapter())
}


def discover_all(cfg: Config, extra_dirs: list[Path] | None = None) -> list[SessionFile]:
    files = []
    for name in cfg.tools:
        adapter = ADAPTERS.get(name)
        if adapter is None:
            continue
        files += [stat_file(p, name) for p in adapter.discover(cfg, extra_dirs or [])]
    return files
