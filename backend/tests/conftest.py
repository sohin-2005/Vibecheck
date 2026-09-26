import subprocess
from pathlib import Path

import pytest

from vibecheck.config import Config
from vibecheck.db.models import Base
from vibecheck.db.session import get_engine, make_sessionmaker

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


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Keep the CLI's one-time ~/.promptlens move away from the real home directory."""
    import vibecheck.config

    monkeypatch.setattr(vibecheck.config, "LEGACY_HOME_DIR", tmp_path / "no-legacy-home")
