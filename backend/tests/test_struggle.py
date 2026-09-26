from datetime import UTC, datetime

from vibecheck.config import Config
from vibecheck.db.models import Message, Project, Session, ToolCall
from vibecheck.metrics.struggle import (
    compute_signals,
    compute_struggle,
    percentile_ranks,
    raw_score,
)

CFG = Config()


def test_signals():
    s = compute_signals(
        prompts=["fix it", "no, that's wrong", "still broken after that", "thanks"],
        interrupts=2,
        tool_errors=3,
        edit_paths=["a.py"] * 5 + ["b.py"] * 2 + ["c.py"] * 4,
        correction_patterns=CFG.correction_patterns,
    )
    assert s == {
        "interrupts": 2,
        "corrections": 2,
        "tool_errors": 3,
        "repeated_edits": 3,
        "turns": 4,
    }


def test_correction_patterns_do_not_fire_on_innocent_words():
    s = compute_signals(
        ["Add a note about nobody", "know the answer"], 0, 0, [], CFG.correction_patterns
    )
    assert s["corrections"] == 0


def test_raw_score_weights():
    sig = {"interrupts": 1, "corrections": 1, "tool_errors": 1, "repeated_edits": 2, "turns": 4}
    assert raw_score(sig, CFG.weights) == 3 + 2 + 1 + 3 + 2


def test_percentile_ranks():
    r = percentile_ranks({"a": 0.0, "b": 5.0, "c": 5.0, "d": 10.0})
    assert r == {"a": 0.0, "b": 33.33, "c": 33.33, "d": 100.0}
    assert percentile_ranks({"x": 3.0}) == {"x": 0.0}
    assert percentile_ranks({}) == {}


def test_compute_struggle_stores_score_and_signals(db):
    t = datetime(2026, 1, 1, tzinfo=UTC)
    db.add(Project(id=1, cwd="/p", name="p"))
    for sid in ("calm", "rough"):
        db.add(Session(id=sid, project_id=1, models=[]))
    db.flush()
    db.add(
        Message(
            session_id="calm",
            event_uuid="c1",
            role="user",
            is_human_prompt=True,
            text="add tests",
            timestamp=t,
        )
    )
    db.add(
        Message(
            session_id="rough",
            event_uuid="r1",
            role="user",
            is_human_prompt=True,
            text="fix bug",
            timestamp=t,
        )
    )
    db.add(
        Message(
            session_id="rough",
            event_uuid="r2",
            role="user",
            is_human_prompt=True,
            text="that's wrong, try again",
            timestamp=t,
        )
    )
    db.add(
        Message(
            session_id="rough",
            event_uuid="r3",
            role="user",
            is_interrupt=True,
            text="[Request interrupted by user]",
            timestamp=t,
        )
    )
    db.add(ToolCall(session_id="rough", tool_use_id="x", tool_name="Bash", is_error=True))
    db.commit()
    compute_struggle(db, CFG)
    calm, rough = db.get(Session, "calm"), db.get(Session, "rough")
    assert float(calm.struggle_score) == 0.0
    assert float(rough.struggle_score) == 100.0
    assert rough.struggle_signals["interrupts"] == 1
    assert rough.struggle_signals["corrections"] == 1
    assert rough.struggle_signals["tool_errors"] == 1
    assert rough.struggle_signals["raw_score"] == 3 + 2 + 1 + 1.0


def test_pasted_documents_are_not_corrections():
    pasted = '<pasted_content id="x">\nSpec: no, the parser must never crash. Try again later.\n</pasted_content id="x">\nbuild this'
    long_typed = "Here is the plan. " * 40 + "no, that's wrong"
    s = compute_signals([pasted, long_typed, "no, that's wrong"], 0, 0, [], CFG.correction_patterns)
    assert s["corrections"] == 1


def test_strip_pasted():
    from vibecheck.ingest.parser import strip_pasted

    assert (
        strip_pasted('hi <pasted_content id="a">\nbig\n</pasted_content id="a"> there')
        == "hi [pasted text] there"
    )
