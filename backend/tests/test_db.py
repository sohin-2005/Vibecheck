from datetime import UTC, datetime

from sqlalchemy import inspect

from vibecheck.db.models import Project, Session
from vibecheck.db.session import get_engine, run_migrations


def test_migrations_create_all_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url)
    tables = set(inspect(get_engine(url)).get_table_names())
    assert {"sessions", "messages", "tool_calls", "commits", "line_survival"} <= tables


def test_datetimes_round_trip_as_utc(db):
    db.add(Project(id=1, cwd="/x", name="x"))
    db.add(Session(id="s1", project_id=1, started_at=datetime(2026, 1, 1, 12, tzinfo=UTC)))
    db.commit()
    db.expire_all()
    s = db.get(Session, "s1")
    assert s.started_at == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert s.started_at.tzinfo is not None
