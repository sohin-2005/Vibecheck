# Vibecheck MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `vibecheck mcp`, a stdio MCP server whose four tools (`session_health`, `project_lessons`, `habits`, `critique_prompt`) let the AI coding agent ask Vibecheck for feedback while it works.

**Architecture:** A new `backend/vibecheck/mcp/` package of small pure modules: `locate` (find the live session file), `live` (session events → struggle findings), `critique` (one prompt → gaps + rewrite), `lessons` (database → project lessons and habit numbers), `render` (shared formatting, redaction, length cap). `server.py` wraps them in a `Feedback` class that never raises and registers them on an `mcp` 2.x `MCPServer`. The CLI gains an `mcp` command.

**Tech Stack:** Python 3.11, `mcp` 2.x (`from mcp.server.mcpserver import MCPServer`; `FastMCP` was renamed in 2.0), SQLAlchemy 2.0, Typer, pytest, anyio (comes with `mcp`).

**Spec:** `docs/superpowers/specs/2026-09-26-mcp-server-design.md`

## Global Constraints

- Every tool returns a short Markdown string, capped at 2,000 characters, passed through `Redactor` before it is returned.
- No tool raises: a failure comes back as a one-line explanation.
- File names, commands and prompt snippets come from the current project only; `habits` returns numbers-only insight titles.
- Paths are shown as basenames or relative to the project root, never absolute.
- The server writes nothing and makes no network calls (the only connection is to the configured database).
- Logging goes to stderr; stdout carries the MCP protocol, so nothing else may print to stdout during `vibecheck mcp`.
- Live struggle headline when the weighted raw score is at least 6, or any single file has been edited more than 5 times.
- `project_lessons` window defaults to 30 days.
- Dependency: `mcp>=2.2,<3`; no other new dependencies.
- Line length 100 (ruff). Type hints everywhere. Every new module gets tests. Run `.venv/Scripts/ruff.exe format` on the files a task creates before `ruff format --check .`.
- `uv` is not installed on this machine: run tools as `.venv/Scripts/python.exe -m pytest`, `.venv/Scripts/ruff.exe`, from `backend/`. Commit messages carry no AI attribution trailers.

## Review Focus

- A configured PostgreSQL that isn't running: database tools must answer with the setup hint within seconds, not hang the agent (Task 5 `test_database_url_adds_postgres_timeout`).
- A SQLite file that exists but was never migrated (no tables): the setup hint, not a crash (Task 5 `test_unmigrated_database_gives_hint`).
- The live session file is being written while it is read, so its last line can be half-written: ignored, no crash (Task 2 `test_malformed_and_partial_lines_are_ignored`).
- Secrets inside failed commands or prompts: come back as `[REDACTED:…]` (Task 5 `test_session_health_is_redacted`).
- The one-time `~/.promptlens` move message printing to stdout would corrupt the stdio protocol: it must go to stderr (Task 5 `test_migration_message_goes_to_stderr`).

---

### Task 1: Shared rendering helpers and session-file lookup

**Files:**
- Create: `backend/vibecheck/mcp/__init__.py`
- Create: `backend/vibecheck/mcp/render.py`
- Create: `backend/vibecheck/mcp/locate.py`
- Test: `backend/tests/test_mcp_locate.py`

**Interfaces:**
- Produces (`render.py`): `MAX_CHARS = 2000`; `short(text: str, n: int = 140) -> str`; `basename(path: str) -> str`; `relative(path: str, root: Path) -> str`; `bullets(items: Iterable[str]) -> list[str]`; `finish(text: str, redactor: Redactor) -> str`.
- Produces (`locate.py`): `encode_project_dir(path: str | Path) -> str`; `same_dir(a: str, b: str) -> bool`; `find_session_file(projects_dir: Path, project_dir: Path, session_id: str | None = None) -> Path | None`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_mcp_locate.py`:

```python
import json
import os
from pathlib import Path

from vibecheck.ingest.redact import Redactor
from vibecheck.mcp.locate import encode_project_dir, find_session_file, same_dir
from vibecheck.mcp.render import MAX_CHARS, finish, relative


