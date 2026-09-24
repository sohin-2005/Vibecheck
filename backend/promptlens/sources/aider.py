"""Aider: ``.aider.chat.history.md`` in each repo.

EXPERIMENTAL: built from Aider's documented markdown history, not yet checked against real
files. "# aider chat started at <time>" starts a session, "#### " lines are your prompts,
"> " lines are Aider's status output (edits applied, token counts, commits) and everything
else is the model's reply. Only session start times are logged, so events get synthetic
one-second offsets and active time is not meaningful.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

from promptlens.config import Config
from promptlens.ingest.parser import Event, ToolUse, Usage

HISTORY = ".aider.chat.history.md"
START_RE = re.compile(r"^# aider chat started at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
TOKENS_RE = re.compile(r"Tokens: ([\d.]+)([kKmM]?) sent, ([\d.]+)([kKmM]?) received")
APPLIED_RE = re.compile(r"Applied edit to (.+)$")
COMMIT_RE = re.compile(r"^Commit ([0-9a-f]{6,40})\b")
MODEL_RE = re.compile(r"^(?:Main model|Model): (\S+)")
BLOCK_RE = re.compile(
    r"^(?P<file>[^\n`]+)\n```[^\n]*\n<<<<<<< SEARCH\n.*?\n=======\n(?P<new>.*?)\n?>>>>>>> REPLACE",
    re.DOTALL | re.MULTILINE,
)


def _tokens(num: str, unit: str) -> int:
    return int(float(num) * {"k": 1_000, "m": 1_000_000}.get(unit.lower(), 1))


class AiderAdapter:
    name = "aider"
    incremental = False
    verified = False

    def discover(self, cfg: Config, extra_dirs: list[Path]) -> list[Path]:
        seen: dict[str, Path] = {}
        for d in [*cfg.aider_dirs, *extra_dirs]:
            p = Path(d) / HISTORY
            if p.is_file():
                seen[str(p.resolve()).lower()] = p
        return list(seen.values())

    def iter_events(
        self, path: Path, start_line: int = 0, interrupt_re: re.Pattern[str] | None = None
    ) -> Iterator[tuple[int, Event]]:
        cwd = str(path.parent)
        tag = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:10]
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        sid: str | None = None
        start = datetime.now().astimezone()
        seq = resp = 0
        model = None
        reply: list[str] = []
        prompt: list[str] = []
        prompt_line = reply_line = 0
        blocks: dict[str, str] = {}  # file -> REPLACE text from the latest reply

        def event(n: int, **kw: object) -> tuple[int, Event]:
            nonlocal seq
            seq += 1
            ev = Event(
                kind="other",
                raw={"line": n, "session": sid},
                session_id=sid,
                uuid=f"{sid}:{n}:{seq}",
                timestamp=start + timedelta(seconds=seq),
                cwd=cwd,
            )
            for k, v in kw.items():
                setattr(ev, k, v)
            return n, ev

        def flush_prompt() -> Iterator[tuple[int, Event]]:
            if prompt:
                yield event(
                    prompt_line, kind="human", text="\n".join(prompt).strip(), event_type="prompt"
                )
                prompt.clear()

        def flush_reply() -> Iterator[tuple[int, Event]]:
            if any(x.strip() for x in reply):
                text = "\n".join(reply).strip()
                yield event(
                    reply_line,
                    kind="assistant",
                    text=text,
                    model=model,
                    api_message_id=f"{sid}:resp:{resp}",
                    event_type="reply",
                )
                blocks.clear()
                blocks.update(
                    {m.group("file").strip(): m.group("new") for m in BLOCK_RE.finditer(text)}
                )
            reply.clear()

        for n, line in enumerate(lines, start=1):
            m = START_RE.match(line)
            if m:
                yield from flush_prompt()
                yield from flush_reply()
                start = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").astimezone()
                sid = f"aider:{tag}:{start:%Y%m%d%H%M%S}"
                seq = resp = 0
                continue
            if sid is None:
                continue
            if line.startswith("#### "):
                yield from flush_reply()
                if not prompt:
                    prompt_line = n
                prompt.append(line[5:])
                continue
            yield from flush_prompt()
            if line.startswith("> ") or line == ">":
                yield from flush_reply()
                status = line[1:].strip()
                if mm := MODEL_RE.match(status):
                    model = mm.group(1)
                elif mm := TOKENS_RE.search(status):
                    yield event(
                        n,
                        kind="assistant",
                        text="",
                        model=model,
                        event_type="tokens",
                        api_message_id=f"{sid}:resp:{resp}",
                        usage=Usage(
                            input=_tokens(*mm.group(1, 2)), output=_tokens(*mm.group(3, 4))
                        ),
                    )
                    resp += 1
                elif mm := APPLIED_RE.search(status):
                    rel = mm.group(1).strip()
                    yield event(
                        n,
                        kind="assistant",
                        text="",
                        event_type="edit",
                        tool_uses=[
                            ToolUse(
                                id=f"{sid}:{n}",
                                name="Edit",
                                file_path=str(Path(cwd) / rel),
                                added_text=blocks.get(rel),
                            )
                        ],
                    )
                elif mm := COMMIT_RE.match(status):
                    yield event(
                        n,
                        kind="assistant",
                        text="",
                        event_type="commit",
                        tool_uses=[
                            ToolUse(
                                id=f"{sid}:{n}",
                                name="Bash",
                                command=f"git commit  # aider auto-commit {mm.group(1)}",
                            )
                        ],
                    )
                continue
            if not reply:
                reply_line = n
            reply.append(line)
        yield from flush_prompt()
        yield from flush_reply()
