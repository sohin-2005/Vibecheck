import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from promptlens.api.main import create_app
from promptlens.db.models import (
    Commit,
    LineSurvival,
    Message,
    Project,
    Session,
    SessionCommit,
    TeamSnapshot,
    ToolCall,
)
from promptlens.team import build_export, import_export

T = datetime(2026, 9, 16, 10, tzinfo=UTC)  # ISO week 2026-W38
SECRET_PROMPT = "fix the bug in secret_billing.py using key hunter2"


def seed(db):
    db.add(
        Project(
            id=1, cwd="/work/secret-client", repo_root="/work/secret-client", name="secret-client"
        )
    )
    db.flush()
    for i in range(3):
        db.add(
            Session(
                id=f"s{i}",
                project_id=1,
                tool="claude-code",
                title=SECRET_PROMPT,
                started_at=T + timedelta(hours=i),
                ended_at=T + timedelta(hours=i, minutes=30),
                active_minutes=30,
                input_tokens=100,
                output_tokens=50,
                models=["m"],
                has_commit=i == 0,
                struggle_signals={"raw_score": float(i * 2)},
            )
        )
        db.flush()
        db.add(
            Message(
                session_id=f"s{i}",
                event_uuid=f"m{i}",
                role="user",
                is_human_prompt=True,
                text=SECRET_PROMPT,
                timestamp=T,
            )
        )
        db.add(
            ToolCall(
                session_id=f"s{i}",
                tool_use_id=f"t{i}",
                tool_name="Bash",
                command="cat secret.txt",
                is_error=i == 1,
                timestamp=T,
            )
        )
    db.add(
        Commit(
            sha="c1",
            project_id=1,
            authored_at=T,
            message="secret commit message",
            ai_coauthored=True,
            lines_added=10,
        )
    )
    db.flush()
    db.add(SessionCommit(session_id="s0", commit_sha="c1", link_method="trailer", confidence=0.9))
    db.add(
        LineSurvival(
            commit_sha="c1",
            days_after=7,
            status="ok",
            lines_total=10,
            lines_surviving=8,
            ai_lines_total=5,
            ai_lines_surviving=5,
            computed_at=T,
        )
    )
    db.commit()


def test_export_contains_aggregates_only(db):
    seed(db)
    payload = build_export(db, member="alex", weeks=520, now=T + timedelta(days=2))
    text = json.dumps(payload)
    for secret in (
        "secret_billing",
        "hunter2",
        "secret-client",
        "secret commit",
        "cat secret",
        "s0",
    ):
        assert secret not in text
    assert payload["schema"] == "promptlens.team.v1" and payload["member"] == "alex"
    week = next(w for w in payload["weeks"] if w["week"] == "2026-W38")
    assert week["sessions"] == 3
    assert week["active_hours"] == 1.5
    assert week["commit_rate"] == 33.3
    assert week["median_struggle"] == 2.0
    assert week["tool_error_rate"] == 33.3
    assert week["survival_7d"] == 100.0 and week["survival_basis"] == "edit-matched"
    assert list(week["projects"]) == [next(iter(week["projects"]))]
    assert next(iter(week["projects"])).startswith("project-")


def test_export_can_include_project_names(db):
    seed(db)
    payload = build_export(
        db, member="alex", weeks=520, include_projects=True, now=T + timedelta(days=2)
    )
    assert "secret-client" in payload["weeks"][-1]["projects"]


def test_import_is_idempotent(db):
    seed(db)
    payload = build_export(db, member="alex", weeks=520, now=T + timedelta(days=2))
    assert import_export(db, payload) == len(payload["weeks"])
    import_export(db, payload)
    assert db.query(TeamSnapshot).count() == len(payload["weeks"])


def test_import_rejects_bad_payloads(db):
    with pytest.raises(ValueError):
        import_export(db, {"schema": "something-else", "member": "x", "weeks": []})
    with pytest.raises(ValueError):
        import_export(db, {"schema": "promptlens.team.v1", "member": "", "weeks": []})


@pytest.fixture
def client(cfg):
    return TestClient(create_app(cfg))


def test_push_requires_token(client, db, monkeypatch):
    seed(db)
    payload = build_export(db, member="alex", weeks=520, now=T + timedelta(days=2))
    monkeypatch.delenv("PROMPTLENS_TEAM_TOKEN", raising=False)
    assert client.post("/api/team/snapshots", json=payload).status_code == 403
    monkeypatch.setenv("PROMPTLENS_TEAM_TOKEN", "s3cret")
    assert client.post("/api/team/snapshots", json=payload).status_code == 401
    r = client.post(
        "/api/team/snapshots", json=payload, headers={"X-PromptLens-Team-Token": "s3cret"}
    )
    assert r.status_code == 200 and r.json()["weeks"] == len(payload["weeks"])
    team = client.get("/api/team").json()
    assert team["members"] == ["alex"]
    assert any(row["week"] == "2026-W38" and row["sessions"] == 3 for row in team["rows"])
