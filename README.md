# Vibecheck

**A fitness tracker for AI-assisted coding.** Vibecheck reads the session logs your AI coding tools leave on your machine (Claude Code, Antigravity, and experimentally Codex CLI and Aider) together with your git history. It shows what your AI usage costs, which sessions turn into struggles and why, how much AI-written code survives, and how your prompts could have been better. It runs locally, and your data stays in your own database.

<!-- Screenshot: run `vibecheck demo`, open the dashboard, and save a capture as docs/screenshot.png -->

## Why

AI coding tools keep a detailed transcript of every session, but nothing reads it back to you. You can't easily tell:
- what a week of sessions cost
- which sessions went in circles, and why
- whether the code the AI wrote is still there a month later
- how a vague prompt could have been phrased

Vibecheck answers those questions from data you already have, and it's useful from your first session.

## What you get

- **A day-one digest.** Your hardest session this week, what went wrong in concrete terms, and specific tips. For example: "main.py was edited 64 times", "15 PowerShell calls failed, e.g. `pytest …`", "Name the file in your first prompt". This works from a single session.
- **Prompt rewrites.** "You wrote" next to "Could have been" for weak prompts. The better version is filled in with hindsight: the files the AI ended up editing and the command that failed. It uses a local LLM when available, otherwise a template.
- **Edit-matched code survival.** How many of the lines the AI's edit tools actually wrote are still there after 1, 7 and 30 days. Lines you added to the same commit don't count as AI lines.
- **Usage and cost:** sessions, active hours, tokens and API-equivalent cost, per project and per tool.
- **Struggle scores** with a "why" breakdown and a step-by-step replay of every session.
- **Habit insights:** "Sessions whose first prompt named a file reached a commit in 4 prompts vs 9", once you have enough sessions.
- **Team mode:** share anonymized weekly aggregates (never prompts or code) and compare week by week.
- **`vibecheck findings`:** drafts a "What I learned" write-up from your real numbers.

## Supported tools

| Tool | Where logs live | Status |
|---|---|---|
| Claude Code | `~/.claude/projects/*/*.jsonl` | Verified against real logs |
| Google Antigravity | `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript_full.jsonl` | Verified against a real log. No token counts or working directory are logged, so there's no cost or project for these sessions. |
| OpenAI Codex CLI | `~/.codex/sessions/**/rollout-*.jsonl` | **Experimental:** built from the documented format, not yet checked against real files |
| Aider | `.aider.chat.history.md` in each repo | **Experimental:** built from the documented format. Only session start times are logged. |
| Cursor, Windsurf, Copilot | Stored in internal databases, or not stored locally | Not supported. There's no stable file format to read. |

Adding a tool means writing one adapter in `backend/vibecheck/sources/` that turns its log format into Vibecheck events. Everything downstream (metrics, survival, coach, digest, team) works unchanged. Choose which tools to read with `[sources] tools = [...]` in the config.

