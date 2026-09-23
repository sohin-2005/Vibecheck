# PromptLens — Project Specification

A local-first analytics and coaching tool for AI-assisted coding. PromptLens reads your Claude Code session logs and your git history, then tells you what your AI usage costs, where it struggles, how much AI-written code survives, and how to prompt better.

## 1. Overview

### 1.1 The problem

Developers using Claude Code have no visibility into how well it is going. They can't easily answer:

- How much did this week's sessions cost (in tokens or API-equivalent money)?
- Which sessions went smoothly, and which turned into long back-and-forth struggles?
- Does the code Claude writes stay in the codebase, or does most of it get rewritten later?
- Which prompting habits lead to good results, and which lead to wasted time?

### 1.2 The solution

PromptLens is a fitness tracker for AI-assisted coding. It:

- Ingests Claude Code session transcripts that already exist on the developer's machine.
- Links sessions to git commits.
- Computes metrics: cost, turns, struggle score, tool usage.
- Measures code survival: what percentage of AI-written lines still exist after 1, 7 and 30 days.
- Uses an LLM to score prompts and find patterns between prompting habits and outcomes.
- Presents everything in a local dashboard and a weekly report.

### 1.3 Goals

- Works entirely locally by default. No data leaves the machine unless the user chooses a cloud LLM.
- Costs nothing to run (open-source stack, local or free-tier LLMs).
- Honest metrics, with limitations clearly stated.
- Easy to try: one command to ingest, one to open the dashboard, and a demo dataset for people without logs.

### 1.4 Non-goals (for v1)

- Multi-user or team features (listed as a stretch goal).
- Support for tools other than Claude Code (stretch goal).
- Real-time capture (v1 parses files after the fact; hooks are a stretch goal).
- Authentication, cloud hosting, billing.

## 2. User and core use cases

User: a single developer who uses Claude Code on one or more git repositories.

| # | Use case | Output |
|---|---|---|
| U1 | "How much am I using Claude Code?" | Sessions per day, tokens, API-equivalent cost over time |
| U2 | "Which sessions went badly?" | Session list sorted by struggle score, with replay |
| U3 | "Is the AI code any good long-term?" | Survival rate at 1/7/30 days, per repo and file type |
| U4 | "How can I prompt better?" | Prompt scores, patterns, and concrete suggestions |
| U5 | "Summarize my week." | Weekly markdown report |

## 3. Data sources

### 3.1 Claude Code session files

- Location: `~/.claude/projects/<encoded-project-path>/<session-id>.jsonl`
- Format: JSONL — one JSON object per line, each an event.
- The format is not officially documented and can change between versions. Phase 1 includes a discovery step to inspect real files before finalizing the parser (see `docs/FORMAT_NOTES.md`).

Fields you are likely to find (verify against your own files):

| Field | Meaning |
|---|---|
| `type` | Event kind, e.g. user, assistant, summary |
| `sessionId` | Session identifier |
| `uuid`, `parentUuid` | Event IDs forming the conversation chain |
| `timestamp` | ISO timestamp |
| `cwd` | Working directory (maps to a repo) |
| `gitBranch` | Branch at the time |
| `version` | Claude Code version |
| `isSidechain` | Whether the event belongs to a subagent |
| `message.role` | user / assistant |
| `message.model` | Model used (assistant events) |
| `message.content` | String or list of blocks: text, tool_use, tool_result, thinking |
| `message.usage` | input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens |

Important parsing details:

- Tool results usually arrive as user-role events containing `tool_result` blocks. These are NOT human prompts. A "human prompt" is a user event whose content is plain text (or text blocks) and is not a tool result.
- `tool_use` blocks carry `name` (e.g. Read, Edit, Write, Bash, Grep) and `input` (e.g. file_path, old_string, new_string, command).
- `tool_result` blocks may carry `is_error: true`.
- Interruptions typically appear as a user text marker like `[Request interrupted by user...]`. Detect with a configurable pattern.
- Unknown fields and unknown event types must be skipped, never crash the parser.

