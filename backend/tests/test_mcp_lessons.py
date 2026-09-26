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
    db.flush()  # no ORM relationships, so parents must be inserted before children
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
            db.flush()
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
                    session_id=sid,
                    tool_use_id=f"{sid}-b",
                    tool_name="Bash",
                    command=cmd,
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
