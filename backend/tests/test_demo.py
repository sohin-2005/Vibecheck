from sqlalchemy import func, select

from promptlens.db.models import Insight, LineSurvival, Session
from promptlens.db.session import make_sessionmaker
from promptlens.demo.generate import build_demo


def test_demo_builds_a_complete_dataset(tmp_path):
    url = f"sqlite:///{(tmp_path / 'demo.db').as_posix()}"
    msg = build_demo(url, n_sessions=80)
    assert "80 sessions" in msg
    db = make_sessionmaker(url)()
    assert db.scalar(select(func.count()).select_from(Session)) == 80
    assert db.scalar(select(func.count()).select_from(Insight)) > 0
    assert db.scalar(select(func.count()).select_from(LineSurvival)) > 0
    s = db.scalars(select(Session)).first()
    assert s.est_cost_usd is not None and s.struggle_score is not None and s.ended_at is not None
    db.close()
