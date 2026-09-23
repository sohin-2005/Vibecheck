"""PromptLens command-line interface."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from promptlens.config import Config, config_path_from_env, load_config, write_default_config
from promptlens.db.models import Project, Session
from promptlens.db.session import make_sessionmaker, reset_database, run_migrations

app = typer.Typer(help="Local-first analytics for Claude Code sessions.", no_args_is_help=True)
console = Console()


def _cfg() -> Config:
    return load_config()


def _db(cfg: Config):  # type: ignore[no-untyped-def]
    return make_sessionmaker(cfg.database_url)()


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING)


@app.command()
def init() -> None:
    """Create the config file, check the DB connection and run migrations."""
    path = config_path_from_env()
    if write_default_config(path):
        console.print(f"Created config at [bold]{path}[/]")
    else:
        console.print(f"Config already exists at {path}")
    cfg = _cfg()
    try:
        run_migrations(cfg.database_url)
    except Exception as e:  # noqa: BLE001 - show a friendly message for any DB error
        console.print(f"[red]Could not migrate database[/] {cfg.database_url}: {e}")
        console.print("Is Postgres running? Try: docker compose up -d")
        raise typer.Exit(1) from e
    console.print("[green]Database ready.[/]")


@app.command()
def ingest() -> None:
    """Parse new session data into the database."""
    from promptlens.ingest.ingest import ingest_all

    cfg = _cfg()
    with _db(cfg) as db:
        res = ingest_all(cfg, db)
    console.print(
        f"Files: {res.files_seen} seen, {res.files_processed} processed; "
        f"{res.lines_processed} new lines; {len(res.sessions_touched)} sessions updated."
    )


@app.command("git")
def git_cmd() -> None:
    """Collect commits and link them to sessions."""
    from promptlens.gitdata.collector import collect_all
    from promptlens.gitdata.linker import link_all

    cfg = _cfg()
    with _db(cfg) as db:
        n = collect_all(cfg, db)
        links = link_all(cfg, db)
    console.print(f"{n} new commits collected; {links} session-commit links.")


@app.command()
def analyze() -> None:
    """Compute metrics, struggle scores, code survival and prompt features."""
    from promptlens.pipeline import analyze_all

    cfg = _cfg()
    with _db(cfg) as db:
        summary = analyze_all(cfg, db)
    for k, v in summary.items():
        console.print(f"{k}: {v}")


@app.command()
def coach(limit: int = typer.Option(None, help="Score at most N prompts.")) -> None:
    """Score prompts with the configured LLM."""
    from promptlens.coach.providers import get_provider
    from promptlens.coach.scorer import score_prompts

    cfg = _cfg()
    try:
        provider = get_provider(cfg)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1) from e
    with _db(cfg) as db:
        res = score_prompts(db, cfg, provider, limit=limit)
    console.print(
        f"Scored {res.scored} prompts ({res.cached} from cache) in {res.llm_calls} LLM calls; "
        f"{res.failed} failed."
    )


@app.command()
def insights() -> None:
    """Recompute insights from current data."""
    from promptlens.insights.analysis import compute_insights

    cfg = _cfg()
    with _db(cfg) as db:
        found = compute_insights(db)
    for i in found:
        console.print(f"- {i.title}")
    if not found:
        console.print("No comparison has enough sessions yet (need 10 per group).")


@app.command()
def report(
    week: bool = typer.Option(True, "--week", help="Weekly report (the only kind for now)."),
    out_dir: Path = typer.Option(Path("reports"), help="Where to write the report."),
) -> None:
    """Write a weekly markdown report."""
    from promptlens.insights.report import write_weekly_report

    cfg = _cfg()
    with _db(cfg) as db:
        path = write_weekly_report(db, out_dir)
    console.print(f"Wrote {path}")


@app.command()
def run() -> None:
    """ingest + git + analyze + insights (everything except coach)."""
    ingest()
    git_cmd()
    analyze()
    insights()


@app.command()
def stats() -> None:
    """Quick terminal summary per project."""
    cfg = _cfg()
    with _db(cfg) as db:
        rows = db.execute(
            select(
                Project.name,
                func.count(Session.id),
                func.coalesce(func.sum(Session.human_turns), 0),
                func.coalesce(func.sum(Session.input_tokens + Session.output_tokens), 0),
                func.coalesce(func.sum(Session.cache_write_tokens + Session.cache_read_tokens), 0),
                func.sum(Session.est_cost_usd),
                func.count(Session.id) - func.count(Session.est_cost_usd),
            )
            .join(Session, Session.project_id == Project.id)
            .group_by(Project.name)
            .order_by(func.count(Session.id).desc())
        ).all()
    t = Table(title="PromptLens - sessions by project")
    for col in ("Project", "Sessions", "Prompts", "In+Out tokens", "Cache tokens", "API-eq. cost"):
        t.add_column(col, justify="left" if col == "Project" else "right")
    unpriced = 0
    for name, n, prompts, io, cache, cost, missing in rows:
        unpriced += missing
        cost_s = f"${float(cost):,.2f}" if cost is not None else "n/a"
        t.add_row(name, str(n), str(prompts), f"{io:,}", f"{cache:,}", cost_s)
    console.print(t)
    if unpriced:
        console.print(
            f"[yellow]{unpriced} session(s) use models with no price in config; "
            r"add them under \[pricing.models] to see cost.[/]"
        )


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Start the API and serve the built dashboard."""
    import uvicorn

    console.print(f"PromptLens at http://{host}:{port}")
    uvicorn.run("promptlens.api.main:create_app", factory=True, host=host, port=port)


@app.command()
def demo(
    sessions: int = typer.Option(120, help="Number of synthetic sessions."),
) -> None:
    """Load a synthetic dataset into a separate demo database (SQLite)."""
    from promptlens.demo.generate import DEMO_DB_URL, build_demo

    summary = build_demo(DEMO_DB_URL, n_sessions=sessions)
    console.print(summary)
    console.print(
        "Open it with: [bold]PROMPTLENS_DATABASE_URL="
        f"{DEMO_DB_URL} promptlens serve[/]  (PowerShell: $env:PROMPTLENS_DATABASE_URL=...)"
    )


@app.command()
def reset(yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt.")) -> None:
    """Drop and recreate all tables."""
    cfg = _cfg()
    if not yes and not typer.confirm(f"Delete ALL PromptLens data in {cfg.database_url}?"):
        raise typer.Abort()
    reset_database(cfg.database_url)
    console.print("[green]Database reset.[/]")


if __name__ == "__main__":
    app()
