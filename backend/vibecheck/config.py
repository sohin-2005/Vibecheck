"""Configuration loading: defaults < ~/.vibecheck/config.toml < environment variables."""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HOME_DIR = Path("~/.vibecheck").expanduser()
LEGACY_HOME_DIR = Path("~/.promptlens").expanduser()  # the project was called PromptLens
DEFAULT_CONFIG_PATH = HOME_DIR / "config.toml"

DEFAULT_CONFIG_TOML = r"""[database]
url = "postgresql+psycopg://vibecheck:vibecheck@localhost:5432/vibecheck"

[sources]
claude_projects_dir = "~/.claude/projects"
include_sidechains = true
# Substrings of project cwd values to skip entirely (e.g. employer repos).
ignore_projects = []
# Which AI coding tools to read. claude-code and antigravity are verified against real logs;
# codex and aider are experimental (built from their documented formats).
tools = ["claude-code", "antigravity", "codex", "aider"]
antigravity_dirs = ["~/.gemini/antigravity/brain", "~/.gemini/antigravity-ide/brain"]
codex_dir = "~/.codex/sessions"
# Aider keeps .aider.chat.history.md in each repo; known project repos are checked automatically.
aider_dirs = []

[git]
commit_link_window_minutes = 30
survival_checkpoints_days = [1, 7, 30]
ignore_globs = ["*.lock", "package-lock.json", "*.min.js", "dist/**", "build/**"]

[pricing]
# Fill in current prices yourself (USD per million tokens). Do not hardcode in code.
# [pricing.models."<model-id>"]
# input = 0.0
# output = 0.0
# cache_write = 0.0
# cache_read = 0.0

[struggle]
correction_patterns = ["\\bno\\b[, ]", "that'?s wrong", "didn'?t work", "still (fails|broken|not)", "try again", "revert"]
interrupt_pattern = "\\[Request interrupted by user"
weights = { interrupts = 3.0, corrections = 2.0, tool_errors = 1.0, repeated_edits = 1.5, turns = 0.5 }

[redaction]
enabled = true
extra_patterns = []

[llm]
provider = "ollama"          # ollama | gemini | groq
model = "llama3.1:8b"
batch_size = 15
min_prompt_chars = 20
send_to_cloud_confirmed = false   # must be true to use gemini/groq
ollama_url = "http://localhost:11434"
"""


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input: float = 0.0
    output: float = 0.0
    cache_write: float = 0.0
    cache_read: float = 0.0


@dataclass
class Config:
    database_url: str = "postgresql+psycopg://vibecheck:vibecheck@localhost:5432/vibecheck"
    claude_projects_dir: Path = field(
        default_factory=lambda: Path("~/.claude/projects").expanduser()
    )
    include_sidechains: bool = True
    ignore_projects: list[str] = field(default_factory=list)
    tools: list[str] = field(
        default_factory=lambda: ["claude-code", "antigravity", "codex", "aider"]
    )
    antigravity_dirs: list[Path] = field(
        default_factory=lambda: [
            Path("~/.gemini/antigravity/brain").expanduser(),
            Path("~/.gemini/antigravity-ide/brain").expanduser(),
        ]
    )
    codex_dir: Path = field(default_factory=lambda: Path("~/.codex/sessions").expanduser())
    aider_dirs: list[Path] = field(default_factory=list)
    commit_link_window_minutes: int = 30
    survival_checkpoints_days: list[int] = field(default_factory=lambda: [1, 7, 30])
    ignore_globs: list[str] = field(
        default_factory=lambda: ["*.lock", "package-lock.json", "*.min.js", "dist/**", "build/**"]
    )
    pricing: dict[str, ModelPrice] = field(default_factory=dict)
    correction_patterns: list[str] = field(
        default_factory=lambda: [
            r"\bno\b[, ]",
            r"that'?s wrong",
            r"didn'?t work",
            r"still (fails|broken|not)",
            r"try again",
            r"revert",
        ]
    )
    interrupt_pattern: str = r"\[Request interrupted by user"
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "interrupts": 3.0,
            "corrections": 2.0,
            "tool_errors": 1.0,
            "repeated_edits": 1.5,
            "turns": 0.5,
        }
    )
    redaction_enabled: bool = True
    redaction_extra_patterns: list[str] = field(default_factory=list)
    llm_provider: str = "ollama"
    llm_model: str = "llama3.1:8b"
    llm_batch_size: int = 15
    min_prompt_chars: int = 20
    send_to_cloud_confirmed: bool = False
    ollama_url: str = "http://localhost:11434"
    config_path: Path | None = None


