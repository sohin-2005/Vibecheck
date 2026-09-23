"""Trigger processing jobs in the background, and read-only config."""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session as DB

from promptlens.api.deps import get_cfg
from promptlens.config import Config
from promptlens.db.session import make_sessionmaker

router = APIRouter()


def _ingest(cfg: Config, db: DB) -> dict[str, Any]:
    from promptlens.ingest.ingest import ingest_all

    r = ingest_all(cfg, db)
    return {"files_processed": r.files_processed, "lines_processed": r.lines_processed}


def _git(cfg: Config, db: DB) -> dict[str, Any]:
    from promptlens.gitdata.collector import collect_all
    from promptlens.gitdata.linker import link_all

    return {"new_commits": collect_all(cfg, db), "links": link_all(cfg, db)}


def _analyze(cfg: Config, db: DB) -> dict[str, Any]:
    from promptlens.pipeline import analyze_all

    return analyze_all(cfg, db)


def _coach(cfg: Config, db: DB) -> dict[str, Any]:
    from promptlens.coach.providers import get_provider
    from promptlens.coach.scorer import score_prompts

    r = score_prompts(db, cfg, get_provider(cfg))
    return {"scored": r.scored, "cached": r.cached, "llm_calls": r.llm_calls, "failed": r.failed}


def _insights(cfg: Config, db: DB) -> dict[str, Any]:
    from promptlens.insights.analysis import compute_insights

    return {"insights": len(compute_insights(db))}


def _run(cfg: Config, db: DB) -> dict[str, Any]:
    return {
        "ingest": _ingest(cfg, db),
        "git": _git(cfg, db),
        "analyze": _analyze(cfg, db),
        "insights": _insights(cfg, db),
    }


JOBS: dict[str, Callable[[Config, DB], dict[str, Any]]] = {
    "ingest": _ingest,
    "git": _git,
    "analyze": _analyze,
    "coach": _coach,
    "insights": _insights,
    "run": _run,
}


@dataclass
class Job:
    id: str
    name: str
    status: str = "queued"  # queued | running | done | failed
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()  # one job at a time; they all write the same tables


def _execute(job: Job, cfg: Config) -> None:
    with _lock:
        job.status = "running"
        db = make_sessionmaker(cfg.database_url)()
        try:
            job.result = JOBS[job.name](cfg, db)
            job.status = "done"
        except Exception as e:  # noqa: BLE001 - report any failure to the UI
            job.status = "failed"
            job.error = f"{e}\n{traceback.format_exc(limit=3)}"
        finally:
            db.close()
            job.finished_at = datetime.now(UTC)


@router.post("/jobs/{name}")
def start_job(
    name: str, background: BackgroundTasks, cfg: Config = Depends(get_cfg)
) -> dict[str, Any]:
    if name not in JOBS:
        raise HTTPException(404, f"unknown job {name!r}; one of {sorted(JOBS)}")
    job = Job(id=uuid.uuid4().hex[:12], name=name)
    _jobs[job.id] = job
    background.add_task(_execute, job, cfg)
    return {"id": job.id, "name": name, "status": job.status}


@router.get("/jobs")
def list_jobs() -> list[Job]:
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)[:20]


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


def _mask_url(url: str) -> str:
    import re

    return re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", url)


@router.get("/config")
def config(cfg: Config = Depends(get_cfg)) -> dict[str, Any]:
    return {
        "config_path": str(cfg.config_path) if cfg.config_path else None,
        "database_url": _mask_url(cfg.database_url),
        "claude_projects_dir": str(cfg.claude_projects_dir),
        "include_sidechains": cfg.include_sidechains,
        "ignore_projects": cfg.ignore_projects,
        "commit_link_window_minutes": cfg.commit_link_window_minutes,
        "survival_checkpoints_days": cfg.survival_checkpoints_days,
        "ignore_globs": cfg.ignore_globs,
        "priced_models": sorted(cfg.pricing),
        "struggle_weights": cfg.weights,
        "redaction_enabled": cfg.redaction_enabled,
        "llm": {
            "provider": cfg.llm_provider,
            "model": cfg.llm_model,
            "batch_size": cfg.llm_batch_size,
            "send_to_cloud_confirmed": cfg.send_to_cloud_confirmed,
        },
    }
