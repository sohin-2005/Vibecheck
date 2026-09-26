# Vibecheck MCP server — design

Date: 2026-09-26
Status: approved

## Goal

Let the AI coding agent itself ask Vibecheck for feedback while it works: "am I going in
circles right now?", "what usually goes wrong in this repo?", "what habits lead to good
sessions?", "how could this prompt be better?". Today that feedback only reaches the human,
through the dashboard, `digest` and `coach`.

## Decisions (agreed in brainstorming)

| Question | Decision |
|---|---|
| Delivery | **On demand.** An MCP server the agent calls when it wants to. No hooks and no generated rules files in this phase. |
| Data | **Past sessions plus the live session.** The agent can check the session in progress without running `vibecheck run`. |
| History scope | **All projects, with details only from this one.** Only habit statistics come from other projects. File names, commands and prompt snippets come from the current project only. |
| Transport | **stdio**, started as `vibecheck mcp`, built on the official `mcp` Python SDK (FastMCP). |

Out of this phase: Claude Code hooks, writing into `CLAUDE.md`/`AGENTS.md`, live parsing for
tools other than Claude Code, LLM-backed rewrites inside MCP calls, and any database writes.

## Usage

```bash
claude mcp add vibecheck -- vibecheck mcp
# or, from a checkout:
claude mcp add vibecheck -- uv --directory /path/to/backend run vibecheck mcp
```

Codex CLI and Antigravity register the same command in their MCP config. The server takes its
working directory, or `--project PATH`, as the current project.

## Tools

Every tool returns a short Markdown string for the model to read, capped at about 2,000
characters. All text goes through `Redactor` before it is returned. No tool raises: a failure
comes back as a one-line explanation, for example "No Vibecheck database found — run
`vibecheck init` and `vibecheck run` to enable project lessons."

### `session_health()` — live, no database needed

1. Find the current session file. The folder is `cfg.claude_projects_dir /
   encode(project_dir)`, where `encode` replaces every character that isn't a letter or
   digit with `-` and the match ignores case (the drive letter's case varies). Within it,
   take the `*.jsonl` with the newest modification time. If the folder is missing, fall back
   to the newest file across `claude_projects_dir` whose first event has a `cwd` equal to the
   project directory.
2. Parse it with `vibecheck.ingest.parser.iter_events` (sidechain events included, as in
   ingestion).
3. Build the signal inputs from the events: human prompts, interrupts, failed tool results
   matched to their `ToolUse` by id, and edit paths from `EDIT_TOOLS`. Feed them to the
   existing pure `compute_signals`.
4. Render:
   - one headline: "Looks healthy" or "Signs of struggle"
   - up to four concrete findings, using the digest's wording: "main.py edited 9 times",
     "4 failed PowerShell calls, e.g. `pytest …`", "2 corrections from the user", "an
     interrupt"
   - up to three nudges for the agent, e.g. "Stop editing main.py and re-read the failing
     test output", "Ask the user for the exact test command", "Summarise the plan back to the
     user before more edits"

"Struggle" uses the same weights as the struggle score (`cfg.weights`), with fixed thresholds
on the raw score (see Open parameters). There's no percentile ranking because that needs the
database.

Optional argument `session_id: str | None`: check that session file in this project instead
of the newest one.

### `project_lessons(days: int = 30)` — database, current project only

Match the project by `Project.cwd` or `Project.repo_root` against the project directory,
normalising separators and case. For the project's sessions in the window, using
`collect_signals` and the existing `ToolCall` / `Message` tables:

- the files most often edited over and over, across sessions (top 3)
- the commands that fail most often (top 3, shortened)
- how often sessions reached a commit, and the median prompts it took
- the common first-prompt gaps: share of first prompts with no file named, and share with no
  success criteria
- up to three tips, reusing the rules in `digest._tips`

If the project has no sessions, say so and suggest `vibecheck run`.

### `habits()` — database, all projects, numbers only

Return the stored `Insight` rows (made by `vibecheck insights`) as their titles and numeric
details. The output never contains paths, commands, prompt text or project names, and a test
checks this. Below `INSIGHT_THRESHOLD` sessions, report the progress instead ("12 of 20
sessions needed").

### `critique_prompt(text: str)` — pure, no database

Run `extract_features(text, is_first=True)` and report what's missing: a file named, success
criteria, error text when the prompt talks about a failure. Return a template rewrite from
`template_rewrite` with an empty `RewriteContext`, so it uses `[placeholders]` and never
calls an LLM.

## Structure

```
backend/vibecheck/mcp/
    __init__.py
    server.py      # FastMCP app, tool registration, `run(project_dir)`; thin wrappers only
    locate.py      # encode_project_dir(), find_current_session(): pure path logic
    live.py        # events -> LiveSignals -> findings/nudges (pure functions)
    lessons.py     # project_lessons() and habits() queries -> Markdown
    render.py      # Markdown formatting, length cap, redaction
```

`cli.py` gains `vibecheck mcp [--project PATH]`. The tool functions take plain arguments and
return strings, so they can be tested without an MCP client. `server.py` only wires them up.
Logging goes to stderr, because stdout carries the protocol.

The database is opened lazily, on the first call to a database tool. If it can't be opened,
those tools return the setup hint while `session_health` and `critique_prompt` keep working.

## Dependencies

Add `mcp>=1.2` to `backend/pyproject.toml`. No other new dependencies.

## Privacy

- Output goes into the model's context and so to the model provider. Only redacted text is
  returned.
- Paths, commands and snippets are limited to the current project. `habits` is limited to
  numbers.
- Paths are shown as basenames or relative to the project root, never as absolute paths.
- Nothing is written anywhere, and no network calls are made.

## Testing

- `tests/test_mcp_locate.py`: encoding (Windows and POSIX paths, drive-letter case), picking
  the newest file, the `cwd` fallback, a missing folder.
- `tests/test_mcp_live.py`: a new fixture `tests/fixtures/struggle_session.jsonl` with
  repeated edits, failing Bash calls, a correction and an interrupt. It checks the signals,
  the findings text and the nudges, plus a healthy session (`basic_session.jsonl`) and a file
  with malformed or unknown lines.
- `tests/test_mcp_lessons.py`: a SQLite database from the existing test helpers, with two
  projects. `project_lessons` must not mention the other project's files or commands, and
  `habits` output must contain no paths, commands or prompt text.
- `tests/test_mcp_server.py`: the tool list and names are registered, and a secret in the
  session text comes back as `[REDACTED:…]`.

## Open parameters (defaults, tunable in the code)

- Live struggle headline when the weighted raw score is at least 6, or any single file has
  been edited more than 5 times.
- Output cap: 2,000 characters per tool.
- `project_lessons` window: 30 days.
