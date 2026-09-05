"""FastAPI app factory.

Run it with::

    uv run --project backend python -m uvicorn backend.app:app --port 8000

Phase 1/2 workers register their routers by adding one line to
`ROUTER_MODULES` below and exposing an `APIRouter` named `router` in that
module. A module that is not merged yet is skipped with a warning, so the app
still boots mid-merge.
"""

from __future__ import annotations

import importlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db import db_path, init_db

log = logging.getLogger(__name__)

__all__ = ["create_app", "app", "ROUTER_MODULES"]

# Registration points for later workstreams. Uncomment as each lands.
ROUTER_MODULES: tuple[str, ...] = (
    # "backend.ledger.api",       # W1 - /events, /insights, /agents/{id}/fixes
    # "backend.runtime.api",      # W2 - /agents/{id}/run, /jobs/{job_id}
    # "backend.architect.api",    # W3 - /agents, /evaluators
    # "backend.improver.api",     # W6 - /agents/{id}/improve
    # "backend.issues.api",       # W7 - /issues
    # "backend.playbook.api",     # W8 - /playbook
)


def _register_routers(app: FastAPI) -> None:
    for module_name in ROUTER_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            log.warning("router module %s is not available yet; skipping", module_name)
            continue
        router = getattr(module, "router", None)
        if router is None:
            log.warning("module %s has no `router`; skipping", module_name)
            continue
        app.include_router(router)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    conn = init_db()
    conn.close()
    log.info("database ready at %s", db_path())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Task Orchestrator",
        version="0.1.0",
        description="Generate, evaluate and improve specialized agents. See contracts/api.md.",
        lifespan=_lifespan,
    )

    origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, object]:
        return {"status": "ok", "db": str(db_path())}

    _register_routers(app)
    return app


app = create_app()
