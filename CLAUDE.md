# Vibecheck

Local-first analytics for AI coding sessions (Claude Code, Antigravity; Codex CLI and Aider experimental). Full spec: docs/SPEC.md. Session format notes: docs/FORMAT_NOTES.md.

## Commands
- Start DB: `docker compose up -d`
- Backend tests: `cd backend && uv run pytest`
- Lint: `cd backend && uv run ruff check . && uv run ruff format --check .`
- Frontend dev: `cd frontend && npm run dev`
- Frontend build: `cd frontend && npm run build` (served by `vibecheck serve`)

## Conventions
- Python 3.11, type hints everywhere, Pydantic for external data, SQLAlchemy 2.0 style.
- Every new module gets tests. Parser/redaction/survival changes need fixture-based tests.
- Never hardcode model prices or API keys. Prices come from config; keys from env vars.
- All text is redacted before it is written to the database.
- Parser must never crash on unknown fields or event types.
- New AI tools = a new adapter in `backend/vibecheck/sources/` plus a fixture and tests. Mark it `verified = False` until checked against real logs.
- Team exports must never contain text, paths, commands or ids; `tests/test_team.py` guards this.
- Use `subprocess` with argument lists (no shell=True) for git commands.
- Keep functions small; prefer pure functions for metrics so they're easy to test.
- Models must work on both PostgreSQL (prod) and SQLite (tests, demo): use the portable types in `db/models.py`.

## Workflow
- Work one phase at a time from docs/SPEC.md §12.
- Plan first, then implement, then run tests and lint before saying you're done.
