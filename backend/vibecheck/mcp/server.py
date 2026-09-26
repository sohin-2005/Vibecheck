"""MCP server: the AI coding agent asks Vibecheck for feedback while it works."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DB

from vibecheck.config import Config
from vibecheck.db.session import make_sessionmaker
from vibecheck.ingest.parser import iter_events
from vibecheck.ingest.redact import Redactor
from vibecheck.mcp import lessons
from vibecheck.mcp.critique import critique_prompt
from vibecheck.mcp.live import assess, read_session, render_health
from vibecheck.mcp.locate import find_session_file
from vibecheck.mcp.render import finish

log = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Vibecheck gives feedback on how this coding session is going, from the session logs. "
    "Call project_lessons when starting a task in this repo, session_health when progress "
    "stalls (repeated edits, failing commands, the user correcting you), and critique_prompt "
    "to check an unclear request before acting on it."
)
NO_DB = (
    "No Vibecheck database found. Run `vibecheck init` and `vibecheck run` to enable "
    "project lessons and habits."
)
PG_CONNECT_TIMEOUT = 5  # seconds; a stopped Postgres must not hang the agent


def database_url(url: str) -> str | None:
    """The URL to open, or None when there is clearly no database yet."""
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        return url if path == ":memory:" or Path(path).exists() else None
    if url.startswith("postgresql") and "connect_timeout" not in url:
        return url + ("&" if "?" in url else "?") + f"connect_timeout={PG_CONNECT_TIMEOUT}"
    return url


class Feedback:
    """The tools as plain functions returning redacted Markdown. They never raise."""

    def __init__(self, cfg: Config, project_dir: Path) -> None:
        self.cfg = cfg
        self.project_dir = project_dir
        self.redactor = Redactor(cfg.redaction_enabled, cfg.redaction_extra_patterns)

    def _safe(self, what: str, fn: Callable[[], str]) -> str:
        try:
            text = fn()
        except Exception as e:  # a tool must answer, never crash the agent's call
            log.exception("%s failed", what)
            text = f"Vibecheck couldn't {what}: {type(e).__name__}."
        return finish(text, self.redactor)

    def _with_db(self, fn: Callable[[DB], str]) -> str:
        url = database_url(self.cfg.database_url)
        if url is None:
            return NO_DB
        db = make_sessionmaker(url)()
        try:
            return fn(db)
        except SQLAlchemyError:
            log.warning("database not usable", exc_info=True)
            return NO_DB
        finally:
            db.close()

    def _health(self, session_id: str | None) -> str:
        path = find_session_file(self.cfg.claude_projects_dir, self.project_dir, session_id)
        if path is None:
            return f"No Claude Code session found for {self.project_dir.name}."
        interrupt_re = re.compile(self.cfg.interrupt_pattern)
        events = (ev for _, ev in iter_events(path, interrupt_re=interrupt_re))
        s = read_session(events)
        return render_health(assess(s, self.cfg.weights, self.cfg.correction_patterns))

    def session_health(self, session_id: str | None = None) -> str:
        return self._safe("check this session", lambda: self._health(session_id))

    def project_lessons(self, days: int = 30) -> str:
        return self._safe(
            "load project lessons",
            lambda: self._with_db(lambda db: lessons.project_lessons(db, self.project_dir, days)),
        )

    def habits(self) -> str:
        return self._safe("load habits", lambda: self._with_db(lessons.habits))

    def critique_prompt(self, text: str) -> str:
        return self._safe("check the prompt", lambda: critique_prompt(text))


def build_server(cfg: Config, project_dir: Path) -> MCPServer:
    fb = Feedback(cfg, project_dir)
    server: MCPServer = MCPServer("vibecheck", instructions=INSTRUCTIONS)

    @server.tool()
    def session_health(session_id: str | None = None) -> str:
        """How the current coding session is going: repeated edits, failing commands,
        user corrections and interrupts, plus what to do next. Call it when progress stalls."""
        return fb.session_health(session_id)

    @server.tool()
    def project_lessons(days: int = 30) -> str:
        """What usually goes wrong in this repo: files that keep being re-edited, commands
        that often fail, and tips. Call it when starting a task."""
        return fb.project_lessons(days)

    @server.tool()
    def habits() -> str:
        """Prompting habits that led to better sessions across all of the user's projects
        (numbers only)."""
        return fb.habits()

    @server.tool()
    def critique_prompt(text: str) -> str:
        """Check a request for missing details (file, expected result, error text) and
        suggest a sharper version. Use it before acting on an unclear request."""
        return fb.critique_prompt(text)

    return server