def _session(folder: Path, name: str, cwd: str, mtime: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{name}.jsonl"
    p.write_text(json.dumps({"type": "user", "cwd": cwd, "sessionId": name}) + "\n", "utf-8")
    os.utime(p, (mtime, mtime))
    return p


def test_encode_windows_and_posix_paths():
    assert encode_project_dir(r"C:\Users\User\Desktop\Vibecheck") == "C--Users-User-Desktop-Vibecheck"
    assert encode_project_dir("/work/my_app.v2") == "-work-my-app-v2"


def test_same_dir_ignores_case_separators_and_trailing_slash():
    assert same_dir(r"C:\Work\App", "c:/work/app/")
    assert not same_dir("", "/work/app")
    assert not same_dir("/work/app2", "/work/app")


def test_picks_newest_file_in_encoded_folder_ignoring_case(tmp_path):
    projects = tmp_path / "projects"
    folder = projects / "c--work-app"  # drive letter case differs on disk
    _session(folder, "old", r"C:\work\app", 1000)
    new = _session(folder, "new", r"C:\work\app", 2000)
    assert find_session_file(projects, Path(r"C:\work\app")) == new


def test_session_id_selects_a_specific_file(tmp_path):
    folder = tmp_path / "projects" / "-work-app"
    old = _session(folder, "old", "/work/app", 1000)
    _session(folder, "new", "/work/app", 2000)
    assert find_session_file(tmp_path / "projects", Path("/work/app"), "old") == old
    assert find_session_file(tmp_path / "projects", Path("/work/app"), "../x") is None


def test_falls_back_to_cwd_match_when_folder_name_differs(tmp_path):
    projects = tmp_path / "projects"
    mine = _session(projects / "renamed", "s1", "/work/app/", 1000)
    _session(projects / "other", "s2", "/work/other", 3000)
    assert find_session_file(projects, Path("/work/app")) == mine


def test_missing_dirs_return_none(tmp_path):
    assert find_session_file(tmp_path / "nope", Path("/work/app")) is None
    (tmp_path / "projects").mkdir()
    assert find_session_file(tmp_path / "projects", Path("/work/app")) is None


def test_relative_paths_never_absolute():
    assert relative("/work/app/src/core.py", Path("/work/app")) == "src/core.py"
    assert relative(r"C:\Work\App\src\core.py", Path("c:/work/app")) == "src/core.py"
    assert relative("/elsewhere/secret/x.py", Path("/work/app")) == "x.py"


def test_finish_redacts_and_caps_length():
    out = finish("key sk-test1234567890abcdefghijkl " + "x" * 5000, Redactor())
    assert "[REDACTED:api_key]" in out and "sk-test" not in out
    assert len(out) <= MAX_CHARS and out.endswith("…")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_locate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vibecheck.mcp'`

- [ ] **Step 3: Write the implementation**

`backend/vibecheck/mcp/__init__.py`:

```python
"""MCP server: lets AI coding agents ask Vibecheck for feedback while they work."""
```

`backend/vibecheck/mcp/render.py`:

```python
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
```

`backend/vibecheck/mcp/locate.py`:

```python
"""Find the Claude Code session file for a project directory."""

from __future__ import annotations

import json
import re
from pathlib import Path

FIRST_LINES = 50  # cwd appears on the first user or assistant line


def encode_project_dir(path: str | Path) -> str:
    """Claude Code's folder name for a working directory: non-alphanumerics become '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def same_dir(a: str, b: str) -> bool:
    def norm(p: str) -> str:
        return p.replace("\\", "/").rstrip("/").lower()

    return bool(a) and norm(a) == norm(b)


def first_cwd(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f):
                if n >= FIRST_LINES:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("cwd"), str):
                    return obj["cwd"]
    except OSError:
        return None
    return None


def find_session_file(
    projects_dir: Path, project_dir: Path, session_id: str | None = None
) -> Path | None:
    """The newest session file for ``project_dir``, or the one named ``session_id``."""
    if not projects_dir.is_dir():
        return None
    wanted = encode_project_dir(project_dir).lower()
    folder = next(
        (d for d in projects_dir.iterdir() if d.is_dir() and d.name.lower() == wanted), None
    )
    if folder is not None:
        candidates = list(folder.glob("*.jsonl"))
    else:
        candidates = [
            p
            for p in projects_dir.rglob("*.jsonl")
            if same_dir(first_cwd(p) or "", str(project_dir))
        ]
    if session_id:
        candidates = [p for p in candidates if p.stem == session_id]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_locate.py -q`
Expected: 8 passed

- [ ] **Step 5: Lint and commit**

```bash
cd backend && .venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format --check .
git add backend/vibecheck/mcp backend/tests/test_mcp_locate.py
git commit -m "MCP: session file lookup and output helpers"
```

---

### Task 2: Live session health

**Files:**
- Create: `backend/tests/fixtures/struggle_session.jsonl`
- Create: `backend/vibecheck/mcp/live.py`
- Test: `backend/tests/test_mcp_live.py`

**Interfaces:**
- Consumes: `render.basename`, `render.short`, `render.bullets` (Task 1); `vibecheck.ingest.parser.Event`, `ToolUse`, `EDIT_TOOLS`, `strip_pasted`, `iter_events`; `vibecheck.metrics.struggle.compute_signals`, `raw_score`, `correction_text`, `EDIT_ALLOWANCE`.
- Produces: `LiveSession` dataclass (`prompts: list[str]`, `interrupts: int`, `failures: list[tuple[str, str | None]]`, `edit_paths: list[str]`); `Health` dataclass (`struggling: bool`, `signals: dict[str, int]`, `findings: list[str]`, `nudges: list[str]`); `read_session(events: Iterable[Event]) -> LiveSession`; `assess(s: LiveSession, weights: dict[str, float], correction_patterns: list[str]) -> Health`; `render_health(h: Health) -> str`.

- [ ] **Step 1: Create the fixture**

`backend/tests/fixtures/struggle_session.jsonl`, exactly these 8 lines. Six edits to `parser.py`, three failing Bash calls (the first contains a fake API key), one correction, one interrupt, three prompts. Its signals are `{"interrupts": 1, "corrections": 1, "tool_errors": 3, "repeated_edits": 3, "turns": 3}` with a raw score of 14.0.

```
{"sessionId": "sess-struggle", "cwd": "/work/demo", "gitBranch": "main", "version": "2.1.0", "isSidechain": false, "type": "user", "uuid": "s-u1", "parentUuid": null, "timestamp": "2026-09-20T10:00:00.000Z", "origin": {"kind": "human"}, "message": {"role": "user", "content": "make the parser faster"}}
{"sessionId": "sess-struggle", "cwd": "/work/demo", "gitBranch": "main", "version": "2.1.0", "isSidechain": false, "type": "assistant", "uuid": "s-a1", "parentUuid": "s-u1", "timestamp": "2026-09-20T10:00:05.000Z", "message": {"id": "msg_s1", "model": "claude-test", "role": "assistant", "content": [{"type": "tool_use", "id": "toolu_e1", "name": "Edit", "input": {"file_path": "/work/demo/src/parser.py", "old_string": "a", "new_string": "b"}}, {"type": "tool_use", "id": "toolu_e2", "name": "Edit", "input": {"file_path": "/work/demo/src/parser.py", "old_string": "b", "new_string": "c"}}, {"type": "tool_use", "id": "toolu_e3", "name": "Edit", "input": {"file_path": "/work/demo/src/parser.py", "old_string": "c", "new_string": "d"}}, {"type": "tool_use", "id": "toolu_b1", "name": "Bash", "input": {"command": "pytest tests/test_parser.py --api-key sk-test1234567890abcdefghijkl"}}]}}
{"sessionId": "sess-struggle", "cwd": "/work/demo", "gitBranch": "main", "version": "2.1.0", "isSidechain": false, "type": "user", "uuid": "s-r1", "parentUuid": "s-a1", "timestamp": "2026-09-20T10:00:09.000Z", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_e1", "content": "ok"}, {"type": "tool_result", "tool_use_id": "toolu_e2", "content": "ok"}, {"type": "tool_result", "tool_use_id": "toolu_e3", "content": "ok"}, {"type": "tool_result", "tool_use_id": "toolu_b1", "is_error": true, "content": "FAILED tests/test_parser.py::test_speed"}]}}
{"sessionId": "sess-struggle", "cwd": "/work/demo", "gitBranch": "main", "version": "2.1.0", "isSidechain": false, "type": "user", "uuid": "s-u2", "parentUuid": "s-r1", "timestamp": "2026-09-20T10:01:00.000Z", "origin": {"kind": "human"}, "message": {"role": "user", "content": "no, that's wrong, keep the old API"}}
{"sessionId": "sess-struggle", "cwd": "/work/demo", "gitBranch": "main", "version": "2.1.0", "isSidechain": false, "type": "assistant", "uuid": "s-a2", "parentUuid": "s-u2", "timestamp": "2026-09-20T10:01:05.000Z", "message": {"id": "msg_s2", "model": "claude-test", "role": "assistant", "content": [{"type": "tool_use", "id": "toolu_e4", "name": "Edit", "input": {"file_path": "/work/demo/src/parser.py", "old_string": "d", "new_string": "e"}}, {"type": "tool_use", "id": "toolu_e5", "name": "Edit", "input": {"file_path": "/work/demo/src/parser.py", "old_string": "e", "new_string": "f"}}, {"type": "tool_use", "id": "toolu_e6", "name": "Edit", "input": {"file_path": "/work/demo/src/parser.py", "old_string": "f", "new_string": "g"}}, {"type": "tool_use", "id": "toolu_b2", "name": "Bash", "input": {"command": "pytest tests/test_parser.py -x"}}, {"type": "tool_use", "id": "toolu_b3", "name": "Bash", "input": {"command": "pytest tests/test_parser.py -x -q"}}]}}
{"sessionId": "sess-struggle", "cwd": "/work/demo", "gitBranch": "main", "version": "2.1.0", "isSidechain": false, "type": "user", "uuid": "s-r2", "parentUuid": "s-a2", "timestamp": "2026-09-20T10:01:30.000Z", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_e4", "content": "ok"}, {"type": "tool_result", "tool_use_id": "toolu_e5", "content": "ok"}, {"type": "tool_result", "tool_use_id": "toolu_e6", "content": "ok"}, {"type": "tool_result", "tool_use_id": "toolu_b2", "is_error": true, "content": "FAILED"}, {"type": "tool_result", "tool_use_id": "toolu_b3", "is_error": true, "content": "FAILED"}]}}
{"sessionId": "sess-struggle", "cwd": "/work/demo", "gitBranch": "main", "version": "2.1.0", "isSidechain": false, "type": "user", "uuid": "s-i1", "parentUuid": "s-r2", "timestamp": "2026-09-20T10:01:40.000Z", "message": {"role": "user", "content": "[Request interrupted by user]"}}
{"sessionId": "sess-struggle", "cwd": "/work/demo", "gitBranch": "main", "version": "2.1.0", "isSidechain": false, "type": "user", "uuid": "s-u3", "parentUuid": "s-i1", "timestamp": "2026-09-20T10:02:00.000Z", "origin": {"kind": "human"}, "message": {"role": "user", "content": "use a cache in src/parser.py instead"}}
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_mcp_live.py`:

```python
import json
from pathlib import Path

from tests.conftest import FIXTURES
from vibecheck.config import Config
from vibecheck.ingest.parser import iter_events
from vibecheck.mcp.live import LiveSession, assess, read_session, render_health

CFG = Config()

HEALTHY = [
    {"type": "user", "uuid": "h1", "sessionId": "h", "cwd": "/w", "origin": {"kind": "human"},
     "message": {"role": "user", "content": "Add a --json flag to src/cli.py; tests should pass"}},
    {"type": "assistant", "uuid": "h2", "sessionId": "h",
     "message": {"id": "m", "role": "assistant", "content": [
         {"type": "tool_use", "id": "t1", "name": "Edit",
          "input": {"file_path": "/w/src/cli.py", "old_string": "a", "new_string": "b"}}]}},
    {"type": "user", "uuid": "h3", "sessionId": "h",
     "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
]


def read(path: Path) -> LiveSession:
    return read_session(ev for _, ev in iter_events(path))


def test_struggle_session_signals_and_text():
    h = assess(read(FIXTURES / "struggle_session.jsonl"), CFG.weights, CFG.correction_patterns)
    assert h.signals == {
        "interrupts": 1, "corrections": 1, "tool_errors": 3, "repeated_edits": 3, "turns": 3
    }
    assert h.struggling
    text = render_health(h)
    assert "Signs of struggle" in text
    assert "parser.py edited 6 times" in text
    assert "3 failed Bash call(s), e.g. `pytest tests/test_parser.py --api-key" in text
    assert "1 correction(s) from the user, first: \"no, that's wrong, keep the old API\"" in text
    assert "The user interrupted 1 time(s)" in text
    assert "Stop editing parser.py" in text
    assert "exact build or test command" in text
    assert "Summarise your plan back to the user" in text
    assert "/work/demo" not in text


def test_healthy_session(tmp_path):
    p = tmp_path / "h.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in HEALTHY) + "\n", "utf-8")
    h = assess(read(p), CFG.weights, CFG.correction_patterns)
    assert not h.struggling
    text = render_health(h)
    assert "Looks healthy" in text and "1 prompt(s) so far" in text
    assert "Try next" not in text


def test_malformed_and_partial_lines_are_ignored(tmp_path):
    good = (FIXTURES / "struggle_session.jsonl").read_text("utf-8")
    p = tmp_path / "s.jsonl"
    p.write_text(
        'not json\n{"type": "mystery", "foo": 1}\n[1, 2]\n' + good + '{"type": "user", "mess',
        "utf-8",
    )
    assert read(p) == read(FIXTURES / "struggle_session.jsonl")


def test_empty_session():
    h = assess(LiveSession(), CFG.weights, CFG.correction_patterns)
    assert not h.struggling
    assert "No prompts in this session yet" in render_health(h)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_live.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vibecheck.mcp.live'`

- [ ] **Step 4: Write the implementation**

`backend/vibecheck/mcp/live.py`:

```python
"""Struggle signals for the session in progress, read straight from its log file."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from vibecheck.ingest.parser import EDIT_TOOLS, Event, ToolUse, strip_pasted
from vibecheck.mcp.render import basename, bullets, short
from vibecheck.metrics.struggle import EDIT_ALLOWANCE, compute_signals, correction_text, raw_score

STRUGGLE_SCORE = 6.0  # weighted raw score that counts as "signs of struggle"
HOT_FILE_EDITS = 5  # more edits than this to one file always counts as struggling
LONG_SESSION = 8  # prompts; matches the digest's "long back-and-forth"
SHELL_TOOLS = {"Bash", "PowerShell"}


@dataclass
class LiveSession:
    prompts: list[str] = field(default_factory=list)
    interrupts: int = 0
    failures: list[tuple[str, str | None]] = field(default_factory=list)  # (tool, what)
    edit_paths: list[str] = field(default_factory=list)


@dataclass
class Health:
    struggling: bool
    signals: dict[str, int]
    findings: list[str]
    nudges: list[str]


def _what(tu: ToolUse | None) -> str | None:
    if tu is None:
        return None
    return tu.command or (basename(tu.file_path) if tu.file_path else None)


def read_session(events: Iterable[Event]) -> LiveSession:
    s = LiveSession()
    uses: dict[str, ToolUse] = {}
    for ev in events:
        if ev.kind == "human":
            s.prompts.append(ev.text or "")
        elif ev.kind == "interrupt":
            s.interrupts += 1
        elif ev.kind == "assistant":
            for tu in ev.tool_uses:
                uses.setdefault(tu.id, tu)
        elif ev.kind == "tool_result":
            for r in ev.tool_results:
                if r.is_error:
                    tu = uses.get(r.tool_use_id)
                    s.failures.append((tu.name if tu else "unknown", _what(tu)))
    s.edit_paths = [t.file_path for t in uses.values() if t.name in EDIT_TOOLS and t.file_path]
    return s


def _top_failed_tool(s: LiveSession) -> tuple[str, int]:
    return Counter(t for t, _ in s.failures).most_common(1)[0]


def _findings(
    s: LiveSession, signals: dict[str, int], hot: tuple[str, int], patterns: list[str]
) -> list[str]:
    out: list[str] = []
    if hot[1] > EDIT_ALLOWANCE:
        out.append(f"{basename(hot[0])} edited {hot[1]} times")
    if s.failures:
        tool, n = _top_failed_tool(s)
        line = f"{n} failed {tool} call(s)"
        example = next((w for t, w in s.failures if t == tool and w), None)
        if example:
            line += f", e.g. `{short(example, 80)}`"
        out.append(line)
    if signals["corrections"]:
        regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
        first = next(
            (p for p in s.prompts if any(r.search(correction_text(p)) for r in regexes)), ""
        )
        out.append(
            f'{signals["corrections"]} correction(s) from the user, '
            f'first: "{short(strip_pasted(first), 100)}"'
        )
    if s.interrupts:
        out.append(f"The user interrupted {s.interrupts} time(s)")
    if signals["turns"] >= LONG_SESSION:
        out.append(f"{signals['turns']} prompts so far; long sessions tend to drift")
    return out[:4]


def _nudges(s: LiveSession, signals: dict[str, int], hot: tuple[str, int]) -> list[str]:
    out: list[str] = []
    if hot[1] > EDIT_ALLOWANCE:
        out.append(
            f"Stop editing {basename(hot[0])} for a moment: re-read the latest error and "
            "state the root cause before the next edit."
        )
    if s.failures:
        if _top_failed_tool(s)[0] in SHELL_TOOLS:
            out.append("Ask the user for the exact build or test command instead of guessing.")
        else:
            out.append("Check the tool's inputs (paths, arguments) before retrying the call.")
    if signals["corrections"] or s.interrupts:
        out.append("Summarise your plan back to the user and get a yes before more edits.")
    if signals["turns"] >= LONG_SESSION:
        out.append("Suggest a fresh session that starts from a short summary of where you are.")
    return out[:3]


def assess(s: LiveSession, weights: dict[str, float], correction_patterns: list[str]) -> Health:
    signals = compute_signals(
        s.prompts, s.interrupts, len(s.failures), s.edit_paths, correction_patterns
    )
    hot = Counter(s.edit_paths).most_common(1)[0] if s.edit_paths else ("", 0)
    struggling = raw_score(signals, weights) >= STRUGGLE_SCORE or hot[1] > HOT_FILE_EDITS
    return Health(
        struggling,
        signals,
        _findings(s, signals, hot, correction_patterns),
        _nudges(s, signals, hot),
    )


def render_health(h: Health) -> str:
    if not h.signals["turns"]:
        return "## Session health\nNo prompts in this session yet."
    head = "Signs of struggle" if h.struggling else "Looks healthy"
    lines = [f"## Session health: {head}", f"{h.signals['turns']} prompt(s) so far."]
    if h.findings:
        lines += ["", "What stands out:", *bullets(h.findings)]
    if h.nudges:
        lines += ["", "Try next:", *bullets(h.nudges)]
    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_live.py -q`
Expected: 4 passed

- [ ] **Step 6: Lint and commit**

```bash
cd backend && .venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format --check .
git add backend/vibecheck/mcp/live.py backend/tests/test_mcp_live.py backend/tests/fixtures/struggle_session.jsonl
git commit -m "MCP: live session health from the session log"
```

(`tests/**` ignores E501, so the long fixture dicts in the test are fine. If `ruff format --check` wants to reflow `HEALTHY`, run `ruff format tests/test_mcp_live.py` and commit the result.)

---

### Task 3: Prompt critique

**Files:**
- Create: `backend/vibecheck/mcp/critique.py`
- Test: `backend/tests/test_mcp_critique.py`

**Interfaces:**
- Consumes: `render.bullets` (Task 1); `vibecheck.coach.features.extract_features`; `vibecheck.coach.rewrite.FIX_RE`, `RewriteContext`, `template_rewrite`; `vibecheck.ingest.parser.strip_pasted`.
- Produces: `critique_prompt(text: str) -> str`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_mcp_critique.py`:

```python
from vibecheck.mcp.critique import critique_prompt


def test_vague_prompt_gets_missing_items_and_rewrite():
    out = critique_prompt("fix the login bug")
    assert "which file(s) or folder" in out
    assert "the error message or what happens now" in out
    assert 'what "done" looks like' in out
    assert "In [file or folder], fix the login bug." in out
    assert "Done when: [the test or check that proves it works]." in out
    assert "asking the user" in out


def test_specific_prompt_passes():
    out = critique_prompt("In src/cli.py, add a --json flag; tests/test_cli.py should pass")
    assert "specific enough" in out
    assert "Could be" not in out


def test_empty_and_pasted_only_prompts():
    assert "empty" in critique_prompt("   ")
    assert "empty" in critique_prompt("<pasted_content>big log</pasted_content>")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_critique.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vibecheck.mcp.critique'`

- [ ] **Step 3: Write the implementation**

`backend/vibecheck/mcp/critique.py`:

```python
"""Rule-based check of one prompt, with a template rewrite (no LLM, no database)."""

from __future__ import annotations

from vibecheck.coach.features import extract_features
from vibecheck.coach.rewrite import FIX_RE, RewriteContext, template_rewrite
from vibecheck.ingest.parser import strip_pasted
from vibecheck.mcp.render import bullets


def critique_prompt(text: str) -> str:
    typed = strip_pasted(text).strip()
    if not typed:
        return "## Prompt check\nNothing to check: the prompt is empty."
    f = extract_features(typed, is_first=True)
    missing: list[str] = []
    if not f["mentions_file"]:
        missing.append("which file(s) or folder the change is in")
    if FIX_RE.search(typed) and not f["has_error_text"]:
        missing.append("the error message or what happens now")
    if not f["has_success_criteria"]:
        missing.append('what "done" looks like (expected behaviour, or a test that should pass)')
    if not missing:
        return "## Prompt check: specific enough\nIt says where to work and what done looks like."
    rewrite, _ = template_rewrite(typed, RewriteContext())
    return "\n".join(
        [
            "## Prompt check",
            "Missing:",
            *bullets(missing),
            "",
            "Could be:",
            "```",
            rewrite,
            "```",
            "",
            "Fill in the [placeholders] by asking the user, not by guessing.",
        ]
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_critique.py -q`
Expected: 3 passed

- [ ] **Step 5: Lint and commit**

```bash
cd backend && .venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format --check .
git add backend/vibecheck/mcp/critique.py backend/tests/test_mcp_critique.py
git commit -m "MCP: rule-based prompt critique with template rewrite"
```

---

### Task 4: Project lessons and habits from the database

**Files:**
- Create: `backend/vibecheck/mcp/lessons.py`
- Test: `backend/tests/test_mcp_lessons.py`

**Interfaces:**
- Consumes: `locate.same_dir`, `render.bullets`, `render.relative`, `render.short` (Task 1); models `Insight`, `Message`, `Project`, `Session`, `ToolCall`; `EDIT_TOOLS`, `strip_pasted`; `extract_features`; `INSIGHT_THRESHOLD` from `vibecheck.insights.digest`; `EDIT_ALLOWANCE` from `vibecheck.metrics.struggle`.
- Produces: `project_ids(db: DB, project_dir: Path) -> list[int]`; `project_lessons(db: DB, project_dir: Path, days: int = 30, now: datetime | None = None) -> str`; `habits(db: DB) -> str`.

Note: the spec says tips reuse "the rules in `digest._tips`". The rules are the same (no file named, no success criteria, failing shell commands, repeated edits), but the wording speaks to the agent instead of the human, so `lessons.py` has its own `_tips`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_mcp_lessons.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vibecheck.db.models import Insight, Message, Project, Session, ToolCall
from vibecheck.mcp.lessons import habits, project_lessons

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
HERE = Path("/work/app")


def seed(db):
    db.add_all(
        [
            Project(id=1, cwd="/work/app", repo_root="/work/app", name="app"),
            Project(id=2, cwd="/work/secret-client", name="secret-client"),
        ]
    )
    projects = [
        (1, "/work/app", "src/core.py", "pytest tests/test_core.py"),
        (2, "/work/secret-client", "billing.py", "make deploy-prod"),
    ]
    for i in range(2):
        for pid, root, fname, cmd in projects:
            sid = f"s{pid}-{i}"
            at = NOW - timedelta(days=i + 1)
            db.add(
                Session(
                    id=sid,
                    project_id=pid,
                    started_at=at,
                    has_commit=i == 0,
                    turns_to_commit=4 if i == 0 else None,
                )
            )
            db.add(
                Message(
                    session_id=sid,
                    event_uuid=f"{sid}-m",
                    role="user",
                    is_human_prompt=True,
                    timestamp=at,
                    text="make it better",
                )
            )
            for k in range(5):
                db.add(
                    ToolCall(
                        session_id=sid,
                        tool_use_id=f"{sid}-e{k}",
                        tool_name="Edit",
                        file_path=f"{root}/{fname}",
                    )
                )
            db.add(
                ToolCall(
                    session_id=sid, tool_use_id=f"{sid}-b", tool_name="Bash", command=cmd,
                    is_error=True,
                )
            )
    db.commit()


def test_project_lessons_only_mentions_this_project(db):
    seed(db)
    text = project_lessons(db, HERE, now=NOW)
    assert "2 session(s)" in text
    assert "src/core.py: re-edited in 2 session(s), 10 edits" in text
    assert "`pytest tests/test_core.py` failed 2 time(s)" in text
    assert "1 of 2 session(s) reached a commit, after a median of 4 prompt(s)." in text
    assert "100% named no file" in text
    assert "ask which ones" in text
    for leak in ("billing", "deploy", "secret", "/work/app"):
        assert leak not in text


def test_project_matching_ignores_case_and_trailing_slash(db):
    seed(db)
    assert "src/core.py" in project_lessons(db, Path("/WORK/app/"), now=NOW)


def test_no_sessions_in_window_or_unknown_project(db):
    seed(db)
    later = NOW + timedelta(days=60)
    assert "No sessions recorded" in project_lessons(db, HERE, days=30, now=later)
    assert "No sessions recorded" in project_lessons(db, Path("/elsewhere"), now=NOW)


def test_habits_needs_enough_sessions(db):
    seed(db)
    assert "4 of 20 sessions needed" in habits(db)


def test_habits_lists_titles_without_project_details(db):
    seed(db)
    for i in range(20):
        db.add(Session(id=f"x{i}", project_id=2))
    db.add(
        Insight(
            generated_at=NOW,
            kind="file:commit",
            title="Sessions where your first prompt named a file had 4 prompts to commit "
            "vs 9 otherwise (n=10 vs n=12).",
            detail={},
            n_a=10,
            n_b=12,
        )
    )
    db.commit()
    text = habits(db)
    assert "n=10 vs n=12" in text and "24 sessions" in text
    for leak in ("/work", "billing", "deploy", "core.py", "secret-client", "make it better"):
        assert leak not in text


def test_habits_with_enough_sessions_but_no_insights(db):
    for i in range(20):
        db.add(Session(id=f"x{i}"))
    db.commit()
    assert "vibecheck insights" in habits(db)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_lessons.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vibecheck.mcp.lessons'`

