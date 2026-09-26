"""Shared formatting for MCP tool output: short, redacted Markdown."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from vibecheck.ingest.redact import Redactor

MAX_CHARS = 2000  # keeps each tool's answer small in the agent's context


def short(text: str, n: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def basename(path: str) -> str:
    return re.split(r"[\\/]", path)[-1]


def relative(path: str, root: Path) -> str:
    """``path`` relative to ``root`` when inside it, else just the file name."""
    p = path.replace("\\", "/")
    r = str(root).replace("\\", "/").rstrip("/")
    if p.lower().startswith(r.lower() + "/"):
        return p[len(r) + 1 :]
    return basename(path)


def bullets(items: Iterable[str]) -> list[str]:
    return [f"- {i}" for i in items]


def finish(text: str, redactor: Redactor) -> str:
    out = redactor.redact(text) or ""
    return out if len(out) <= MAX_CHARS else out[: MAX_CHARS - 1].rstrip() + "…"