## Quick start with demo data

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
git clone <this repo> vibecheck && cd vibecheck
cd frontend && npm install && npm run build && cd ..
cd backend && uv sync
uv run vibecheck demo
VIBECHECK_DATABASE_URL=sqlite:///$HOME/.vibecheck/demo.db uv run vibecheck serve
```

Then open http://127.0.0.1:8000.

On Windows PowerShell 5.1 (no `&&`), run each line separately:

```powershell
cd frontend; npm install; npm run build; cd ..
cd backend; python -m uv sync
python -m uv run vibecheck demo
$env:VIBECHECK_DATABASE_URL = "sqlite:///$($HOME -replace '\\','/')/.vibecheck/demo.db"
python -m uv run vibecheck serve
```

If `uv` isn't found, run the installed commands directly: `.\.venv\Scripts\vibecheck.exe demo` and so on.

## Using it on your own data

```bash
docker compose up -d                 # PostgreSQL 16 on localhost:5432 (or use SQLite, below)
cd backend
uv run vibecheck init               # writes ~/.vibecheck/config.toml, runs migrations
uv run vibecheck run                # ingest + git + analyze + insights
uv run vibecheck digest             # your hardest recent session and what went wrong
uv run vibecheck serve              # dashboard at http://127.0.0.1:8000
```

No Docker? Set `[database] url = "sqlite:///C:/Users/you/.vibecheck/vibecheck.db"` in the config, or set the `VIBECHECK_DATABASE_URL` environment variable.

| Command | What it does |
|---|---|
| `vibecheck ingest` | Read new session data from every enabled tool (incremental, safe to re-run) |
| `vibecheck git` | Collect commits from the repos your sessions ran in and link them to sessions |
| `vibecheck analyze` | Session metrics, struggle scores, code survival, prompt features |
| `vibecheck digest [--days N]` | Hardest recent session, what went wrong, tips |
| `vibecheck coach [--rewrite]` | Score prompts with an LLM; `--rewrite` also rewrites the weakest ones |
| `vibecheck insights` | Recompute habit-vs-outcome comparisons |
| `vibecheck findings [--out FILE]` | Draft your "What I learned" section from your numbers |
| `vibecheck report --week` | Write `reports/YYYY-Www.md` |
| `vibecheck team export / import / push` | Share weekly aggregates with a team (see below) |
| `vibecheck stats` | Quick terminal summary |
| `vibecheck mcp [--project PATH]` | Run the MCP server so your AI coding agent can ask for feedback (see below) |
| `vibecheck reset` | Drop and recreate all tables (asks first) |

### Costs

Prices change, so Vibecheck ships with none. Add the models you use to `~/.vibecheck/config.toml` in USD per million tokens:

```toml
[pricing.models."claude-opus-5"]
input = 0.0        # fill in current prices
output = 0.0
cache_write = 0.0
cache_read = 0.0
```

Costs are labelled **API-equivalent**: subscription users don't pay per token, so treat them as a relative measure. Sessions from tools that don't log tokens show no cost rather than $0.

### Prompt coach and rewrites

`vibecheck coach` uses [Ollama](https://ollama.com) locally by default (`ollama pull llama3.1:8b`). Gemini and Groq are supported too, but they send your redacted prompts to a cloud API. They refuse to run unless you set `send_to_cloud_confirmed = true` under `[llm]`, and they read keys only from `GEMINI_API_KEY` / `GROQ_API_KEY`.

Rewrites work without any LLM. The template version fills in the files the AI actually edited after your prompt and a short command that failed, and puts `[placeholders]` wherever the logs can't know the answer. With an LLM configured, the rewrite is written by the model and falls back to the template if the model fails.

### Team mode

1. The team lead picks a shared secret and starts the server with it: `VIBECHECK_TEAM_TOKEN=... vibecheck serve --host 0.0.0.0`.
2. Each teammate sets the same `VIBECHECK_TEAM_TOKEN` and runs `vibecheck team push --url http://lead-host:8000 --member alex`.
3. Without a network, share files instead: `vibecheck team export --member alex --out alex.json`, then the lead runs `vibecheck team import alex.json`.

An export contains, per ISO week, only counts, rates and medians: sessions, active hours, tokens, commit rate, median struggle, tool error rate, 7-day survival, prompt specificity and a context share. It never contains prompts, replies, code, file paths, commands, commit messages or session ids. Project names are hashed unless you pass `--include-projects`. The receiving endpoint is off unless the server sets a token.

### Feedback for your AI agent (MCP)