- [ ] **Step 3: Write the implementation**

`backend/vibecheck/mcp/lessons.py`:

```python
"""Lessons from past sessions: details from this project, habit numbers from all projects."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from vibecheck.coach.features import extract_features
from vibecheck.db.models import Insight, Message, Project, Session, ToolCall
from vibecheck.ingest.parser import EDIT_TOOLS, strip_pasted
from vibecheck.insights.digest import INSIGHT_THRESHOLD
from vibecheck.mcp.locate import same_dir
from vibecheck.mcp.render import bullets, relative, short
from vibecheck.metrics.struggle import EDIT_ALLOWANCE

TOP = 3


def project_ids(db: DB, project_dir: Path) -> list[int]:
    here = str(project_dir)
    return [
        p.id
        for p in db.scalars(select(Project))
        if same_dir(p.cwd, here) or same_dir(p.repo_root or "", here)
    ]


def _hot_files(db: DB, sids: list[str], project_dir: Path) -> list[str]:
    per_session: Counter[tuple[str, str]] = Counter()
    for sid, path in db.execute(
        select(ToolCall.session_id, ToolCall.file_path).where(
            ToolCall.session_id.in_(sids),
            ToolCall.tool_name.in_(EDIT_TOOLS),
            ToolCall.file_path.is_not(None),
        )
    ):
        per_session[(sid, path)] += 1
    hot_sessions: Counter[str] = Counter()
    edits: Counter[str] = Counter()
    for (_, path), n in per_session.items():
        if n > EDIT_ALLOWANCE:
            hot_sessions[path] += 1
            edits[path] += n
    return [
        f"{relative(p, project_dir)}: re-edited in {k} session(s), {edits[p]} edits"
        for p, k in hot_sessions.most_common(TOP)
    ]


def _failing_commands(db: DB, sids: list[str]) -> list[str]:
    rows = db.scalars(
        select(ToolCall.command).where(
            ToolCall.session_id.in_(sids),
            ToolCall.is_error.is_(True),
            ToolCall.command.is_not(None),
        )
    ).all()
    counts = Counter(short(c, 80) for c in rows)
    return [f"`{c}` failed {n} time(s)" for c, n in counts.most_common(TOP)]


def _commit_line(sessions: list[Session]) -> str:
    done = [s for s in sessions if s.has_commit]
    turns = [s.turns_to_commit for s in done if s.turns_to_commit is not None]
    line = f"{len(done)} of {len(sessions)} session(s) reached a commit"
    if turns:
        line += f", after a median of {median(turns):g} prompt(s)"
    return line + "."


def _first_prompt_gaps(db: DB, sids: list[str]) -> tuple[float, float] | None:
    """Share of sessions whose first prompt named no file, and gave no success criteria."""
    first: dict[str, str] = {}
    for sid, text in db.execute(
        select(Message.session_id, Message.text)
        .where(Message.session_id.in_(sids), Message.is_human_prompt.is_(True))
        .order_by(Message.session_id, Message.timestamp, Message.id)
    ):
        first.setdefault(sid, strip_pasted(text or ""))
    if not first:
        return None
    feats = [extract_features(t, is_first=True) for t in first.values()]
    n = len(feats)
    no_file = sum(not f["mentions_file"] for f in feats) / n
    no_done = sum(not f["has_success_criteria"] for f in feats) / n
    return no_file, no_done


def _tips(hot: bool, fails: bool, gaps: tuple[float, float] | None) -> list[str]:
    tips: list[str] = []
    if gaps and gaps[0] >= 0.5:
        tips.append("If the user hasn't named the file(s), ask which ones before searching.")
    if gaps and gaps[1] >= 0.5:
        tips.append('Agree on what "done" means (behaviour or a passing test) before editing.')
    if fails:
        tips.append("Confirm the exact build or test command with the user instead of guessing.")
    if hot:
        tips.append("For changes in the files above, write a short plan before the first edit.")
    return tips[:3]


def project_lessons(
    db: DB, project_dir: Path, days: int = 30, now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    ids = project_ids(db, project_dir)
    sessions = (
        list(
            db.scalars(
                select(Session).where(
                    Session.project_id.in_(ids), Session.started_at >= now - timedelta(days=days)
                )
            )
        )
        if ids
        else []
    )
    if not sessions:
        return (
            f"## Project lessons\nNo sessions recorded for this project in the last {days} "
            "days. Run `vibecheck run` to import recent sessions."
        )
    sids = [s.id for s in sessions]
    lines = [f"## Project lessons (last {days} days, {len(sessions)} session(s))"]
    hot = _hot_files(db, sids, project_dir)
    if hot:
        lines += ["", "Files that kept being re-edited:", *bullets(hot)]
    fails = _failing_commands(db, sids)
    if fails:
        lines += ["", "Commands that often failed:", *bullets(fails)]
    lines += ["", _commit_line(sessions)]
    gaps = _first_prompt_gaps(db, sids)
    if gaps:
        lines.append(
            f"First prompts: {gaps[0]:.0%} named no file, {gaps[1]:.0%} gave no success criteria."
        )
    tips = _tips(bool(hot), bool(fails), gaps)
    if tips:
        lines += ["", "For this task:", *bullets(tips)]
    return "\n".join(lines)


def habits(db: DB) -> str:
    total = db.scalar(select(func.count()).select_from(Session)) or 0
    if total < INSIGHT_THRESHOLD:
        return (
            f"## Habits\nNot enough history yet: {total} of {INSIGHT_THRESHOLD} sessions "
            "needed for habit comparisons."
        )
    rows = db.scalars(select(Insight).order_by(Insight.id)).all()
    if not rows:
        return (
            "## Habits\nNo clear habit differences found yet. "
            "Run `vibecheck insights` after more sessions."
        )
    return "\n".join(
        [f"## Habits (across {total} sessions, all projects)", *bullets(r.title for r in rows)]
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_lessons.py -q`
Expected: 6 passed

