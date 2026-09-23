from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from promptlens.db.models import Commit, CommitFile, Project, Session, SessionCommit, ToolCall
from promptlens.gitdata.collector import collect_all, is_ignored, parse_numstat
from promptlens.gitdata.linker import link_all
from tests.conftest import git

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def commit(repo, path, content, msg, when, add=True):
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, date=when.isoformat())
    return git(repo, "rev-parse", "HEAD")


def setup_project(db, repo, started=T0, ended=T0 + timedelta(minutes=20), sid="s1"):
    p = db.scalar(select(Project).where(Project.repo_root == str(repo)))
    if p is None:
        p = Project(cwd=str(repo), repo_root=str(repo), name="repo")
        db.add(p)
        db.flush()
    db.add(Session(id=sid, project_id=p.id, started_at=started, ended_at=ended, models=[]))
    db.commit()
    return p


def test_parse_numstat_handles_renames_and_binary():
    out = "3\t1\tsrc/a.py\n-\t-\timg.png\n2\t0\tsrc/{old => new}/b.py\n1\t1\tx.txt => y.txt\n"
    assert parse_numstat(out) == [
        ("src/a.py", 3, 1),
        ("src/new/b.py", 2, 0),
        ("y.txt", 1, 1),
    ]


def test_ignore_globs():
    globs = ["*.lock", "package-lock.json", "dist/**"]
    assert is_ignored("poetry.lock", globs)
    assert is_ignored("web/package-lock.json", globs)
    assert is_ignored("dist/app/main.js", globs)
    assert not is_ignored("src/dist.py", globs)


def test_collect_commits(cfg, db, repo):
    setup_project(db, repo)
    commit(
        repo,
        "a.py",
        "1\n2\n3\n",
        "feat: a\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
        T0 + timedelta(minutes=5),
    )
    (repo / "bin.dat").write_bytes(b"\x00\x01\x02")
    commit(repo, "yarn.lock", "x\n", "chore: human", T0 + timedelta(minutes=6))
    assert collect_all(cfg, db) == 2
    commits = {c.message.splitlines()[0]: c for c in db.scalars(select(Commit))}
    a = commits["feat: a"]
    assert a.ai_coauthored and a.lines_added == 3 and not a.is_merge
    assert a.authored_at == T0 + timedelta(minutes=5)
    human = commits["chore: human"]
    assert not human.ai_coauthored
    files = db.scalars(select(CommitFile.file_path).where(CommitFile.commit_sha == human.sha)).all()
    assert files == []  # lock ignored, binary skipped
    assert collect_all(cfg, db) == 0  # incremental


def test_collect_skips_commits_long_before_sessions(cfg, db, repo):
    commit(repo, "old.py", "x\n", "ancient", T0 - timedelta(days=10))
    setup_project(db, repo)
    assert collect_all(cfg, db) == 0


def add_tool(db, sid, tid, name, when, file_path=None, command=None):
    db.add(
        ToolCall(
            session_id=sid,
            tool_use_id=tid,
            tool_name=name,
            file_path=file_path,
            command=command,
            timestamp=when,
        )
    )


def links(db):
    return {
        (lk.session_id, lk.commit_sha): (lk.link_method, float(lk.confidence))
        for lk in db.scalars(select(SessionCommit))
    }


def test_link_methods(cfg, db, repo):
    p = setup_project(db, repo)
    # bash_commit: session ran `git commit` right before this commit
    add_tool(
        db, "s1", "t1", "Bash", T0 + timedelta(minutes=10), command='git add . && git commit -m "x"'
    )
    # timestamp: session edited b.py
    add_tool(db, "s1", "t2", "Edit", T0 + timedelta(minutes=2), file_path=str(repo / "b.py"))
    db.commit()
    c_bash = commit(repo, "a.py", "a\n", "via bash", T0 + timedelta(minutes=10, seconds=30))
    c_trailer = commit(
        repo, "c.py", "c\n", "x\n\nCo-Authored-By: Claude", T0 + timedelta(minutes=40)
    )
    c_ts = commit(repo, "b.py", "b\n", "edited file", T0 + timedelta(minutes=45))
    c_unrelated = commit(repo, "z.py", "z\n", "human only", T0 + timedelta(minutes=46))
    c_late = commit(repo, "c.py", "late\n", "y\n\nCo-Authored-By: Claude", T0 + timedelta(hours=3))
    collect_all(cfg, db)
    link_all(cfg, db)
    got = links(db)
    assert got[("s1", c_bash)] == ("bash_commit", 0.95)
    assert got[("s1", c_trailer)] == ("trailer", 0.9)
    assert got[("s1", c_ts)] == ("timestamp", 0.5)
    assert ("s1", c_unrelated) not in got
    assert ("s1", c_late) not in got
    s = db.get(Session, "s1")
    assert s.has_commit
    assert p.id


def test_commit_links_to_one_session_best_confidence(cfg, db, repo):
    setup_project(db, repo, sid="s1")
    setup_project(
        db, repo, sid="s2", started=T0 + timedelta(minutes=5), ended=T0 + timedelta(minutes=30)
    )
    add_tool(db, "s2", "t1", "Bash", T0 + timedelta(minutes=15), command="git commit -am wip")
    add_tool(db, "s1", "t2", "Edit", T0, file_path=str(repo / "a.py"))
    db.commit()
    c = commit(repo, "a.py", "a\n", "wip", T0 + timedelta(minutes=15, seconds=20))
    collect_all(cfg, db)
    link_all(cfg, db)
    got = links(db)
    assert ("s2", c) in got and ("s1", c) not in got


def test_linking_is_idempotent(cfg, db, repo):
    setup_project(db, repo)
    add_tool(db, "s1", "t1", "Bash", T0 + timedelta(minutes=1), command="git commit -m a")
    db.commit()
    commit(repo, "a.py", "a\n", "a", T0 + timedelta(minutes=1, seconds=5))
    collect_all(cfg, db)
    link_all(cfg, db)
    first = links(db)
    link_all(cfg, db)
    assert links(db) == first


def test_turns_to_commit(cfg, db, repo):
    from promptlens.db.models import Message

    setup_project(db, repo)
    for i, minutes in enumerate([0, 3, 30]):
        db.add(
            Message(
                session_id="s1",
                event_uuid=f"m{i}",
                role="user",
                is_human_prompt=True,
                timestamp=T0 + timedelta(minutes=minutes),
            )
        )
    add_tool(db, "s1", "t1", "Bash", T0 + timedelta(minutes=5), command="git commit -m a")
    db.commit()
    commit(repo, "a.py", "a\n", "a", T0 + timedelta(minutes=5, seconds=10))
    collect_all(cfg, db)
    link_all(cfg, db)
    assert db.get(Session, "s1").turns_to_commit == 2
