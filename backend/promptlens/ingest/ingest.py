"""Incremental, idempotent loading of session files into the database."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DB

from promptlens.config import Config
from promptlens.db.models import IngestState, Message, Project, RawEvent, Session, ToolCall
from promptlens.db.upsert import upsert
from promptlens.gitdata.gitcli import resolve_repo_root
from promptlens.ingest.discover import SessionFile, plan_file
from promptlens.ingest.parser import Event
from promptlens.ingest.redact import Redactor
from promptlens.metrics.session_metrics import recompute_session
from promptlens.sources import ADAPTERS, discover_all

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    files_seen: int = 0
    files_processed: int = 0
    lines_processed: int = 0
    sessions_touched: set[str] = field(default_factory=set)


def project_name(path: str) -> str:
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1] or path


def complete_line_count(path: Path) -> int:
    """Lines terminated by a newline; a trailing partial line is still being written."""
    with path.open("rb") as f:
        return f.read().count(b"\n")


class _FileLoader:
    def __init__(
        self, db: DB, cfg: Config, redactor: Redactor, projects: dict[str, int], tool: str
    ):
        self.db, self.cfg, self.redactor, self.projects = db, cfg, redactor, projects
        self.tool = tool
        self.interrupt_re = re.compile(cfg.interrupt_pattern)
        self.sessions: dict[str, dict[str, Any]] = {}
        self.raw: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.tools: list[dict[str, Any]] = []
        self.results: dict[str, bool] = {}
        self.skipped_sessions: set[str] = set()

    def project_id(self, cwd: str) -> int | None:
        if any(p and p in cwd for p in self.cfg.ignore_projects):
            return None
        if cwd not in self.projects:
            root = resolve_repo_root(cwd)
            p = Project(cwd=cwd, repo_root=root, name=project_name(root or cwd))
            self.db.add(p)
            self.db.flush()
            self.projects[cwd] = p.id
        return self.projects[cwd]

    def add(self, path: Path, line_no: int, ev: Event, fallback_sid: str) -> None:
        sid = ev.session_id or fallback_sid
        if sid in self.skipped_sessions:
            return
        info = self.sessions.setdefault(sid, {"tool": self.tool})
        if ev.cwd and "project_id" not in info:
            pid = self.project_id(ev.cwd)
            if pid is None:
                self.skipped_sessions.add(sid)
                self.sessions.pop(sid)
                return
            info["project_id"] = pid
        if ev.title:
            info["title"] = self.redactor.redact(ev.title)
        if ev.git_branch:
            info["git_branch"] = ev.git_branch
        if ev.version:
            info["cc_version"] = ev.version

        self.raw.append(
            {
                "session_id": sid,
                "file_path": str(path),
                "line_no": line_no,
                "event_uuid": ev.uuid,
                "event_type": ev.event_type,
                "timestamp": ev.timestamp,
                "payload": self.redactor.redact_json(ev.raw),
            }
        )
        if ev.is_sidechain and not self.cfg.include_sidechains:
            return
        for tr in ev.tool_results:
            self.results[tr.tool_use_id] = bool(tr.is_error)
        if ev.kind in ("human", "interrupt", "assistant") and ev.uuid:
            u = ev.usage
            self.messages.append(
                {
                    "session_id": sid,
                    "event_uuid": ev.uuid,
                    "role": "assistant" if ev.kind == "assistant" else "user",
                    "is_human_prompt": ev.kind == "human",
                    "is_interrupt": ev.kind == "interrupt",
                    "is_sidechain": ev.is_sidechain,
                    "timestamp": ev.timestamp,
                    "text": self.redactor.redact(ev.text),
                    "model": ev.model,
                    "api_message_id": ev.api_message_id,
                    "input_tokens": u.input if u else 0,
                    "output_tokens": u.output if u else 0,
                    "cache_write_tokens": u.cache_write if u else 0,
                    "cache_read_tokens": u.cache_read if u else 0,
                }
            )
        for tu in ev.tool_uses:
            self.tools.append(
                {
                    "session_id": sid,
                    "tool_use_id": tu.id,
                    "tool_name": tu.name,
                    "file_path": tu.file_path,
                    "command": self.redactor.redact(tu.command),
                    "added_text": self.redactor.redact(tu.added_text),
                    "is_error": None,
                    "is_sidechain": ev.is_sidechain,
                    "timestamp": ev.timestamp,
                }
            )

    def flush(self) -> None:
        db = self.db
        existing = set(
            db.scalars(select(Session.id).where(Session.id.in_(list(self.sessions)))).all()
        )
        for sid, info in self.sessions.items():
            if sid in existing:
                if info:
                    db.execute(update(Session).where(Session.id == sid).values(**info))
            else:
                db.add(Session(id=sid, models=[], **info))
        db.flush()
        keep = set(self.sessions)
        self.raw = [r for r in self.raw if r["session_id"] in keep]
        self.messages = [m for m in self.messages if m["session_id"] in keep]
        self.tools = [t for t in self.tools if t["session_id"] in keep]
        upsert(
            db,
            RawEvent,
            self.raw,
            keys=["file_path", "line_no"],
            update=["session_id", "event_uuid", "event_type", "timestamp", "payload"],
        )
        msg_cols = [c for c in self.messages[0] if c != "event_uuid"] if self.messages else []
        upsert(db, Message, self.messages, keys=["event_uuid"], update=msg_cols)
        for t in self.tools:
            if t["tool_use_id"] in self.results:
                t["is_error"] = self.results.pop(t["tool_use_id"])
        tool_cols = [
            "tool_name",
            "file_path",
            "command",
            "added_text",
            "is_error",
            "is_sidechain",
            "timestamp",
        ]
        upsert(db, ToolCall, self.tools, keys=["tool_use_id"], update=tool_cols)
        # results whose tool_use arrived in an earlier run
        for flag in (True, False):
            ids = [k for k, v in self.results.items() if v is flag]
            if ids:
                db.execute(
                    update(ToolCall).where(ToolCall.tool_use_id.in_(ids)).values(is_error=flag)
                )


def ingest_file(
    db: DB, cfg: Config, f: SessionFile, start: int, projects: dict[str, int]
) -> tuple[int, set[str]]:
    adapter = ADAPTERS[f.tool]
    loader = _FileLoader(
        db, cfg, Redactor(cfg.redaction_enabled, cfg.redaction_extra_patterns), projects, f.tool
    )
    # JSONL tools may have a partial last line still being written; others are read whole.
    end = complete_line_count(f.path) if adapter.incremental else 10**12
    for n, ev in adapter.iter_events(f.path, start_line=start, interrupt_re=loader.interrupt_re):
        if n > end:
            break
        loader.add(f.path, n, ev, fallback_sid=f.path.stem)
    loader.flush()
    upsert(
        db,
        IngestState,
        [
            {
                "file_path": str(f.path),
                "file_size": f.size,
                "mtime": f.mtime,
                "lines_processed": min(end, complete_line_count(f.path)),
                "updated_at": datetime.now(UTC),
            }
        ],
        keys=["file_path"],
        update=["file_size", "mtime", "lines_processed", "updated_at"],
    )
    return min(end, complete_line_count(f.path)) - start, set(loader.sessions)


def ingest_all(cfg: Config, db: DB, progress: Any = None) -> IngestResult:
    res = IngestResult()
    projects = {p.cwd: p.id for p in db.scalars(select(Project))}
    repo_dirs = [Path(r) for r in {p.repo_root for p in db.scalars(select(Project)) if p.repo_root}]
    files = discover_all(cfg, repo_dirs)
    res.files_seen = len(files)
    states = {s.file_path: s for s in db.scalars(select(IngestState))}
    for f in files:
        start = plan_file(f, states.get(str(f.path)), ADAPTERS[f.tool].incremental)
        if start is None:
            continue
        try:
            lines, sessions = ingest_file(db, cfg, f, start, projects)
            for sid in sessions:
                recompute_session(db, sid, cfg)
            db.commit()
        except Exception:
            db.rollback()
            projects.clear()
            projects.update({p.cwd: p.id for p in db.scalars(select(Project))})
            log.exception("failed to ingest %s", f.path)
            continue
        res.files_processed += 1
        res.lines_processed += lines
        res.sessions_touched |= sessions
        if progress:
            progress(f.path)
    return res
