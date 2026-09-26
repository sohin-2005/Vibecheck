from datetime import UTC, datetime, timedelta

from vibecheck.config import Config
from vibecheck.db.models import Message, Project, Session, ToolCall
from vibecheck.insights.digest import build_digest

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
CFG = Config()


def add_session(
    db, sid, prompts, *, bash_errors=0, edits=None, interrupts=0, days_ago=1, committed=False
):
    t = NOW - timedelta(days=days_ago)
    db.add(
        Session(
            id=sid,
            project_id=1,
            title=f"title {sid}",
            started_at=t,
            ended_at=t + timedelta(minutes=30),
            models=[],
            has_commit=committed,
            tool="claude-code",
        )
    )
    db.flush()
    for i, text in enumerate(prompts):
        db.add(
            Message(
                session_id=sid,
                event_uuid=f"{sid}-p{i}",
                role="user",
                is_human_prompt=True,
                text=text,
                timestamp=t + timedelta(minutes=i),
            )
        )
    for i in range(interrupts):
        db.add(
            Message(
                session_id=sid,
                event_uuid=f"{sid}-i{i}",
                role="user",
                is_interrupt=True,
                text="[Request interrupted by user]",
                timestamp=t,
            )
        )
    for i in range(bash_errors):
        db.add(
            ToolCall(
                session_id=sid,
                tool_use_id=f"{sid}-b{i}",
                tool_name="Bash",
                command="npm test",
                is_error=True,
                timestamp=t,
            )
        )
    for i, path in enumerate(edits or []):
        db.add(
            ToolCall(
                session_id=sid,
                tool_use_id=f"{sid}-e{i}",
                tool_name="Edit",
                file_path=path,
                is_error=False,
                timestamp=t,
            )
        )
    db.commit()


def seed_project(db):
    db.add(Project(id=1, cwd="/p", name="p"))
    db.flush()


def test_works_with_a_single_session(db):
    seed_project(db)
    add_session(
        db,
        "only",
        ["fix it", "no, that's wrong", "still broken", "try again"],
        bash_errors=3,
        edits=["/p/app.py"] * 6,
    )
    d = build_digest(db, CFG, now=NOW)
    assert d["sessions"] == 1
    w = d["worst"]
    assert w["id"] == "only"
    kinds = [x["kind"] for x in w["went_wrong"]]
    assert kinds[0] == "corrections"  # 3 corrections x 2 = 6 points, the biggest contributor
    assert set(kinds) >= {"corrections", "tool_errors", "repeated_edits"}
    corr = next(x for x in w["went_wrong"] if x["kind"] == "corrections")
    assert "no, that's wrong" in corr["detail"]
    edits = next(x for x in w["went_wrong"] if x["kind"] == "repeated_edits")
    assert "app.py" in edits["detail"] and "6" in edits["detail"]
    tools = next(x for x in w["went_wrong"] if x["kind"] == "tool_errors")
    assert "Bash" in tools["detail"] and "npm test" in tools["detail"]
    assert d["best"] is None  # nothing to contrast with
    assert 1 <= len(d["tips"]) <= 3
    assert any("file" in t.lower() for t in d["tips"])  # first prompt named no file


def test_worst_and_best_this_week(db):
    seed_project(db)
    add_session(
        db, "calm", ["Add a --dry-run flag to sync.sh; done when it exits 0"], committed=True
    )
    add_session(db, "rough", ["make it better", "no", "that's wrong, revert"], interrupts=2)
    add_session(db, "old", ["no no no"] * 10, days_ago=30)
    d = build_digest(db, CFG, now=NOW)
    assert d["sessions"] == 2
    assert d["worst"]["id"] == "rough"
    assert d["best"]["id"] == "calm"
    assert d["worst"]["went_wrong"][0]["kind"] in ("interrupts", "corrections")


def test_falls_back_to_recent_sessions_when_week_is_empty(db):
    seed_project(db)
    add_session(db, "old", ["fix it", "try again"], days_ago=20)
    d = build_digest(db, CFG, now=NOW)
    assert d["sessions"] == 0
    assert d["worst"]["id"] == "old"
    assert d["fallback"] is True


def test_empty_database(db):
    d = build_digest(db, CFG, now=NOW)
    assert d["worst"] is None and d["tips"] == []
