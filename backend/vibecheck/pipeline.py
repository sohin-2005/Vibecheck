"""Orchestration for `vibecheck analyze`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from vibecheck.coach.features import compute_features
from vibecheck.config import Config
from vibecheck.db.models import Session
from vibecheck.gitdata.survival import compute_survival
from vibecheck.metrics.session_metrics import recompute_session
from vibecheck.metrics.struggle import compute_struggle


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