### 3.2 Git history

Read from each repository referenced by session `cwd` values (resolved to the git root with `git rev-parse --show-toplevel`).

Collected per commit: SHA, author time, message, parent count (to skip merges), files changed, lines added/deleted (`git show --numstat`), and whether the message contains a `Co-Authored-By: Claude` trailer.

Use subprocess calls to the git CLI (simpler and faster than GitPython for `blame --porcelain`).

## 4. Architecture

```
 ~/.claude/projects/*.jsonl        local git repos
            │                             │
            ▼                             ▼
   ┌─────────────────┐          ┌──────────────────┐
   │ Parser + Redact │          │  Git Collector   │
   └────────┬────────┘          └────────┬─────────┘
            └──────────────┬─────────────┘
                           ▼
                  ┌─────────────────┐
                  │   PostgreSQL    │◄──── Metrics engine
                  │                 │◄──── Survival analyzer
                  │                 │◄──── Prompt coach (LLM)
                  └────────┬────────┘◄──── Insights + reports
                           ▼
                  ┌─────────────────┐
                  │  FastAPI (API)  │
                  └────────┬────────┘
                           ▼
                  ┌─────────────────┐
                  │ React dashboard │
                  └─────────────────┘
```

The CLI drives all processing jobs. The API is read-mostly and can also trigger jobs.

### 4.1 Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Packaging | uv (or pip + venv) |
| CLI | Typer + Rich (nice terminal tables) |
| DB | PostgreSQL 16 (Docker Compose) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic |
| API | FastAPI + Pydantic v2 |
| LLM | Provider interface: Ollama (local), Gemini, Groq |
| Frontend | React + Vite + TypeScript + Tailwind + Recharts + TanStack Query |
| Tests | pytest (backend), Vitest (optional, frontend) |
| Lint/format | ruff, prettier |
| CI | GitHub Actions: ruff + pytest |

### 4.2 Repository structure

```
promptlens/
├── CLAUDE.md
├── README.md
├── docker-compose.yml
├── docs/
│   ├── SPEC.md
│   └── FORMAT_NOTES.md
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── promptlens/
│   │   ├── cli.py
│   │   ├── config.py
│   │   ├── db/            (models.py, session.py)
│   │   ├── ingest/        (discover.py, parser.py, redact.py, ingest.py)
│   │   ├── gitdata/       (collector.py, linker.py, survival.py)
│   │   ├── metrics/       (session_metrics.py, struggle.py)
│   │   ├── coach/         (features.py, rubric.py, scorer.py, providers/)
│   │   ├── insights/      (analysis.py, report.py)
│   │   ├── demo/          (generate.py)
│   │   └── api/           (main.py, routes/)
│   └── tests/
│       └── fixtures/
└── frontend/
    ├── package.json
    └── src/ (pages/, components/, api/)
```

## 5. Configuration

File: `~/.promptlens/config.toml` (created by `promptlens init`). Environment variables override values.

```toml
[database]
url = "postgresql+psycopg://promptlens:promptlens@localhost:5432/promptlens"

[sources]
claude_projects_dir = "~/.claude/projects"
include_sidechains = true

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
```

API keys come only from environment variables (`GEMINI_API_KEY`, `GROQ_API_KEY`), never from the config file.

## 6. Data model

All timestamps stored as timestamptz. Store the raw event JSON so the parser can improve later without re-reading files.

Tables: `ingest_state`, `projects`, `sessions`, `raw_events`, `messages`, `tool_calls`, `commits`, `commit_files`, `session_commits`, `line_survival`, `prompt_features`, `prompt_scores`, `insights`. See `backend/promptlens/db/models.py` for the authoritative definitions.

Indexes: `messages(session_id, timestamp)`, `tool_calls(session_id)`, `commits(project_id, authored_at)`, `sessions(started_at)`.

## 7. Module specifications

