import shutil

from typer.testing import CliRunner

from promptlens.cli import app
from tests.conftest import FIXTURES

runner = CliRunner()


def env_for(tmp_path):
    projects = tmp_path / "projects" / "-work-demo"
    projects.mkdir(parents=True)
    shutil.copy(FIXTURES / "basic_session.jsonl", projects)
    return {
        "PROMPTLENS_CONFIG": str(tmp_path / "config.toml"),
        "PROMPTLENS_DATABASE_URL": f"sqlite:///{(tmp_path / 'cli.db').as_posix()}",
        "PROMPTLENS_CLAUDE_PROJECTS_DIR": str(tmp_path / "projects"),
    }


def test_init_ingest_stats(tmp_path):
    env = env_for(tmp_path)
    r = runner.invoke(app, ["init"], env=env)
    assert r.exit_code == 0, r.output
    assert (tmp_path / "config.toml").exists()
    r = runner.invoke(app, ["ingest"], env=env)
    assert r.exit_code == 0, r.output
    assert "1 processed" in r.output
    r = runner.invoke(app, ["stats"], env=env)
    assert r.exit_code == 0, r.output
    assert "demo" in r.output
    assert "no price" in r.output


def test_reset_requires_confirmation(tmp_path):
    env = env_for(tmp_path)
    runner.invoke(app, ["init"], env=env)
    r = runner.invoke(app, ["reset"], env=env, input="n\n")
    assert r.exit_code != 0
    r = runner.invoke(app, ["reset", "--yes"], env=env)
    assert r.exit_code == 0, r.output
