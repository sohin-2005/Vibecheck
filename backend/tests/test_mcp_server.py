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
