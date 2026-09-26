from sqlalchemy import func, select

from vibecheck.db.models import Insight, LineSurvival, Session
from vibecheck.db.session import make_sessionmaker
from vibecheck.demo.generate import build_demo


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


def test_demo_covers_new_features(tmp_path):
    from vibecheck.db.models import TeamSnapshot

    url = f"sqlite:///{(tmp_path / 'demo2.db').as_posix()}"
    build_demo(url, n_sessions=60)
    db = make_sessionmaker(url)()
    assert len({s.tool for s in db.scalars(select(Session))}) >= 3
    assert (
        db.scalar(
            select(func.count())
            .select_from(LineSurvival)
            .where(LineSurvival.ai_lines_total.is_not(None))
        )
        > 0
    )
    assert {t.member for t in db.scalars(select(TeamSnapshot))} == {"you", "sam", "priya"}
    db.close()