- [ ] **Step 5: Lint and commit**

```bash
cd backend && .venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format --check .
git add backend/vibecheck/mcp/lessons.py backend/tests/test_mcp_lessons.py
git commit -m "MCP: project lessons and all-project habits"
```

---

### Task 5: MCP server, `vibecheck mcp` command and docs

**Files:**
- Modify: `backend/pyproject.toml` (dependencies)
- Create: `backend/vibecheck/mcp/server.py`
- Modify: `backend/vibecheck/cli.py` (stderr console for the migration message; new `mcp` command)
- Modify: `README.md` (new "Use it from your AI coding agent" section and command-table row)
- Modify: `CLAUDE.md` (one line under Commands)
- Test: `backend/tests/test_mcp_server.py`, `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `find_session_file` (Task 1); `finish` (Task 1); `read_session`, `assess`, `render_health` (Task 2); `critique_prompt` (Task 3); `lessons.project_lessons`, `lessons.habits` (Task 4); `Config`, `Redactor`, `iter_events`, `make_sessionmaker`.
- Produces: `database_url(url: str) -> str | None`; `class Feedback(cfg: Config, project_dir: Path)` with methods `session_health(session_id: str | None = None) -> str`, `project_lessons(days: int = 30) -> str`, `habits() -> str`, `critique_prompt(text: str) -> str`; `build_server(cfg: Config, project_dir: Path) -> MCPServer`; CLI command `vibecheck mcp [--project PATH]`.

- [ ] **Step 1: Add and install the dependency**

In `backend/pyproject.toml`, add to `dependencies` after `"httpx>=0.27",`:

```toml
    "mcp>=2.2,<3",