### 7.1 Discovery (`ingest/discover.py`)
- Walk `claude_projects_dir`, return all `*.jsonl` files with size and mtime.
- Compare with `ingest_state` to find new or changed files.

### 7.2 Parser (`ingest/parser.py`)
- Read line by line. Each line → `json.loads`. Malformed lines are logged and skipped.
- Convert each event into typed models: HumanPrompt, AssistantMessage, ToolUse, ToolResult, Other.
- A user event is a HumanPrompt only if its content is text and not a tool result and not a system/meta injection.
- Assistant events with the same message ID may appear across several lines (streamed content blocks). Deduplicate usage by message ID so tokens are not counted twice.
- Pair `tool_result` blocks with their `tool_use` by `tool_use_id` to fill `is_error`.
- Extract `file_path` from Read/Edit/Write/MultiEdit inputs and `command` from Bash.
- Unknown types → Other, stored in `raw_events` only.

### 7.3 Redaction (`ingest/redact.py`)
Applied to all text before anything is written to the DB. Default patterns (replace with `[REDACTED:<kind>]`): AWS keys, generic API keys (`sk-`, `ghp_`, `gho_`, `xox[baprs]-`, `AIza`), JWTs, `KEY=`/`SECRET=`/`PASSWORD=`/`TOKEN=` assignments, private key blocks, connection strings with passwords. Plus user-defined `extra_patterns`. Must have thorough unit tests.

### 7.4 Ingestion (`ingest/ingest.py`)
- For each new/changed file: resume from `lines_processed`, parse new lines, redact, upsert into projects, sessions, messages, tool_calls, raw_events.
- If a file shrank or its mtime went backwards, reprocess it fully.
- One transaction per file. Upserts keyed on `event_uuid` / `tool_use_id` make re-runs idempotent.
- After ingestion, recompute aggregates for touched sessions.

### 7.5 Git collector (`gitdata/collector.py`)
- For each project with a `repo_root`: `git log --all` since the earliest session date minus 1 day.
- Per commit: `git show --numstat --format= <sha>`. Skip binary files and files matching `ignore_globs`.
- Trailer: case-insensitive `Co-Authored-By: Claude`.
- Incremental: only fetch commits not already in the DB.

### 7.6 Session–commit linker (`gitdata/linker.py`)
Three methods, strongest first:
- **bash_commit** (0.95): session has a Bash call containing `git commit`, and a commit in that repo was authored within 2 minutes after it.
- **trailer** (0.9): commit has the Claude trailer and was authored between session start and session end + window.
- **timestamp** (0.5): commit authored between session start and session end + window, touching at least one file the session edited.

A commit links to at most one session (highest confidence, then closest time).

### 7.7 Session metrics (`metrics/session_metrics.py`)
- `human_turns`, `assistant_turns`, token sums (deduplicated).
- `est_cost_usd`: Σ per model (tokens × price / 1,000,000) from config. Labelled "API-equivalent cost". Null if a model has no price.
- `turns_to_commit`: human turns before the first linked commit.
- `duration_minutes`: active time; gaps > 30 minutes excluded.

### 7.8 Struggle score (`metrics/struggle.py`)
Signals: interrupts, corrections, tool_errors, repeated_edits (Σ max(0, edits_per_file − 3)), turns. Score = Σ weight × signal, mapped to 0–100 by percentile rank across the user's sessions. Raw signals stored for the "why" breakdown.

### 7.9 Survival analysis (`gitdata/survival.py`)
For each non-merge commit C that is AI co-authored or linked to a session, and each checkpoint d where C.time + d ≤ now:
- S = `git rev-list -1 --before=<C.time + d> <default-branch>`. Skip if C is not an ancestor of S ("not merged").
- Lines total = Σ lines_added in `commit_files` (after ignore globs).
- Lines surviving: map paths through renames (`git diff --name-status -M C S`), then `git blame --porcelain -M -C -w S -- path`, count lines attributed to C.
- Cache blame per (S, path). Only compute missing checkpoints.

