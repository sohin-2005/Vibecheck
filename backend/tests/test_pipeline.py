import shutil

from promptlens.db.models import Session
from promptlens.ingest.ingest import ingest_all
from promptlens.pipeline import analyze_all
from tests.conftest import FIXTURES


def test_analyze_runs_end_to_end(cfg, db):
    d = cfg.claude_projects_dir / "p"
    d.mkdir()
    shutil.copy(FIXTURES / "basic_session.jsonl", d)
    ingest_all(cfg, db)
    out = analyze_all(cfg, db)
    assert out["sessions_recomputed"] == 1
    s = db.get(Session, "sess-basic")
    assert s.struggle_signals["interrupts"] == 1
    assert s.struggle_signals["corrections"] == 1
