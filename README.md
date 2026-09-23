# PromptLens

**A fitness tracker for AI-assisted coding.** PromptLens reads your Claude Code session logs and your git history, then shows what your AI usage costs, which sessions turn into struggles, how much AI-written code survives, and which prompting habits work for you. It runs locally and stores everything in your own database.

<!-- Screenshot: run `promptlens demo`, open the dashboard, and save a capture as docs/screenshot.png -->

## Why

Claude Code leaves a detailed transcript of every session on your machine, but nothing reads it back to you. You can't easily tell what a week of sessions cost, which ones went in circles, whether the code Claude wrote is still there a month later, or whether "fix it" prompts really are worse than precise ones. PromptLens answers those questions from data you already have.

## Quick start (demo data, no logs needed)

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
git clone <this repo> promptlens && cd promptlens
cd frontend && npm install && npm run build && cd ..
cd backend && uv sync
uv run promptlens demo
PROMPTLENS_DATABASE_URL=sqlite:///$HOME/.promptlens/demo.db uv run promptlens serve
```

Then open http://127.0.0.1:8000. On Windows PowerShell, set the variable with `$env:PROMPTLENS_DATABASE_URL = "sqlite:///$HOME/.promptlens/demo.db"` first.

No uv? `python -m pip install uv` works, then use `python -m uv` in place of `uv`.

## Using it on your own data

```bash
docker compose up -d                 # PostgreSQL 16 on localhost:5432
cd backend
uv run promptlens init               # writes ~/.promptlens/config.toml, runs migrations
uv run promptlens run                # ingest + git + analyze + insights
uv run promptlens stats              # quick terminal summary
uv run promptlens serve              # dashboard at http://127.0.0.1:8000
```

Prefer no Docker? Point PromptLens at SQLite instead. Set `[database] url = "sqlite:///C:/Users/you/.promptlens/promptlens.db"` in the config, or use the `PROMPTLENS_DATABASE_URL` environment variable.

Other commands:

| Command | What it does |
|---|---|
| `promptlens ingest` | Parse new session lines (incremental, safe to re-run) |
| `promptlens git` | Collect commits from the repos your sessions ran in and link them to sessions |
| `promptlens analyze` | Session metrics, struggle scores, code survival, prompt features |
| `promptlens coach [--limit N]` | Score prompts with an LLM (Ollama by default) |
| `promptlens insights` | Recompute habit-vs-outcome comparisons |
| `promptlens report --week` | Write `reports/YYYY-Www.md` |
| `promptlens reset` | Drop and recreate all tables (asks first) |

### Costs

Prices change, so PromptLens ships with none. Add the models you use to `~/.promptlens/config.toml` in USD per million tokens:

```toml
[pricing.models."claude-opus-5"]
input = 0.0        # fill in current prices
output = 0.0
cache_write = 0.0
cache_read = 0.0
```

Costs are labelled **API-equivalent**: subscription users don't pay per token, so treat them as a relative measure.

### Prompt coach

`promptlens coach` uses [Ollama](https://ollama.com) locally by default (`ollama pull llama3.1:8b`). Gemini and Groq are supported, but they send your redacted prompts to a cloud API. They refuse to run unless you set `send_to_cloud_confirmed = true` under `[llm]`, and they read keys only from `GEMINI_API_KEY` / `GROQ_API_KEY`. Re-running only scores new prompts: results are cached by text hash and rubric version.

## How each metric works, and its limits

| Metric | How | Limits |
|---|---|---|
| **Tokens** | Sum of `message.usage` per assistant API message. Claude Code writes one line per content block with the same usage repeated, so usage is deduplicated by message id. | Subagent (sidechain) usage is included unless `include_sidechains = false`. |
| **Active time** | Time between events, skipping gaps longer than 30 minutes. | Reading or thinking time without events is invisible. |
| **Struggle score** | `3×interrupts + 2×corrections + 1×tool errors + 1.5×repeated edits + 0.5×prompts` (weights configurable), then ranked 0–100 against your own sessions. The session page shows the breakdown. | A hard task isn't the same as a bad session. The score is relative to *you*, not an absolute grade. Corrections are detected with regexes. |
| **Session↔commit links** | `bash_commit` (0.95): Claude ran `git commit` within 2 minutes before the commit. `trailer` (0.9): a `Co-Authored-By: Claude` commit during the session or up to 30 minutes after. `timestamp` (0.5): a commit in that window touching a file the session edited. Each commit links to one session. | Human edits in the same commit count as AI lines. |
| **Code survival** | For each AI-linked commit, at 1/7/30 days: take the default branch as it was then, follow renames, `git blame -w -M -C`, and count lines still attributed to the commit. | Deleted code can mean a feature was removed, not that the code was bad. Commits that never reached the default branch are shown as "not merged". |
| **Prompt features** | Regexes for file mentions, error text, code blocks and success criteria. | Heuristic. |
| **Prompt scores** | An LLM applies a versioned rubric: specificity 1–5, context, success criteria, scope and category. | Small local models are noisy scorers. |
| **Insights** | Medians (rates for yes/no outcomes) compared between first-prompt groups, only when each group has at least 10 sessions, with group sizes and a bootstrap 95% interval. | These are correlations, not causes. |

## Privacy

- **What's stored:** a redacted copy of each session event, your prompts and Claude's text replies, tool names and file paths, commit metadata, and computed metrics. Your database stays on your machine.
- **Redaction** runs before anything is written. It catches AWS keys, `sk-`/`ghp_`/`xox*-`/`AIza` API keys, JWTs, `*KEY/SECRET/PASSWORD/TOKEN=` assignments, private key blocks, and passwords in connection strings. You can add your own patterns under `[redaction] extra_patterns`.
- **Local-first:** nothing leaves your machine unless you enable a cloud LLM provider, and those only receive redacted prompt text.
- Skip repos you shouldn't analyze with `[sources] ignore_projects = ["substring-of-path"]`.
- The repo contains only synthetic fixtures and demo data. Never commit a real database.

## What I learned from my own data

_Fill this in after a few weeks. Good candidates are your biggest insight card, your 7-day survival rate, and your most expensive or highest-struggle session type._

## Architecture

```
~/.claude/projects/*.jsonl      local git repos
          │                           │
   Parser + Redact              Git collector ── linker ── survival (blame)
          └──────────┬────────────────┘
               PostgreSQL / SQLite  ◄── metrics, struggle, coach (LLM), insights
                     │
               FastAPI (/api)  ──►  React dashboard (served at /)
```

Stack: Python 3.11, Typer + Rich, SQLAlchemy 2 + Alembic, FastAPI + Pydantic v2, PostgreSQL 16 (SQLite for tests and demo), React + Vite + TypeScript + Tailwind + Recharts + TanStack Query. The full design is in [docs/SPEC.md](docs/SPEC.md), and the session log format findings are in [docs/FORMAT_NOTES.md](docs/FORMAT_NOTES.md).

## Development

```bash
cd backend && uv run pytest            # 126 tests; temp git repos, no network
cd backend && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run dev             # Vite on :5173, proxies /api to :8000
```

## Roadmap

- Real-time capture with Claude Code hooks
- An MCP server (`get_my_stats`, `get_recent_struggles`, `get_prompt_tips`) so Claude can query its own history
- Line-precise attribution by matching Edit/Write content to committed lines
- Adapters for other AI coding tools
- Team mode with anonymized aggregates
- Side-by-side rewrites of weak prompts

## License

MIT
