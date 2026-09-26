"""Google Antigravity: ~/.gemini/antigravity/brain/<conversation>/.system_generated/logs/.

Verified against a real ``transcript_full.jsonl`` (step_index, source, type, status,
created_at, content). Only USER_INPUT and PLANNER_RESPONSE steps have been seen; any other
step type from the model is treated as a tool step named after its type. The logs carry no
working directory or token usage, so these sessions have no project or cost.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from vibecheck.config import Config
from vibecheck.ingest.parser import DEFAULT_INTERRUPT_PATTERN, Event, ToolResult, ToolUse
from vibecheck.ingest.parser import parse_timestamp as ts
from vibecheck.sources.base import json_lines

REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)
FAILED = {"ERROR", "FAILED", "FAILURE", "CANCELED", "CANCELLED"}


class AntigravityAdapter:
    name = "antigravity"
    incremental = True
    verified = True

    def discover(self, cfg: Config, extra_dirs: list[Path]) -> list[Path]:
        out: list[Path] = []
        for d in cfg.antigravity_dirs:
            if d.exists():
                out += sorted(d.glob("*/.system_generated/logs/transcript_full.jsonl"))
        return out

    def iter_events(
        self, path: Path, start_line: int = 0, interrupt_re: re.Pattern[str] | None = None
    ) -> Iterator[tuple[int, Event]]:
        interrupt_re = interrupt_re or re.compile(DEFAULT_INTERRUPT_PATTERN)
        sid = f"antigravity:{path.parents[2].name}"
        for n, raw in json_lines(path, start_line):
            step = raw.get("step_index", n)
            kind = raw.get("type") if isinstance(raw.get("type"), str) else None
            content = raw.get("content") if isinstance(raw.get("content"), str) else ""
            ev = Event(
                kind="other",
                raw=raw,
                event_type=kind,
                session_id=sid,
                uuid=f"{sid}:{step}",
                timestamp=ts(raw.get("created_at")),
            )
            if kind == "USER_INPUT":
                m = REQUEST_RE.search(content)
                ev.text = (m.group(1) if m else content).strip()
                ev.kind = "interrupt" if interrupt_re.match(ev.text) else "human"
            elif kind == "PLANNER_RESPONSE":
                ev.kind, ev.text = "assistant", content
            elif kind and raw.get("source") == "MODEL":
                ev.kind = "assistant"
                ev.tool_uses = [ToolUse(id=ev.uuid, name=kind, command=content[:2000] or None)]
                status = str(raw.get("status", "")).upper()
                ev.tool_results = [ToolResult(tool_use_id=ev.uuid, is_error=status in FAILED)]
            yield n, ev
