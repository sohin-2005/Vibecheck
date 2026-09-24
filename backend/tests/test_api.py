import shutil
import time

import pytest
from fastapi.testclient import TestClient

from promptlens.api.main import create_app
from promptlens.db.models import Insight
from promptlens.ingest.ingest import ingest_all
from promptlens.pipeline import analyze_all
from tests.conftest import FIXTURES


@pytest.fixture
def client(cfg, db, tmp_path):
    d = cfg.claude_projects_dir / "p"
    d.mkdir()
    shutil.copy(FIXTURES / "basic_session.jsonl", d)
    ingest_all(cfg, db)
    analyze_all(cfg, db)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    return TestClient(create_app(cfg, dist=dist))


def test_overview(client):
    r = client.get("/api/overview").json()
    assert r["totals"]["sessions"] == 1
    assert r["totals"]["prompts"] == 3
    assert r["totals"]["cost_usd"] is None and r["totals"]["unpriced_sessions"] == 1
    assert r["daily"][0]["date"] == "2026-09-01"
    assert r["by_project"] == [{"project": "demo", "sessions": 1}]


def test_date_filters(client):
    assert client.get("/api/overview?from=2026-09-02").json()["totals"]["sessions"] == 0
    assert client.get("/api/overview?to=2026-09-01").json()["totals"]["sessions"] == 1


def test_sessions_list_and_sort(client):
    r = client.get("/api/sessions?sort=struggle_score&order=desc").json()
    assert r["total"] == 1
    assert r["items"][0]["id"] == "sess-basic"
    assert r["items"][0]["title"] == "Fix login bug"
    assert client.get("/api/sessions?sort=bogus").status_code == 422


def test_session_detail_and_timeline(client):
    d = client.get("/api/sessions/sess-basic").json()
    assert d["struggle_signals"]["interrupts"] == 1
    assert {t["tool_name"]: t["errors"] for t in d["tools"]} == {"Edit": 0, "Bash": 1}
    tl = client.get("/api/sessions/sess-basic/timeline").json()
    kinds = [i["kind"] for i in tl]
    assert kinds[0] == "prompt"
    assert "tool" in kinds and "interrupt" in kinds
    assert client.get("/api/sessions/nope").status_code == 404


def test_projects_tools_survival_coach(client):
    assert client.get("/api/projects").json()[0]["sessions"] == 1
    tools = {t["tool_name"]: t for t in client.get("/api/tools").json()}
    assert tools["Bash"]["error_rate"] == 100.0
    assert client.get("/api/survival").json()["checkpoints"] == []
    s = client.get("/api/coach/summary").json()
    assert s["prompts"] == 3 and s["scored"] == 0
    p = client.get("/api/coach/prompts").json()
    assert p["total"] == 3


def test_insights_endpoint(client, db):
    from datetime import UTC, datetime

    db.add(Insight(generated_at=datetime.now(UTC), kind="k", title="t", detail={}, n_a=10, n_b=12))
    db.commit()
    assert client.get("/api/insights").json()[0]["title"] == "t"


def test_jobs(client):
    assert client.post("/api/jobs/nope").status_code == 404
    job = client.post("/api/jobs/analyze").json()
    for _ in range(50):
        st = client.get(f"/api/jobs/{job['id']}").json()
        if st["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert st["status"] == "done", st
    assert st["result"]["struggle_scored"] == 1


def test_config_masks_password(client):
    c = client.get("/api/config").json()
    assert "llm" in c and "***" not in c["database_url"]  # sqlite has no password


def test_spa_fallback(client):
    assert "app" in client.get("/sessions/abc").text
    assert client.get("/api/nope").status_code == 404


def test_sources_and_tool_filter(client):
    src = {s["tool"]: s for s in client.get("/api/sources").json()}
    assert src["claude-code"]["sessions"] == 1 and src["claude-code"]["verified"] is True
    assert src["codex"]["verified"] is False
    assert client.get("/api/sessions?tool=codex").json()["total"] == 0
    assert client.get("/api/sessions?tool=claude-code").json()["items"][0]["tool"] == "claude-code"


def test_digest_endpoint(client):
    d = client.get("/api/digest?days=3650").json()
    assert d["worst"]["id"] == "sess-basic"
    assert d["worst"]["went_wrong"]


def test_rewrite_endpoint(client):
    items = client.get("/api/coach/prompts").json()["items"]
    vague = next(i for i in items if "that's wrong" in i["text"])
    r = client.post(f"/api/coach/rewrite/{vague['message_id']}?llm=false").json()
    assert r["method"] == "template" and r["changes"]
    again = client.get("/api/coach/prompts").json()["items"]
    assert (
        next(i for i in again if i["message_id"] == vague["message_id"])["rewrite"]["rewrite"]
        == r["rewrite"]
    )
    assert client.post("/api/coach/rewrite/99999?llm=false").status_code == 404