```

Install into the venv (no `uv` on this machine; use the absolute interpreter path in PowerShell):

```powershell
cd C:\Users\User\Desktop\Vibecheck\backend
py -3.11 -m pip --python C:\Users\User\Desktop\Vibecheck\backend\.venv\Scripts\python.exe install "mcp>=2.2,<3"
.\.venv\Scripts\python.exe -c "from mcp.server.mcpserver import MCPServer; print('ok')"
```

Expected: `ok`. `backend/uv.lock` can't be regenerated here; the final report must tell the user to run `uv lock` where `uv` is available.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_mcp_server.py`:

```python
import shutil
from pathlib import Path

import anyio

from tests.conftest import FIXTURES
from vibecheck.mcp import server as server_mod
from vibecheck.mcp.server import Feedback, build_server, database_url

TOOLS = {"session_health", "project_lessons", "habits", "critique_prompt"}


def test_tools_are_registered(cfg, tmp_path):
    server = build_server(cfg, tmp_path)
    assert {t.name for t in anyio.run(server.list_tools)} == TOOLS


def test_call_tool_through_the_server(cfg, tmp_path):
    server = build_server(cfg, tmp_path)
    result = anyio.run(server.call_tool, "critique_prompt", {"text": "fix the login bug"})
    assert "In [file or folder]" in result.content[0].text


def test_session_health_is_redacted(cfg):
    folder = cfg.claude_projects_dir / "-work-demo"
    folder.mkdir()
    shutil.copy(FIXTURES / "struggle_session.jsonl", folder)
    out = Feedback(cfg, Path("/work/demo")).session_health()
    assert "Signs of struggle" in out
    assert "[REDACTED:api_key]" in out and "sk-test" not in out


def test_no_session_found(cfg, tmp_path):
    assert "No Claude Code session found" in Feedback(cfg, tmp_path / "proj").session_health()


def test_database_tools_without_database(cfg, tmp_path):
    cfg.database_url = f"sqlite:///{(tmp_path / 'missing.db').as_posix()}"
    fb = Feedback(cfg, tmp_path)
    assert "vibecheck init" in fb.project_lessons()
    assert "vibecheck init" in fb.habits()
    assert not (tmp_path / "missing.db").exists()


def test_unmigrated_database_gives_hint(cfg, tmp_path):
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    cfg.database_url = f"sqlite:///{empty.as_posix()}"
    assert "vibecheck init" in Feedback(cfg, tmp_path).project_lessons()


def test_database_tools_with_database(cfg, db, tmp_path):
    assert "No sessions recorded" in Feedback(cfg, tmp_path).project_lessons()
    assert "0 of 20 sessions needed" in Feedback(cfg, tmp_path).habits()


def test_database_url_adds_postgres_timeout(tmp_path):
    assert database_url("postgresql+psycopg://u:p@h/db").endswith("?connect_timeout=5")
    assert database_url("postgresql+psycopg://u:p@h/db?sslmode=require").endswith(
        "&connect_timeout=5"
    )
    assert database_url("postgresql+psycopg://u:p@h/db?connect_timeout=2").endswith("=2")
    assert database_url(f"sqlite:///{(tmp_path / 'nope.db').as_posix()}") is None


def test_unexpected_errors_become_a_message(cfg, tmp_path, monkeypatch, db):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(server_mod.lessons, "project_lessons", boom)
    out = Feedback(cfg, tmp_path).project_lessons()
    assert out == "Vibecheck couldn't load project lessons: RuntimeError."
```