def _apply_toml(cfg: Config, data: dict[str, Any]) -> None:
    db = data.get("database", {})
    src = data.get("sources", {})
    git = data.get("git", {})
    struggle = data.get("struggle", {})
    red = data.get("redaction", {})
    llm = data.get("llm", {})

    cfg.database_url = db.get("url", cfg.database_url)
    if "claude_projects_dir" in src:
        cfg.claude_projects_dir = Path(src["claude_projects_dir"]).expanduser()
    cfg.include_sidechains = src.get("include_sidechains", cfg.include_sidechains)
    cfg.ignore_projects = list(src.get("ignore_projects", cfg.ignore_projects))
    cfg.tools = list(src.get("tools", cfg.tools))
    if "antigravity_dirs" in src:
        cfg.antigravity_dirs = [Path(d).expanduser() for d in src["antigravity_dirs"]]
    if "codex_dir" in src:
        cfg.codex_dir = Path(src["codex_dir"]).expanduser()
    cfg.aider_dirs = [Path(d).expanduser() for d in src.get("aider_dirs", [])]
    cfg.commit_link_window_minutes = int(
        git.get("commit_link_window_minutes", cfg.commit_link_window_minutes)
    )
    cfg.survival_checkpoints_days = [
        int(d) for d in git.get("survival_checkpoints_days", cfg.survival_checkpoints_days)
    ]
    cfg.ignore_globs = list(git.get("ignore_globs", cfg.ignore_globs))
    for model, prices in data.get("pricing", {}).get("models", {}).items():
        cfg.pricing[model] = ModelPrice(**{k: float(v) for k, v in prices.items()})
    cfg.correction_patterns = list(struggle.get("correction_patterns", cfg.correction_patterns))
    cfg.interrupt_pattern = struggle.get("interrupt_pattern", cfg.interrupt_pattern)
    cfg.weights.update({k: float(v) for k, v in struggle.get("weights", {}).items()})
    cfg.redaction_enabled = red.get("enabled", cfg.redaction_enabled)
    cfg.redaction_extra_patterns = list(red.get("extra_patterns", cfg.redaction_extra_patterns))
    cfg.llm_provider = llm.get("provider", cfg.llm_provider)
    cfg.llm_model = llm.get("model", cfg.llm_model)
    cfg.llm_batch_size = int(llm.get("batch_size", cfg.llm_batch_size))
    cfg.min_prompt_chars = int(llm.get("min_prompt_chars", cfg.min_prompt_chars))
    cfg.send_to_cloud_confirmed = bool(
        llm.get("send_to_cloud_confirmed", cfg.send_to_cloud_confirmed)
    )
    cfg.ollama_url = llm.get("ollama_url", cfg.ollama_url)


def _apply_env(cfg: Config) -> None:
    env = os.environ
    if v := env.get("VIBECHECK_DATABASE_URL"):
        cfg.database_url = v
    if v := env.get("VIBECHECK_CLAUDE_PROJECTS_DIR"):
        cfg.claude_projects_dir = Path(v).expanduser()
    if v := env.get("VIBECHECK_TOOLS"):
        cfg.tools = [t.strip() for t in v.split(",") if t.strip()]
    if v := env.get("VIBECHECK_LLM_PROVIDER"):
        cfg.llm_provider = v
    if v := env.get("VIBECHECK_LLM_MODEL"):
        cfg.llm_model = v
    if v := env.get("VIBECHECK_OLLAMA_URL"):
        cfg.ollama_url = v


def config_path_from_env() -> Path:
    return Path(os.environ.get("VIBECHECK_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()


def load_config(path: Path | None = None) -> Config:
    path = path or config_path_from_env()
    cfg = Config(config_path=path)
    if path.exists():
        with path.open("rb") as f:
            _apply_toml(cfg, tomllib.load(f))
    _apply_env(cfg)
    return cfg


def write_default_config(path: Path) -> bool:
    """Create the config file if missing. Returns True if it was created."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    return True


def migrate_legacy_home(old: Path | None = None, new: Path | None = None) -> bool:
    """Move a pre-rename ~/.promptlens to ~/.vibecheck once. Returns True if it moved."""
    old = old or LEGACY_HOME_DIR
    new = new or HOME_DIR
    if not old.is_dir() or new.exists():
        return False
    shutil.move(str(old), str(new))
    cfg_file = new / "config.toml"
    if cfg_file.exists():
        text = cfg_file.read_text(encoding="utf-8")
        legacy_pg = "promptlens:promptlens@localhost:5432/promptlens"
        pairs = [(old.as_posix(), new.as_posix()), (str(old), str(new))]
        pairs.append((legacy_pg, legacy_pg.replace("promptlens", "vibecheck")))
        for a, b in pairs:
            text = text.replace(a, b)
        cfg_file.write_text(text, encoding="utf-8")
    return True