### 7.10 Prompt features (`coach/features.py`)
Rule-based: char_len, mentions_file, has_error_text, has_code_block, has_success_criteria, is_first_in_session.

### 7.11 LLM prompt coach (`coach/`)
Provider protocol with `complete_json(system, user, schema) -> dict`. Ollama, Gemini, Groq; cloud providers refuse unless `send_to_cloud_confirmed = true`. Scorer selects unscored prompts ≥ `min_prompt_chars`, caches by (text_hash, rubric_version, model), batches, validates with Pydantic, retries once with the error, then falls back to one-at-a-time. Rubric versioned (`v1`).

### 7.12 Insights (`insights/analysis.py`)
Compare outcomes (turns_to_commit, struggle_score, 7-day survival, has_commit) between groups of first prompts: has_context, mentions_file, has_error_text (bugfix only), scope small/medium vs too_large, specificity ≥4 vs ≤2. Medians; min 10 sessions per group; always show n; correlation language.

### 7.13 Weekly report (`insights/report.py`)
`promptlens report --week` writes `reports/YYYY-Www.md`: summary vs previous week, top-3 struggle sessions, 7-day survival, prompt habits, top insights.

## 8. CLI

```
promptlens init | ingest | git | analyze | coach [--limit N] | insights
promptlens report --week | run | stats | serve | demo | reset
```

## 9. API (FastAPI)

All under `/api`. Common query params: `from`, `to`, `project_id`.

| Method | Path | Returns |
|---|---|---|
| GET | /overview | Totals + daily series |
| GET | /projects | Projects with session counts |
| GET | /sessions | Paginated list; sortable |
| GET | /sessions/{id} | Metrics, struggle signals, linked commits |
| GET | /sessions/{id}/timeline | Ordered messages + tool calls |
| GET | /survival | Survival by checkpoint; by project or file_ext |
| GET | /tools | Tool usage counts and error rates |
| GET | /coach/summary | Score distributions, categories, trends |
| GET | /coach/prompts | Scored prompts with suggestions |
| GET | /insights | Latest insights |
| POST | /jobs/{name} | Trigger ingest/git/analyze/coach |
| GET | /jobs/{id} | Job status |

## 10. Dashboard (React)

Overview, Sessions, Session detail, Code survival, Tools, Coach, Settings. Light and dark mode, readable on a laptop screen, no remote images.

## 11. Testing strategy

Fixture-based parser tests; table-driven redaction tests with false-positive checks; ingestion idempotency and incremental append; temp git repos with scripted dates for collector/linker/survival with exact numbers; fake LLM provider incl. malformed responses; insights with known differences and min-group rule; API via TestClient.

## 12. Build plan

- Phase 0 — Setup
- Phase 1 — Discovery and parser
- Phase 2 — Ingestion, redaction and CLI stats
- Phase 3 — API and Overview dashboard
- Phase 4 — Git collection and linking
- Phase 5 — Metrics and struggle score
- Phase 6 — Code survival
- Phase 7 — Prompt coach
- Phase 8 — Insights and weekly report
- Phase 9 — Polish and release

## 13. Risks and limitations

| Risk | Mitigation |
|---|---|
| Session file format changes | Tolerant parser, raw JSON stored, FORMAT_NOTES.md, version recorded |
| Attribution is imperfect | Confidence per link, stated clearly in README |
| Survival confounded | Present as a signal, not a verdict |
| Small sample sizes | Minimum group size, show n, correlation language |
| Secrets in logs | Redaction before storage, local-first, cloud LLM opt-in |
| Cost estimates wrong | User-maintained price table; "API-equivalent" label |
| Employer code privacy | `ignore_projects` config option; never commit real data |

## 14. Stretch goals

Hooks-based real-time capture; MCP server (`get_my_stats`, `get_recent_struggles`, `get_prompt_tips`); precise edit-matching attribution; adapters for other tools; team mode; prompt rewrite suggestions.
