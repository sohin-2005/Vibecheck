import subprocess
from pathlib import Path

import pytest

from promptlens.config import Config
from promptlens.db.models import Base
from promptlens.db.session import get_engine, make_sessionmaker

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db_url(tmp_path) -> str:
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    Base.metadata.create_all(get_engine(url))
    return url


@pytest.fixture
def db(db_url):
    s = make_sessionmaker(db_url)()
    yield s
    s.close()


@pytest.fixture
def cfg(db_url, tmp_path) -> Config:
    c = Config(
        database_url=db_url,
        claude_projects_dir=tmp_path / "projects",
        antigravity_dirs=[],
        codex_dir=tmp_path / "no-codex",
        aider_dirs=[],
    )
    c.claude_projects_dir.mkdir()
    return c


def git(repo: Path, *args: str, date: str | None = None) -> str:
    env = None
    if date:
        import os

        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "Tester")
    git(r, "config", "commit.gpgsign", "false")
    return r
