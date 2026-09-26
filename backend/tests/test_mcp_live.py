import json
from pathlib import Path

from tests.conftest import FIXTURES
from vibecheck.config import Config
from vibecheck.ingest.parser import iter_events
from vibecheck.mcp.live import LiveSession, assess, read_session, render_health

CFG = Config()

HEALTHY = [
    {
        "type": "user",
        "uuid": "h1",
        "sessionId": "h",
        "cwd": "/w",
        "origin": {"kind": "human"},
        "message": {
            "role": "user",
            "content": "Add a --json flag to src/cli.py; tests should pass",
        },
    },
    {
        "type": "assistant",
        "uuid": "h2",
        "sessionId": "h",
        "message": {
            "id": "m",
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "Edit",
                    "input": {"file_path": "/w/src/cli.py", "old_string": "a", "new_string": "b"},
                }
            ],
        },
    },
    {
        "type": "user",
        "uuid": "h3",
        "sessionId": "h",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
        },
    },
]


def read(path: Path) -> LiveSession:
    return read_session(ev for _, ev in iter_events(path))


def test_struggle_session_signals_and_text():
    h = assess(read(FIXTURES / "struggle_session.jsonl"), CFG.weights, CFG.correction_patterns)
    assert h.signals == {
        "interrupts": 1,
        "corrections": 1,
        "tool_errors": 3,
        "repeated_edits": 3,
        "turns": 3,
    }
    assert h.struggling
    text = render_health(h)
    assert "Signs of struggle" in text
    assert "parser.py edited 6 times" in text
    assert "3 failed Bash call(s), e.g. `pytest tests/test_parser.py --api-key" in text
    assert '1 correction(s) from the user, first: "no, that\'s wrong, keep the old API"' in text
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