Append to `backend/tests/test_cli.py`:

```python
def test_mcp_help(tmp_path):
    r = runner.invoke(app, ["mcp", "--help"], env=env_for(tmp_path))
    assert r.exit_code == 0, r.output
    assert "stdio" in r.stdout


def test_migration_message_goes_to_stderr(tmp_path, monkeypatch):
    import vibecheck.config

    legacy = tmp_path / ".promptlens"
    legacy.mkdir()
    monkeypatch.setattr(vibecheck.config, "LEGACY_HOME_DIR", legacy)
    monkeypatch.setattr(vibecheck.config, "HOME_DIR", tmp_path / ".vibecheck")
    r = runner.invoke(app, ["mcp", "--help"], env=env_for(tmp_path))
    assert r.exit_code == 0, r.output
    assert "Moved" not in r.stdout
    assert "Moved" in r.stderr
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_server.py tests/test_cli.py -q`
Expected: FAIL. `test_mcp_server.py` fails with `ModuleNotFoundError: No module named 'vibecheck.mcp.server'`, and the two new CLI tests fail with `No such command 'mcp'`.

- [ ] **Step 4: Write the server**

`backend/vibecheck/mcp/server.py`:

```python
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
```

Check against the Step 2 test: `result.content[0].text` is how `mcp` 2.x `CallToolResult` exposes a string return. If `test_call_tool_through_the_server` fails on that attribute, print `result` in the test to see the shape, then fix the test's access path. Don't change the tool.

