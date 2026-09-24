import shutil

from sqlalchemy import select

from promptlens.db.models import Message, Session, ToolCall
from promptlens.ingest.ingest import ingest_all
from promptlens.sources import ADAPTERS
from promptlens.sources.aider import AiderAdapter
from promptlens.sources.antigravity import AntigravityAdapter
from promptlens.sources.claude_code import ClaudeCodeAdapter
from promptlens.sources.codex import CodexAdapter
from tests.conftest import FIXTURES


def events(adapter, path):
    return [e for _, e in adapter.iter_events(path)]


def test_registry_lists_all_tools():
    assert set(ADAPTERS) == {"claude-code", "antigravity", "codex", "aider"}


def test_claude_code_captures_edit_text():
    evs = events(ClaudeCodeAdapter(), FIXTURES / "basic_session.jsonl")
    edit = next(tu for e in evs for tu in e.tool_uses if tu.name == "Edit")
    assert edit.added_text == "b"


def test_antigravity_adapter():
    path = FIXTURES / "antigravity/brain/ag-sess-1/.system_generated/logs/transcript_full.jsonl"
    evs = events(AntigravityAdapter(), path)
    assert {e.session_id for e in evs} == {"antigravity:ag-sess-1"}
    human = [e for e in evs if e.kind == "human"]
    assert [h.text for h in human] == [
        "Add a health endpoint to server/app.py that returns 200",
        "that didn't work, try again",
    ]
    assert any(e.kind == "assistant" and e.text == "I'll add the endpoint." for e in evs)
    tool = next(tu for e in evs for tu in e.tool_uses)
    assert tool.name == "RUN_COMMAND" and tool.command == "pytest -q"
    assert next(tr for e in evs for tr in e.tool_results).is_error is True


def test_codex_adapter():
    path = next((FIXTURES / "codex").rglob("*.jsonl"))
    evs = events(CodexAdapter(), path)
    assert {e.session_id for e in evs if e.session_id} == {"codex:cx-123"}
    assert all(e.cwd == "/work/api" for e in evs if e.kind in ("human", "assistant"))
    human = [e for e in evs if e.kind == "human"]
    assert [h.text for h in human] == [
        "Add input validation to api/users.py so empty names return 400"
    ]
    tools = {tu.name: tu for e in evs for tu in e.tool_uses}
    assert tools["shell"].command == "pytest -q"
    assert tools["apply_patch"].file_path == "api/users.py"
    assert "raise BadRequest('name required')" in tools["apply_patch"].added_text
    results = {tr.tool_use_id: tr.is_error for e in evs for tr in e.tool_results}
    assert results == {"call_1": True, "call_2": False}
    usage = [e.usage for e in evs if e.usage]
    assert (usage[0].input, usage[0].cache_read, usage[0].output) == (200, 1000, 80)
    assert any(e.kind == "interrupt" for e in evs)
    assert any(e.model == "gpt-5-codex" for e in evs if e.kind == "assistant")


def test_aider_adapter():
    path = FIXTURES / "aider_repo/.aider.chat.history.md"
    evs = events(AiderAdapter(), path)
    sessions = sorted({e.session_id for e in evs})
    assert len(sessions) == 2 and all(s.startswith("aider:") for s in sessions)
    first = [e for e in evs if e.session_id == sessions[0]]
    assert [e.text for e in first if e.kind == "human"] == [
        "fix the off-by-one in pager.py, page 2 should start at item 11",
        "thanks, now add a test",
    ]
    edits = [tu for e in first for tu in e.tool_uses if tu.name == "Edit"]
    assert [tu.file_path.replace("\\", "/").rsplit("aider_repo/", 1)[1] for tu in edits] == [
        "pager.py",
        "tests/test_pager.py",
    ]
    assert edits[0].added_text == "    return (page - 1) * size"
    usage = [e.usage for e in first if e.usage]
    assert [(u.input, u.output) for u in usage] == [(2400, 310), (3100, 1200)]
    assert all(e.cwd and e.cwd.replace("\\", "/").endswith("aider_repo") for e in first)


def test_ingest_all_tools_together(cfg, db, tmp_path):
    cfg.claude_projects_dir.joinpath("p").mkdir()
    shutil.copy(FIXTURES / "basic_session.jsonl", cfg.claude_projects_dir / "p")
    cfg.antigravity_dirs = [FIXTURES / "antigravity/brain"]
    cfg.codex_dir = FIXTURES / "codex"
    repo = tmp_path / "aider_repo"
    shutil.copytree(FIXTURES / "aider_repo", repo)
    cfg.aider_dirs = [repo]
    res = ingest_all(cfg, db)
    assert res.files_processed == 4
    tools = dict(db.execute(select(Session.id, Session.tool)).all())
    assert tools["sess-basic"] == "claude-code"
    assert tools["codex:cx-123"] == "codex"
    assert tools["antigravity:ag-sess-1"] == "antigravity"
    assert sum(1 for t in tools.values() if t == "aider") == 2
    cx = db.get(Session, "codex:cx-123")
    assert cx.human_turns == 1 and cx.input_tokens == 200 and cx.models == ["gpt-5-codex"]
    patch = db.scalar(select(ToolCall).where(ToolCall.tool_name == "apply_patch"))
    assert patch.is_error is False and "BadRequest" in patch.added_text
    # idempotent across tools
    before = db.scalar(select(Message.id).order_by(Message.id.desc()))
    res2 = ingest_all(cfg, db)
    assert res2.files_processed == 0
    assert db.scalar(select(Message.id).order_by(Message.id.desc())) == before


def test_disabled_tools_are_skipped(cfg, db):
    cfg.codex_dir = FIXTURES / "codex"
    cfg.tools = ["claude-code"]
    ingest_all(cfg, db)
    assert db.get(Session, "codex:cx-123") is None
