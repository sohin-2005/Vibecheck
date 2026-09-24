"""OpenAI Codex CLI: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.

EXPERIMENTAL: built from the documented rollout format, not yet checked against real files.
Each line is ``{"timestamp", "type", "payload"}`` with types session_meta, turn_context,
response_item (message / function_call / custom_tool_call / *_output) and event_msg
(token_count, turn_aborted). Unknown shapes are kept as raw events and never crash.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from promptlens.config import Config
from promptlens.ingest.parser import Event, ToolResult, ToolUse, Usage
from promptlens.ingest.parser import parse_timestamp as ts
from promptlens.sources.base import added_lines_from_patch, json_lines

META_PREFIXES = ("<environment_context>", "<user_instructions>", "<user_action>")


def _text(content: Any, kinds: tuple[str, ...]) -> str:
    if not isinstance(content, list):
        return ""
    return "\n".join(
        c["text"]
        for c in content
        if isinstance(c, dict) and c.get("type") in kinds and isinstance(c.get("text"), str)
    )


def _command(args: Any) -> list[str] | None:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    cmd = args.get("command") if isinstance(args, dict) else None
    return [str(c) for c in cmd] if isinstance(cmd, list) else None


def _is_error(output: Any) -> bool:
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return bool(re.match(r"\s*(error|failed)", output, re.IGNORECASE))
    if isinstance(output, dict):
        code = (output.get("metadata") or {}).get("exit_code")
        return code not in (0, None)
    return False


class CodexAdapter:
    name = "codex"
    incremental = False  # session id and cwd come from the first lines, so re-read whole files
    verified = False

    def discover(self, cfg: Config, extra_dirs: list[Path]) -> list[Path]:
        root = cfg.codex_dir
        return sorted(root.rglob("rollout-*.jsonl")) if root.exists() else []

    def iter_events(
        self, path: Path, start_line: int = 0, interrupt_re: re.Pattern[str] | None = None
    ) -> Iterator[tuple[int, Event]]:
        sid = f"codex:{path.stem}"
        cwd = branch = version = model = None
        calls = 0
        patch_ids: dict[str, list[str]] = {}
        for n, raw in json_lines(path):
            kind = raw.get("type")
            p = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
            if kind == "session_meta":
                sid = f"codex:{p.get('id') or path.stem}"
                cwd = p.get("cwd") or cwd
                branch = (
                    (p.get("git") or {}).get("branch") if isinstance(p.get("git"), dict) else branch
                )
                version = p.get("cli_version") or version
            elif kind == "turn_context":
                cwd = p.get("cwd") or cwd
                model = p.get("model") or model
            ev = Event(
                kind="other",
                raw=raw,
                event_type=f"{kind}:{p.get('type')}" if p.get("type") else kind,
                session_id=sid,
                uuid=f"{sid}:{n}",
                timestamp=ts(raw.get("timestamp")),
                cwd=cwd,
                git_branch=branch,
                version=version,
            )
            ptype = p.get("type")
            if kind == "response_item" and ptype == "message":
                if p.get("role") == "user":
                    ev.text = _text(p.get("content"), ("input_text", "text")).strip()
                    ev.kind = (
                        "user_meta" if ev.text.startswith(META_PREFIXES) or not ev.text else "human"
                    )
                elif p.get("role") == "assistant":
                    ev.kind, ev.model = "assistant", model
                    ev.text = _text(p.get("content"), ("output_text", "text"))
                    ev.api_message_id = f"{sid}:call:{calls}"
            elif kind == "response_item" and ptype in ("function_call", "custom_tool_call"):
                ev.kind, ev.model, ev.api_message_id = "assistant", model, f"{sid}:call:{calls}"
                call_id = str(p.get("call_id") or ev.uuid)
                name = str(p.get("name") or "tool")
                cmd = _command(p.get("arguments"))
                patch = p.get("input") if isinstance(p.get("input"), str) else None
                if cmd and cmd[0] == "apply_patch" and len(cmd) > 1:
                    name, patch = "apply_patch", cmd[1]
                if patch and "*** Begin Patch" in patch:
                    files = added_lines_from_patch(patch) or {None: []}
                    ids = [call_id if i == 0 else f"{call_id}#{i}" for i in range(len(files))]
                    patch_ids[call_id] = ids
                    ev.tool_uses = [
                        ToolUse(
                            id=i,
                            name="apply_patch",
                            file_path=f,
                            added_text="\n".join(lines) or None,
                        )
                        for i, (f, lines) in zip(ids, files.items(), strict=True)
                    ]
                else:
                    command = (
                        cmd[-1] if cmd and cmd[:2] in (["bash", "-lc"], ["bash", "-c"]) else None
                    )
                    ev.tool_uses = [
                        ToolUse(
                            id=call_id,
                            name=name,
                            command=command or (" ".join(cmd) if cmd else None),
                        )
                    ]
            elif kind == "response_item" and ptype in (
                "function_call_output",
                "custom_tool_call_output",
            ):
                call_id = str(p.get("call_id"))
                err = _is_error(p.get("output"))
                ev.tool_results = [
                    ToolResult(tool_use_id=i, is_error=err)
                    for i in patch_ids.get(call_id, [call_id])
                ]
                ev.kind = "tool_result"
            elif kind == "event_msg" and ptype == "token_count":
                info = p.get("info") if isinstance(p.get("info"), dict) else {}
                last = (
                    info.get("last_token_usage")
                    if isinstance(info.get("last_token_usage"), dict)
                    else None
                )
                if last:
                    cached = int(last.get("cached_input_tokens") or 0)
                    ev.kind, ev.model, ev.text = "assistant", model, ""
                    ev.api_message_id = f"{sid}:call:{calls}"
                    ev.usage = Usage(
                        input=max(0, int(last.get("input_tokens") or 0) - cached),
                        output=int(last.get("output_tokens") or 0),
                        cache_read=cached,
                    )
                    calls += 1
            elif kind == "event_msg" and ptype == "turn_aborted":
                ev.kind, ev.text = "interrupt", "[turn aborted]"
            yield n, ev
