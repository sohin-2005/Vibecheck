from pathlib import Path

from vibecheck.config import DEFAULT_CONFIG_TOML, load_config


def test_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("VIBECHECK_DATABASE_URL", raising=False)
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.database_url.startswith("postgresql+psycopg://")
    assert cfg.survival_checkpoints_days == [1, 7, 30]
    assert cfg.weights["interrupts"] == 3.0
    assert cfg.pricing == {}
    assert cfg.llm_provider == "ollama"
    assert cfg.send_to_cloud_confirmed is False


def test_file_values_override_defaults(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[git]
commit_link_window_minutes = 45
[pricing.models."claude-x"]
input = 3.0
output = 15.0
cache_write = 3.75
cache_read = 0.3
[struggle]
weights = { interrupts = 5.0 }
""",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.commit_link_window_minutes == 45
    assert cfg.pricing["claude-x"].output == 15.0
    assert cfg.weights["interrupts"] == 5.0
    assert cfg.weights["turns"] == 0.5  # untouched default kept


def test_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECHECK_DATABASE_URL", "sqlite:///x.db")
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.database_url == "sqlite:///x.db"


def test_default_toml_parses(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    cfg = load_config(p)
    assert cfg.claude_projects_dir == Path("~/.claude/projects").expanduser()


def test_legacy_home_is_moved_and_paths_rewritten(tmp_path):
    from vibecheck.config import migrate_legacy_home

    old, new = tmp_path / ".promptlens", tmp_path / ".vibecheck"
    old.mkdir()
    (old / "dev.db").write_bytes(b"db")
    (old / "config.toml").write_text(
        f'[database]\nurl = "sqlite:///{old.as_posix()}/dev.db"\n'
        '# url = "postgresql+psycopg://promptlens:promptlens@localhost:5432/promptlens"\n',
        encoding="utf-8",
    )
    assert migrate_legacy_home(old, new) is True
    assert not old.exists() and (new / "dev.db").read_bytes() == b"db"
    text = (new / "config.toml").read_text("utf-8")
    assert f"sqlite:///{new.as_posix()}/dev.db" in text
    assert "vibecheck:vibecheck@localhost:5432/vibecheck" in text and "promptlens" not in text


def test_legacy_home_left_alone_when_new_home_exists(tmp_path):
    from vibecheck.config import migrate_legacy_home

    old, new = tmp_path / ".promptlens", tmp_path / ".vibecheck"
    old.mkdir()
    new.mkdir()
    assert migrate_legacy_home(old, new) is False
    assert old.exists()
    assert migrate_legacy_home(tmp_path / "missing", tmp_path / "other") is False