`vibecheck mcp` is an [MCP](https://modelcontextprotocol.io) server. Your coding agent can call it while it works:

| Tool | What the agent gets | Needs the database? |
|---|---|---|
| `session_health` | How the current session is going (files edited over and over, failing commands, corrections) and what to do next | No, it reads the live session log |
| `project_lessons` | What usually goes wrong in this repo: re-edited files, failing commands, tips | Yes (`vibecheck run`) |
| `habits` | Prompting habits that led to better sessions, across all projects, numbers only | Yes |
| `critique_prompt` | What a request is missing, plus a sharper version with `[placeholders]` | No |

Register it once with Claude Code:

```bash
claude mcp add vibecheck -- vibecheck mcp
# from a checkout without the command on PATH (Windows):
claude mcp add vibecheck -- C:\path\to\backend\.venv\Scripts\vibecheck.exe mcp
```

Codex CLI and Antigravity take the same command in their MCP settings. The project is the directory the agent starts the server in, or `--project PATH`.

Everything the tools return is redacted and goes into the agent's context, so it is sent to your model provider. File names and commands only ever come from the current project, and `habits` returns numbers only. The server never writes anything. `session_health` reads Claude Code sessions only.

## How each metric works, and its limits

| Metric | How | Limits |
|---|---|---|
| **Tokens** | Sum of usage per model call, deduplicated (Claude Code repeats usage on every streamed line). | Antigravity logs no usage. Aider reports rounded counts. |
| **Active time** | Time between events, skipping gaps longer than 30 minutes. | Reading or thinking time without events is invisible. Aider logs no per-message times. |
| **Struggle score** | `3×interrupts + 2×corrections + 1×tool errors + 1.5×repeated edits + 0.5×prompts` (weights configurable), ranked 0–100 against your own sessions. Corrections are only looked for in what you typed, not in pasted documents. | A hard task isn't a bad session. The score is relative to *you*. |
| **Digest** | The session with the highest raw struggle score in the period, explained with its real prompts, failing commands and files, plus rule-based tips. | Tips are heuristics, not a diagnosis. |
| **Session↔commit links** | `bash_commit` (0.95): the AI ran `git commit` within 2 minutes before the commit. `trailer` (0.9): a `Co-Authored-By: Claude` commit during the session or up to 30 minutes after. `timestamp` (0.5): a commit in that window touching a file the session edited. Each commit links to one session. | Links are evidence, not proof. |
| **Code survival** | At 1/7/30 days: take the default branch as it was then, follow renames, `git blame -w -M -C`. **Edit-matched:** only count the commit's added lines that match (ignoring whitespace) code the linked session's edit tools wrote, skipping trivial lines like `}`. **Whole-commit** is the fallback when no edit content was logged. | Deleted code can mean a feature was removed, not that the code was bad. A human line identical to an AI line counts as AI. |
| **Prompt features** | Regexes for file mentions, error text, code blocks and success criteria. | Heuristic. |
| **Prompt scores** | An LLM applies a versioned rubric: specificity 1–5, context, success criteria, scope and category. | Small local models are noisy scorers. |
| **Insights** | Medians (rates for yes/no outcomes) compared between first-prompt groups, only when each group has ≥10 sessions, with group sizes and a bootstrap 95% interval. | Correlations, not causes. |

## Privacy

- **What's stored:** a redacted copy of each session event, your prompts and the AI's text replies, tool names, file paths, and code written by edit tools (for attribution), plus commit metadata and computed metrics. Your database stays on your machine.
- **Redaction** runs before anything is written. It catches AWS keys, `sk-`/`ghp_`/`xox*-`/`AIza` API keys, JWTs, `*KEY/SECRET/PASSWORD/TOKEN=` assignments, private key blocks, and passwords in connection strings. You can add your own patterns under `[redaction] extra_patterns`.
- **Local-first:** nothing leaves your machine unless you enable a cloud LLM provider, which receives redacted prompt text only, or push team aggregates, which contain no text at all.
- Skip repos you shouldn't analyze with `[sources] ignore_projects = ["substring-of-path"]`.
- The repo contains only synthetic fixtures and demo data. Never commit a real database.

## What I learned from my own data

_After a few weeks of use, run `vibecheck findings --out docs/FINDINGS.md` and replace this paragraph with the parts worth keeping. The draft states facts from your data: where your time went, your biggest source of friction, your most error-prone tool, survival and prompt habits. It warns you when there are too few sessions to trust._

## Architecture

```
AI tool logs (Claude Code, Antigravity, Codex, Aider)      local git repos
          │  one adapter per tool                                │
   Parser + Redact  ─────────────────────────────  collector ── linker ── survival (blame + edit matching)
          └───────────────────────┬──────────────────────────────┘
                   PostgreSQL / SQLite  ◄── metrics, struggle, digest, coach + rewrites, insights, team
                          │
                    FastAPI (/api)  ──►  React dashboard (served at /)
```

Stack: Python 3.11, Typer + Rich, SQLAlchemy 2 + Alembic, FastAPI + Pydantic v2, PostgreSQL 16 (SQLite for tests and demo), React + Vite + TypeScript + Tailwind + Recharts + TanStack Query. The design is in [docs/SPEC.md](docs/SPEC.md), and the log format findings are in [docs/FORMAT_NOTES.md](docs/FORMAT_NOTES.md).

## Development

```bash
cd backend && uv run pytest            # temp git repos, fixtures per tool, no network
cd backend && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run dev             # Vite on :5173, proxies /api to :8000
```

## Roadmap

- Verify the Codex CLI and Aider adapters against real logs
- Real-time capture with tool hooks
- An MCP server (`get_my_stats`, `get_recent_struggles`, `get_prompt_tips`) so the AI can query its own history
- A hosted team server with per-member tokens

## License

MIT
