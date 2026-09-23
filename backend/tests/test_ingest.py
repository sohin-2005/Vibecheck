import json
import shutil

from sqlalchemy import func, select

from promptlens.config import ModelPrice
from promptlens.db.models import IngestState, Message, Project, RawEvent, Session, ToolCall
from promptlens.ingest.ingest import ingest_all
from tests.conftest import FIXTURES


def place(cfg, name="basic_session.jsonl"):
    d = cfg.claude_projects_dir / "-work-demo"
    d.mkdir(exist_ok=True)
    dst = d / name
    shutil.copy(FIXTURES / name, dst)
    return dst


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def snapshot(db):
    return {m.__tablename__: count(db, m) for m in (Project, Session, RawEvent, Message, ToolCall)}


def test_ingest_basic_fixture(cfg, db):
    place(cfg)
    res = ingest_all(cfg, db)
    assert res.files_processed == 1
    s = db.get(Session, "sess-basic")
    assert s.title == "Fix login bug"
    assert s.human_turns == 3
    assert s.assistant_turns == 3
    assert (s.input_tokens, s.output_tokens) == (16, 29)
    assert (s.cache_write_tokens, s.cache_read_tokens) == (100, 1500)
    assert sorted(s.models) == ["claude-sub", "claude-test"]
    assert s.started_at.isoformat() == "2026-09-01T10:00:00+00:00"
    assert s.ended_at.isoformat() == "2026-09-01T10:03:00+00:00"
    assert s.git_branch == "main" and s.cc_version == "2.1.0"
    assert s.est_cost_usd is None  # no prices configured
    proj = db.get(Project, s.project_id)
    assert proj.cwd == "/work/demo" and proj.name == "demo"

    tools = {t.tool_use_id: t for t in db.scalars(select(ToolCall))}
    assert tools["toolu_1"].is_error is False
    assert tools["toolu_1"].file_path == "/work/demo/src/auth.py"
    assert tools["toolu_2"].is_error is True
    assert tools["toolu_2"].command == "pytest -q"

    kinds = db.execute(select(Message.is_human_prompt, Message.is_interrupt)).all()
    assert sum(1 for h, _ in kinds if h) == 3
    assert sum(1 for _, i in kinds if i) == 1


def test_everything_is_redacted(cfg, db):
    place(cfg)
    ingest_all(cfg, db)
    texts = [t for t in db.scalars(select(Message.text)) if t]
    assert not any("AKIAABCDEFGHIJKLMNOP" in t for t in texts)
    assert any("[REDACTED:aws_key]" in t for t in texts)
    payloads = [json.dumps(p) for p in db.scalars(select(RawEvent.payload))]
    assert not any("AKIAABCDEFGHIJKLMNOP" in p for p in payloads)


def test_idempotent(cfg, db):
    place(cfg)
    ingest_all(cfg, db)
    first = snapshot(db)
    res = ingest_all(cfg, db)
    assert res.files_processed == 0
    assert snapshot(db) == first
    # forcing a full reprocess must not duplicate anything either
    db.query(IngestState).delete()
    db.commit()
    ingest_all(cfg, db)
    assert snapshot(db) == first


def test_incremental_append_only_processes_new_lines(cfg, db):
    path = place(cfg)
    ingest_all(cfg, db)
    new = {
        "type": "user",
        "uuid": "u9",
        "sessionId": "sess-basic",
        "cwd": "/work/demo",
        "timestamp": "2026-09-01T10:05:00Z",
        "message": {"role": "user", "content": "one more thing"},
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(new) + "\n")
    res = ingest_all(cfg, db)
    assert res.lines_processed == 1
    assert db.get(Session, "sess-basic").human_turns == 4


def test_partial_trailing_line_is_left_for_later(cfg, db):
    path = place(cfg)
    ingest_all(cfg, db)
    line = json.dumps(
        {
            "type": "user",
            "uuid": "u9",
            "sessionId": "sess-basic",
            "message": {"role": "user", "content": "later"},
        }
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(line[:20])
    ingest_all(cfg, db)
    with path.open("a", encoding="utf-8") as f:
        f.write(line[20:] + "\n")
    ingest_all(cfg, db)
    assert db.get(Session, "sess-basic").human_turns == 4


def test_shrunk_file_is_reprocessed(cfg, db):
    path = place(cfg)
    ingest_all(cfg, db)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:3]), encoding="utf-8")
    res = ingest_all(cfg, db)
    assert res.files_processed == 1 and res.lines_processed == 3


def test_exclude_sidechains(cfg, db):
    cfg.include_sidechains = False
    place(cfg)
    ingest_all(cfg, db)
    s = db.get(Session, "sess-basic")
    assert (s.input_tokens, s.output_tokens) == (15, 27)
    assert s.models == ["claude-test"]


def test_ignore_projects(cfg, db):
    cfg.ignore_projects = ["/work/demo"]
    place(cfg)
    ingest_all(cfg, db)
    assert count(db, Session) == 0


def test_cost_with_prices(cfg, db):
    cfg.pricing = {
        "claude-test": ModelPrice(
            input=1_000_000, output=1_000_000, cache_write=0, cache_read=1_000
        ),
        "claude-sub": ModelPrice(input=0, output=0),
    }
    place(cfg)
    ingest_all(cfg, db)
    # claude-test: 15 in + 27 out = 42 USD, + 1500 cache_read * 1000/1e6 = 1.5
    assert float(db.get(Session, "sess-basic").est_cost_usd) == 43.5
