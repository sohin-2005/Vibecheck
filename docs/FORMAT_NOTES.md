# Claude Code session format notes

Findings from inspecting real session files (Claude Code 2.1.x, September 2026, 3 sessions, ~5,700 events).
Re-run `python -m vibecheck.ingest.survey` to check against your own files.

## Layout

- `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` — one file per session.
- `<session-id>/` sibling folders may hold subagent transcripts (`subagents/*.jsonl`) and other JSON. Discovery walks recursively; the `sessionId` inside each event decides the session.

## Event types seen

| type | Notes |
|---|---|
| `user` | Human prompts **and** tool results. Has `uuid`, `parentUuid`, `timestamp`, `cwd`, `gitBranch`, `version`, `isSidechain`, `sessionId`. |
| `assistant` | One line **per content block**. `message.id` repeats across lines; `message.usage` is identical on every line of the same id → dedupe by `message.id` (keep last). |
| `attachment`, `system`, `queue-operation`, `mode`, `custom-title`, `ai-title`, `last-prompt`, `bridge-session`, `atis-latch`, `frame-link`, `file-history-snapshot`, `agent-name`, `artifact-*` | Metadata. Stored in `raw_events` only. `custom-title` / `ai-title` give a session title. Some have no `uuid` or `timestamp`. |

## Human prompt rules

A `user` event is a human prompt when all hold:

- `toolUseResult` is absent and content has no `tool_result` blocks.
- `isMeta` is not true (skill bodies, "Continue from where you left off" injections).
- `origin.kind`, if present, is `human` (task notifications use `task-notification`).
- Text does not start with `<task-notification>`, `<command-`, `<local-command-` or `<system-reminder>`.
- It is not an interrupt marker.

Content is either a string or a list of `text` blocks.

## Interrupts

`[Request interrupted by user]` and `[Request interrupted by user for tool use]` arrive as user text blocks. They are counted as interrupts, not prompts.

## Tool calls

- `tool_use` blocks: `id`, `name`, `input`. `input.file_path` for Read/Edit/Write/MultiEdit/NotebookEdit; `input.command` for Bash/PowerShell.
- `tool_result` blocks: `tool_use_id`, `content`, `is_error` (bool). Errors often start with `Exit code N`.

## Usage

`message.usage` has `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, plus nested extras (`cache_creation`, `iterations`, `server_tool_use`) we ignore.

## Other

- `gitBranch` can be `HEAD` (detached) or empty.
- Synthetic assistant messages (`model: "<synthetic>"`, API errors) exist; they carry zero usage.

---

# Other tools

## Google Antigravity (verified, September 2026)

- `~/.gemini/antigravity/brain/<conversation-id>/.system_generated/logs/transcript_full.jsonl` (also `transcript.jsonl`, identical in the one sample; only `_full` is read). `~/.gemini/antigravity-ide/brain` may hold more.
- One JSON object per step: `step_index`, `source` (`USER_EXPLICIT` | `MODEL`), `type`, `status`, `created_at`, `content`.
- Seen types: `USER_INPUT` (content wraps the prompt in `<USER_REQUEST>…</USER_REQUEST>` plus metadata blocks) and `PLANNER_RESPONSE`. Other model step types are assumed to be tool steps; `status` ERROR/FAILED marks a failure.
- No working directory, git branch, model id or token usage is logged. Conversations are also kept in `conversations/<id>.db` (SQLite, not read).

## OpenAI Codex CLI (experimental, not yet verified)

Built from the documented rollout format: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, lines `{"timestamp", "type", "payload"}` with `session_meta` (id, cwd, git, cli_version), `turn_context` (cwd, model), `response_item` (message / function_call / custom_tool_call / *_output) and `event_msg` (`token_count` with `info.last_token_usage`, `turn_aborted`). User messages starting with `<environment_context>` or `<user_instructions>` are treated as meta. `apply_patch` inputs give per-file added lines.

## Aider (experimental, not yet verified)

`.aider.chat.history.md` in a repo: `# aider chat started at <local time>` starts a session, `#### ` lines are prompts, `> ` lines are status output (`Tokens: 2.4k sent, 310 received`, `Applied edit to <file>`, `Commit <sha> …`), and everything else is the model reply, including SEARCH/REPLACE blocks. Only session start times exist.

## Not supported

Cursor and Windsurf keep chats in VS Code-style `state.vscdb` SQLite blobs with undocumented, frequently changing schemas. Copilot doesn't store transcripts locally in a readable form.
