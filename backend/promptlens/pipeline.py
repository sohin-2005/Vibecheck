"""Orchestration for `promptlens analyze`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from promptlens.coach.features import compute_features
from promptlens.config import Config
from promptlens.db.models import Session
from promptlens.gitdata.survival import compute_survival
from promptlens.metrics.session_metrics import recompute_session
from promptlens.metrics.struggle import compute_struggle


def analyze_all(cfg: Config, db: DB) -> dict[str, int]:
    ids = db.scalars(select(Session.id)).all()
    for sid in ids:  # prices may have changed since ingest
        recompute_session(db, sid, cfg)
    db.commit()
    return {
        "sessions_recomputed": len(ids),
        "struggle_scored": compute_struggle(db, cfg),
        "survival_checkpoints_computed": compute_survival(cfg, db),
        "prompt_features": compute_features(db),
    }
