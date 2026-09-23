from pathlib import Path

from promptlens.config import DEFAULT_CONFIG_TOML, load_config


def test_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMPTLENS_DATABASE_URL", raising=False)
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
    monkeypatch.setenv("PROMPTLENS_DATABASE_URL", "sqlite:///x.db")
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.database_url == "sqlite:///x.db"


def test_default_toml_parses(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    cfg = load_config(p)
    assert cfg.claude_projects_dir == Path("~/.claude/projects").expanduser()
