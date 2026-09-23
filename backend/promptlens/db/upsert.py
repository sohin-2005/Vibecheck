"""Dialect-aware bulk upsert (PostgreSQL and SQLite both support ON CONFLICT)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session as DB

CHUNK = 500


def upsert(
    db: DB,
    model: type,
    rows: Sequence[dict[str, Any]],
    keys: Sequence[str],
    update: Sequence[str] | None = None,
) -> None:
    """Insert rows; on key conflict update ``update`` columns (or do nothing if empty).

    Rows sharing a key are collapsed (last wins) since one statement can't touch a row twice.
    """
    if not rows:
        return
    unique = list({tuple(r[k] for k in keys): r for r in rows}.values())
    dialect = db.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    table = model.__table__  # type: ignore[attr-defined]
    for i in range(0, len(unique), CHUNK):
        stmt = insert(table).values(unique[i : i + CHUNK])
        if update:
            stmt = stmt.on_conflict_do_update(
                index_elements=list(keys), set_={c: stmt.excluded[c] for c in update}
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=list(keys))
        db.execute(stmt)
