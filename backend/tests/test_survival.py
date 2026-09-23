from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from promptlens.db.models import LineSurvival, Project, Session
from promptlens.gitdata.collector import collect_all
from promptlens.gitdata.survival import compute_survival, count_blame, default_branch
from tests.conftest import git

T0 = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
NOW = T0 + timedelta(days=40)
AI = "\n\nCo-Authored-By: Claude <noreply@anthropic.com>"


def write(repo, path, lines):
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")


def commit_all(repo, msg, when):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, date=when.isoformat())
    return git(repo, "rev-parse", "HEAD")


def build_history(repo):
    write(repo, "keep.py", ["base"])
    commit_all(repo, "base", T0 - timedelta(days=1))
    write(repo, "ai.py", [f"line {i}" for i in range(10)])
    write(repo, "tool.py", ["def a():", "    return 1", "def b():", "    return 2"])
    c = commit_all(repo, "feat: ai work" + AI, T0)
    # day 2: human rewrites half of ai.py
    write(repo, "ai.py", [f"rewritten {i}" for i in range(5)] + [f"line {i}" for i in range(5, 10)])
    commit_all(repo, "human rewrite", T0 + timedelta(days=2))
    # day 3: rename tool.py -> util.py (content unchanged)
    git(repo, "mv", "tool.py", "util.py")
    commit_all(repo, "rename", T0 + timedelta(days=3))
    # day 4: whitespace-only change of ai.py lines 5-9 must not count as a rewrite
    write(
        repo, "ai.py", [f"rewritten {i}" for i in range(5)] + [f"line  {i}  " for i in range(5, 10)]
    )
    commit_all(repo, "reformat", T0 + timedelta(days=4))
    # day 10: util.py deleted
    git(repo, "rm", "-q", "util.py")
    commit_all(repo, "remove util", T0 + timedelta(days=10))
    return c


def setup(db, repo):
    db.add(Project(id=1, cwd=str(repo), repo_root=str(repo), name="repo"))
    db.flush()
    db.add(
        Session(id="s", project_id=1, started_at=T0 - timedelta(hours=1), ended_at=T0, models=[])
    )
    db.commit()


def surv(db, sha):
    return {
        r.days_after: r
        for r in db.scalars(select(LineSurvival).where(LineSurvival.commit_sha == sha))
    }


def test_count_blame_porcelain():
    sha_a, sha_b = "a" * 40, "b" * 40
    out = (
        f"{sha_a} 1 1 2\nauthor x\nfilename f\n\tline1\n"
        f"{sha_a} 2 2\n\tline2\n"
        f"{sha_b} 1 3 1\nauthor y\nfilename f\n\tline3\n"
    )
    assert count_blame(out) == {sha_a: 2, sha_b: 1}


def test_default_branch(repo):
    write(repo, "x", ["1"])
    commit_all(repo, "x", T0)
    assert default_branch(str(repo)) == "main"


def test_survival_exact_numbers(cfg, db, repo):
    c = build_history(repo)
    setup(db, repo)
    collect_all(cfg, db)
    compute_survival(cfg, db, now=NOW)
    s = surv(db, c)
    assert set(s) == {1, 7, 30}
    assert (s[1].lines_total, s[1].lines_surviving) == (14, 14)
    # day 7: 5 of ai.py rewritten; whitespace change ignored; renamed file still counts
    assert (s[7].lines_total, s[7].lines_surviving) == (14, 9)
    # day 30: util.py (4 lines) deleted
    assert (s[30].lines_total, s[30].lines_surviving) == (14, 5)
    assert all(r.status == "ok" for r in s.values())


def test_only_due_checkpoints_and_idempotent(cfg, db, repo):
    c = build_history(repo)
    setup(db, repo)
    collect_all(cfg, db)
    compute_survival(cfg, db, now=T0 + timedelta(days=8))
    assert set(surv(db, c)) == {1, 7}
    computed = compute_survival(cfg, db, now=T0 + timedelta(days=8))
    assert computed == 0
    compute_survival(cfg, db, now=NOW)
    assert set(surv(db, c)) == {1, 7, 30}


def test_unmerged_commit(cfg, db, repo):
    write(repo, "keep.py", ["base"])
    commit_all(repo, "base", T0 - timedelta(days=1))
    git(repo, "checkout", "-q", "-b", "side")
    write(repo, "side.py", ["x", "y"])
    c = commit_all(repo, "side work" + AI, T0)
    git(repo, "checkout", "-q", "main")
    setup(db, repo)
    collect_all(cfg, db)
    compute_survival(cfg, db, now=NOW)
    s = surv(db, c)
    assert s[7].status == "not_merged"


def test_human_commits_are_not_analyzed(cfg, db, repo):
    write(repo, "keep.py", ["base"])
    c = commit_all(repo, "human", T0)
    setup(db, repo)
    collect_all(cfg, db)
    compute_survival(cfg, db, now=NOW)
    assert surv(db, c) == {}
