from promptlens.ingest.parser import iter_events, parse_line, summarize
from tests.conftest import FIXTURES

BASIC = FIXTURES / "basic_session.jsonl"


def events():
    return [e for _, e in iter_events(BASIC)]


def by_uuid(uuid):
    return next(e for e in events() if e.uuid == uuid)


def test_malformed_and_non_object_lines_are_skipped():
    evs = events()
    # 17 lines: 1 malformed, 1 blank, 1 JSON array -> 14 events
    assert len(evs) == 14


def test_line_numbers_are_one_based_and_preserved():
    nums = [n for n, _ in iter_events(BASIC)]
    assert nums[0] == 1
    assert 13 not in nums  # the malformed line


def test_human_prompt_string_content():
    e = by_uuid("u1")
    assert e.kind == "human"
    assert e.text.startswith("Fix the login bug")
    assert e.session_id == "sess-basic"
    assert e.cwd == "/work/demo"
    assert e.timestamp.isoformat() == "2026-09-01T10:00:00+00:00"


def test_human_prompt_text_blocks():
    assert by_uuid("u5").kind == "human"
    assert by_uuid("u5").text == "no, that's wrong. try again"


def test_tool_results_are_not_human_prompts():
    e = by_uuid("u3")
    assert e.kind == "tool_result"
    assert e.tool_results[0].tool_use_id == "toolu_2"
    assert e.tool_results[0].is_error is True
    assert by_uuid("u2").tool_results[0].is_error is False


def test_interrupt_detected():
    e = by_uuid("u4")
    assert e.kind == "interrupt"


def test_meta_and_task_notifications_are_not_human():
    assert by_uuid("u6").kind == "user_meta"
    assert by_uuid("u7").kind == "user_meta"


def test_assistant_blocks_and_usage():
    a1, a2 = by_uuid("a1"), by_uuid("a2")
    assert a1.kind == a2.kind == "assistant"
    assert a1.api_message_id == a2.api_message_id == "msg_1"
    assert a1.text == "Looking at it."
    assert a1.usage.cache_read == 1000
    assert a1.model == "claude-test"
    tu = a2.tool_uses[0]
    assert (tu.id, tu.name, tu.file_path) == ("toolu_1", "Edit", "/work/demo/src/auth.py")


def test_bash_command_extracted():
    assert by_uuid("a3").tool_uses[0].command == "pytest -q"


def test_sidechain_flag():
    assert by_uuid("a4").is_sidechain is True
    assert by_uuid("a1").is_sidechain is False


def test_unknown_types_become_other():
    e = by_uuid("x1")
    assert e.kind == "other"
    assert e.event_type == "brand-new-event-type"
    t = next(e for e in events() if e.event_type == "custom-title")
    assert t.kind == "other" and t.title == "Fix login bug"


def test_parse_line_never_raises_on_weird_shapes():
    weird = [
        '{"type": "user", "message": null}',
        '{"type": "user", "message": {"content": 42}}',
        '{"type": "assistant", "message": {"content": [null, 1, {"type": "tool_use"}]}}',
        '{"type": "user", "message": {"content": [{"type": "tool_result"}]}}',
        '{"type": "assistant", "message": {"usage": "bad"}}',
        '{"timestamp": "not a date", "type": 5}',
    ]
    for w in weird:
        parse_line(w)  # must not raise


def test_resume_from_offset():
    tail = list(iter_events(BASIC, start_line=14))
    assert [e.uuid for _, e in tail] == ["x1", "u8"]


def test_summarize_counts():
    s = summarize([BASIC])
    assert s["files"] == 1
    assert s["malformed_lines"] == 2
    assert s["kinds"]["human"] == 3
    assert s["kinds"]["assistant"] == 4
