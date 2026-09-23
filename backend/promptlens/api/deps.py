"""Shared API dependencies and query filters."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import Query, Request
from sqlalchemy import Select
from sqlalchemy.orm import Session as DB

from promptlens.config import Config
from promptlens.db.models import Session
from promptlens.db.session import make_sessionmaker


def get_cfg(request: Request) -> Config:
    return request.app.state.cfg


def get_db(request: Request) -> Iterator[DB]:
    db = make_sessionmaker(request.app.state.cfg.database_url)()
    try:
        yield db
    finally:
        db.close()


@dataclass
class Filters:
    start: datetime | None
    end: datetime | None
    project_id: int | None

    def apply(self, q: Select[Any]) -> Select[Any]:
        if self.start:
            q = q.where(Session.started_at >= self.start)
        if self.end:
            q = q.where(Session.started_at < self.end)
        if self.project_id is not None:
            q = q.where(Session.project_id == self.project_id)
        return q


def filters(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    project_id: int | None = Query(None),
) -> Filters:
    return Filters(
        start=datetime.combine(from_, time.min, tzinfo=UTC) if from_ else None,
        end=datetime.combine(to + timedelta(days=1), time.min, tzinfo=UTC) if to else None,
        project_id=project_id,
    )


def num(x: Any) -> float | None:
    return float(x) if x is not None else None
