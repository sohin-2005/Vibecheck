from datetime import UTC, datetime, timedelta

from promptlens.config import Config
from promptlens.db.models import Message, Project, PromptFeatures, Session, ToolCall
from promptlens.insights.findings import draft_findings

T = datetime(2026, 9, 1, 10, tzinfo=UTC)


def seed(db, n_sessions):
    db.add(Project(id=1, cwd="/a", name="webshop"))
    db.add(Project(id=2, cwd="/b", name="api"))
    db.flush()
    for i in range(n_sessions):
        pid = 1 if i % 3 else 2
        db.add(
            Session(
                id=f"s{i}",
                project_id=pid,
                tool="claude-code",
                started_at=T + timedelta(days=i),
                ended_at=T + timedelta(days=i, hours=1),
                active_minutes=60 if pid == 1 else 20,
                models=[],
                struggle_signals={
                    "interrupts": 0,
                    "corrections": 1,
                    "tool_errors": 1,
                    "repeated_edits": 4,
                    "turns": 3,
                    "raw_score": 11.0,
                },
            )
        )
        db.flush()
        db.add(
            Message(
                id=i + 1,
                session_id=f"s{i}",
                event_uuid=f"m{i}",
                role="user",
                is_human_prompt=True,
                text="fix app.py",
                timestamp=T + timedelta(days=i),
            )
        )
        db.flush()
        db.add(
            PromptFeatures(
                message_id=i + 1,
                char_len=10,
                mentions_file=i % 2 == 0,
                has_error_text=False,
                has_code_block=False,
                has_success_criteria=False,
                is_first_in_session=True,
            )
        )
        for k in range(4):
            db.add(
                ToolCall(
                    session_id=f"s{i}", tool_use_id=f"t{i}-{k}", tool_name="Bash", is_error=k == 0
                )
            )
    db.commit()


def test_findings_draft_uses_real_numbers(db):
    seed(db, 12)
    md = draft_findings(db, Config())
    assert md.startswith("## What I learned from my own data")
    assert "12 sessions" in md
    assert "webshop" in md  # where most active time went
    assert "repeated edits" in md.lower()  # 4 x 1.5 = 6 of 11 points: the largest share
    assert "Bash" in md and "25%" in md
    assert "Early data" not in md


def test_findings_warns_when_data_is_thin(db):
    seed(db, 3)
    md = draft_findings(db, Config())
    assert "Early data" in md


def test_findings_empty(db):
    assert "No sessions yet" in draft_findings(db, Config())


def test_tool_label():
    from promptlens.insights.findings import tool_label

    assert tool_label("mcp__Claude_Browser__computer") == "computer (Claude_Browser MCP)"
    assert tool_label("Bash") == "Bash"
