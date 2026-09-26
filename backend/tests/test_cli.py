import shutil

from typer.testing import CliRunner

from tests.conftest import FIXTURES
from vibecheck.cli import app

runner = CliRunner()


def env_for(tmp_path):
    projects = tmp_path / "projects" / "-work-demo"
    projects.mkdir(parents=True)
    shutil.copy(FIXTURES / "basic_session.jsonl", projects)
    return {
        "VIBECHECK_CONFIG": str(tmp_path / "config.toml"),
        "VIBECHECK_DATABASE_URL": f"sqlite:///{(tmp_path / 'cli.db').as_posix()}",
        "VIBECHECK_CLAUDE_PROJECTS_DIR": str(tmp_path / "projects"),
        "VIBECHECK_TOOLS": "claude-code",
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


def test_team_export_and_import(tmp_path):
    env = env_for(tmp_path)
    runner.invoke(app, ["init"], env=env)
    runner.invoke(app, ["ingest"], env=env)
    out = tmp_path / "alex.json"
    r = runner.invoke(
        app, ["team", "export", "--member", "alex", "--weeks", "600", "--out", str(out)], env=env
    )
    assert r.exit_code == 0, r.output
    assert "Fix the login bug" not in out.read_text(encoding="utf-8")
    r = runner.invoke(app, ["team", "import", str(out)], env=env)
    assert r.exit_code == 0 and "Imported 1 week" in r.output


def test_mcp_help(tmp_path):
    r = runner.invoke(app, ["mcp", "--help"], env=env_for(tmp_path))
    assert r.exit_code == 0, r.output
    assert "stdio" in r.stdout


def test_migration_message_goes_to_stderr(tmp_path, monkeypatch):
    import vibecheck.config

    legacy = tmp_path / ".promptlens"
    legacy.mkdir()
    monkeypatch.setattr(vibecheck.config, "LEGACY_HOME_DIR", legacy)
    monkeypatch.setattr(vibecheck.config, "HOME_DIR", tmp_path / ".vibecheck")
    r = runner.invoke(app, ["mcp", "--help"], env=env_for(tmp_path))
    assert r.exit_code == 0, r.output
    assert "Moved" not in r.stdout
    assert "Moved" in r.stderr