- [ ] **Step 5: Wire up the CLI**

In `backend/vibecheck/cli.py`, below `console = Console()` add:

```python
err_console = Console(stderr=True)  # stdout carries the MCP protocol during `vibecheck mcp`
```

In `main()`, change the migration message line to:

```python
        err_console.print("Moved ~/.promptlens to ~/.vibecheck (PromptLens is now Vibecheck).")
```

Add the command after `serve`:

```python
@app.command("mcp")
def mcp_cmd(
    project: Path | None = typer.Option(
        None, "--project", help="Project to give feedback on (default: current directory)."
    ),
) -> None:
    """Run the MCP server on stdio, so AI coding agents can ask Vibecheck for feedback."""
    from vibecheck.mcp.server import build_server

    build_server(_cfg(), (project or Path.cwd()).resolve()).run()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_mcp_server.py tests/test_cli.py -q`
Expected: all pass

- [ ] **Step 7: Document it**

In `README.md`, add this row to the command table, after the `vibecheck stats` row:

```markdown
| `vibecheck mcp [--project PATH]` | Run the MCP server so your AI coding agent can ask for feedback (see below) |
```

Add this section after the "### Team mode" section:

~~~markdown
### Feedback for your AI agent (MCP)

`vibecheck mcp` is an [MCP](https://modelcontextprotocol.io) server. Your coding agent can call it while it works:

| Tool | What the agent gets | Needs the database? |
|---|---|---|
| `session_health` | How the current session is going (files edited over and over, failing commands, corrections) and what to do next | No, it reads the live session log |
| `project_lessons` | What usually goes wrong in this repo: re-edited files, failing commands, tips | Yes (`vibecheck run`) |
| `habits` | Prompting habits that led to better sessions, across all projects, numbers only | Yes |
| `critique_prompt` | What a request is missing, plus a sharper version with `[placeholders]` | No |

Register it once with Claude Code:

```bash
claude mcp add vibecheck -- vibecheck mcp
# from a checkout without the command on PATH (Windows):
claude mcp add vibecheck -- C:\path\to\backend\.venv\Scripts\vibecheck.exe mcp
```

Codex CLI and Antigravity take the same command in their MCP settings. The project is the directory the agent starts the server in, or `--project PATH`.

Everything the tools return is redacted and goes into the agent's context, so it is sent to your model provider. File names and commands only ever come from the current project, and `habits` returns numbers only. The server never writes anything. `session_health` reads Claude Code sessions only.
~~~

In `CLAUDE.md` under "## Commands", add:

```markdown
- MCP server (stdio): `cd backend && uv run vibecheck mcp`
```

- [ ] **Step 8: Full verification**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q
cd backend && .venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format --check .
```

Expected: every test passes (170 existing plus the new ones), and lint is clean.

Manual end-to-end check with Claude Code (PowerShell):

```powershell
claude mcp add vibecheck -- C:\Users\User\Desktop\Vibecheck\backend\.venv\Scripts\vibecheck.exe mcp
claude mcp list
```

Expected: `vibecheck` shows as connected. Leave it registered only if the user wants it. If not, run `claude mcp remove vibecheck`.

- [ ] **Step 9: Commit**

```bash
git add backend/pyproject.toml backend/vibecheck/mcp/server.py backend/vibecheck/cli.py backend/tests/test_mcp_server.py backend/tests/test_cli.py README.md CLAUDE.md
git commit -m "MCP: vibecheck mcp server with four feedback tools"
```
