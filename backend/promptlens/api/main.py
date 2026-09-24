"""FastAPI app: JSON API under /api, plus the built dashboard at /."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from promptlens.api.routes import analytics, jobs, overview, sessions, team
from promptlens.config import Config, load_config

DEFAULT_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_app(cfg: Config | None = None, dist: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="PromptLens", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.state.cfg = cfg or load_config()
    for r in (overview.router, sessions.router, analytics.router, jobs.router, team.router):
        app.include_router(r, prefix="/api")

    dist = (dist or Path(os.environ.get("PROMPTLENS_FRONTEND_DIST", DEFAULT_DIST))).resolve()
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "not found")
            f = dist / path
            if path and f.is_file() and dist in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app
