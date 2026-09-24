"""Source adapters for AI coding tools."""

from __future__ import annotations

from pathlib import Path

from promptlens.config import Config
from promptlens.ingest.discover import SessionFile, stat_file
from promptlens.sources.aider import AiderAdapter
from promptlens.sources.antigravity import AntigravityAdapter
from promptlens.sources.base import Adapter
from promptlens.sources.claude_code import ClaudeCodeAdapter
from promptlens.sources.codex import CodexAdapter

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
