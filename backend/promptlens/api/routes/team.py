"""Team mode endpoints: receive teammates' anonymized weekly exports and list them."""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session as DB

from promptlens.api.deps import get_db
from promptlens.team import import_export, team_table

router = APIRouter()


@router.post("/team/snapshots")
def receive(
    payload: dict[str, Any],
    token: str | None = Header(None, alias="X-PromptLens-Team-Token"),
    db: DB = Depends(get_db),
) -> dict[str, Any]:
    expected = os.environ.get("PROMPTLENS_TEAM_TOKEN")
    if not expected:
        raise HTTPException(403, "Team mode is off on this server (set PROMPTLENS_TEAM_TOKEN).")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "Missing or wrong X-PromptLens-Team-Token.")
    try:
        n = import_export(db, payload)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"member": payload.get("member"), "weeks": n}


@router.get("/team")
def team(db: DB = Depends(get_db)) -> dict[str, Any]:
    return team_table(db)
