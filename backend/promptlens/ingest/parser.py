"""Tolerant parser for Claude Code session JSONL files. See docs/FORMAT_NOTES.md.

The parser never raises on unexpected shapes: anything it doesn't understand
becomes an ``Event`` of kind ``"other"`` and is still kept as raw JSON.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

Kind = Literal["human", "interrupt", "user_meta", "tool_result", "assistant", "other"]

DEFAULT_INTERRUPT_PATTERN = r"\[Request interrupted by user"
META_PREFIXES = ("<task-notification>", "<command-", "<local-command-", "<system-reminder>")
FILE_PATH_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}
COMMAND_TOOLS = {"Bash", "PowerShell"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class ToolUse:
    id: str
    name: str
    file_path: str | None = None
    command: str | None = None
    added_text: str | None = None  # code this call wrote, for edit-matched attribution


@dataclass
class ToolResult:
    tool_use_id: str
    is_error: bool | None = None


@dataclass
class Event:
    kind: Kind
    raw: dict[str, Any]
    event_type: str | None = None
    session_id: str | None = None
    uuid: str | None = None
    timestamp: datetime | None = None
    cwd: str | None = None
    git_branch: str | None = None
    version: str | None = None
    is_sidechain: bool = False
    text: str | None = None
    model: str | None = None
    api_message_id: str | None = None
    usage: Usage | None = None
    tool_uses: list[ToolUse] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    title: str | None = None


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None


def _int(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def parse_timestamp(v: Any) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _text_of(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        b["text"] for b in blocks if b.get("type") == "text" and isinstance(b.get("text"), str)
    )


def _parse_usage(u: Any) -> Usage | None:
    if not isinstance(u, dict):
        return None
    return Usage(
        input=_int(u.get("input_tokens")),
        output=_int(u.get("output_tokens")),
        cache_write=_int(u.get("cache_creation_input_tokens")),
        cache_read=_int(u.get("cache_read_input_tokens")),
    )


def _parse_tool_use(b: dict[str, Any]) -> ToolUse | None:
    tid, name = _str(b.get("id")), _str(b.get("name"))
    if not tid or not name:
        return None
    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
    tu = ToolUse(id=tid, name=name)
    if name in FILE_PATH_TOOLS:
        tu.file_path = _str(inp.get("file_path")) or _str(inp.get("notebook_path"))
    if name in COMMAND_TOOLS:
        tu.command = _str(inp.get("command"))
    tu.added_text = _added_text(name, inp)
    return tu


def _added_text(name: str, inp: dict[str, Any]) -> str | None:
    if name == "Edit":
        return _str(inp.get("new_string"))
    if name == "Write":
        return _str(inp.get("content"))
    if name == "NotebookEdit":
        return _str(inp.get("new_source"))
    if name == "MultiEdit" and isinstance(inp.get("edits"), list):
        parts = [e.get("new_string") for e in inp["edits"] if isinstance(e, dict)]
        return "\n".join(p for p in parts if isinstance(p, str)) or None
    return None


def _classify_user(
    raw: dict[str, Any], blocks: list[dict[str, Any]], interrupt_re: re.Pattern[str]
) -> tuple[Kind, str, list[ToolResult]]:
    results = [
        ToolResult(tool_use_id=b["tool_use_id"], is_error=bool(b.get("is_error", False)))
        for b in blocks
        if b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str)
    ]
    text = _text_of(blocks)
    if results or "toolUseResult" in raw or any(b.get("type") == "tool_result" for b in blocks):
        return "tool_result", text, results
    if interrupt_re.match(text.strip()):
        return "interrupt", text, results
    origin = raw.get("origin")
    origin_kind = origin.get("kind") if isinstance(origin, dict) else None
    if (
        raw.get("isMeta")
        or (origin_kind is not None and origin_kind != "human")
        or text.lstrip().startswith(META_PREFIXES)
        or not text.strip()
    ):
        return "user_meta", text, results
    return "human", text, results


def parse_event(raw: dict[str, Any], interrupt_re: re.Pattern[str] | None = None) -> Event:
    interrupt_re = interrupt_re or re.compile(DEFAULT_INTERRUPT_PATTERN)
    etype = raw.get("type") if isinstance(raw.get("type"), str) else None
    ev = Event(
        kind="other",
        raw=raw,
        event_type=etype,
        session_id=_str(raw.get("sessionId")),
        uuid=_str(raw.get("uuid")),
        timestamp=parse_timestamp(raw.get("timestamp")),
        cwd=_str(raw.get("cwd")),
        git_branch=_str(raw.get("gitBranch")),
        version=_str(raw.get("version")),
        is_sidechain=raw.get("isSidechain") is True,
        title=_str(raw.get("customTitle")) or _str(raw.get("aiTitle")),
    )
    msg = raw.get("message") if isinstance(raw.get("message"), dict) else None
    if msg is None or etype not in ("user", "assistant"):
        return ev
    blocks = _blocks(msg.get("content"))
    if etype == "user":
        ev.kind, ev.text, ev.tool_results = _classify_user(raw, blocks, interrupt_re)
    else:
        ev.kind = "assistant"
        ev.text = _text_of(blocks)
        ev.model = _str(msg.get("model"))
        ev.api_message_id = _str(msg.get("id"))
        ev.usage = _parse_usage(msg.get("usage"))
        ev.tool_uses = [
            tu for b in blocks if b.get("type") == "tool_use" if (tu := _parse_tool_use(b))
        ]
    return ev


def parse_line(line: str, interrupt_re: re.Pattern[str] | None = None) -> Event | None:
    """Parse one JSONL line. Returns None for blank, malformed or non-object lines."""
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return parse_event(raw, interrupt_re)
    except Exception:  # defensive: the parser must never crash ingestion
        log.exception("unexpected error parsing event; keeping as other")
        return Event(kind="other", raw=raw)


def iter_events(
    path: Path, start_line: int = 0, interrupt_re: re.Pattern[str] | None = None
) -> Iterator[tuple[int, Event]]:
    """Yield (1-based line number, event) for lines after ``start_line``."""
    with path.open(encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, start=1):
            if n <= start_line:
                continue
            ev = parse_line(line, interrupt_re)
            if ev is None:
                if line.strip():
                    log.warning("skipping malformed line %s:%d", path, n)
                continue
            yield n, ev


def count_lines(path: Path) -> int:
    with path.open("rb") as f:
        return sum(1 for _ in f)


def summarize(paths: Iterable[Path]) -> dict[str, Any]:
    """Event counts across files, for the Phase 1 "zero crashes" check."""
    kinds: Counter[str] = Counter()
    types: Counter[str] = Counter()
    files = malformed = 0
    for p in paths:
        files += 1
        with p.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                ev = parse_line(line)
                if ev is None:
                    malformed += 1
                    continue
                kinds[ev.kind] += 1
                types[ev.event_type or "?"] += 1
    return {
        "files": files,
        "malformed_lines": malformed,
        "kinds": dict(kinds),
        "types": dict(types),
    }
