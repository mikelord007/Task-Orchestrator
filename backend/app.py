"""FastAPI app factory.

Run it with::

    uv run --project backend python -m uvicorn backend.app:app --port 8000

Later workstreams register a router simply by adding `backend/<pkg>/api.py`
with an `APIRouter` named `router` -- `discover_routers()` finds every
immediate subpackage of `backend` that exposes one and includes it. This
replaces an explicit list of modules to import: a hand-maintained list is a
guaranteed merge conflict once five workers are each adding one entry.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from contextlib import asynccontextmanager
from types import ModuleType

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db import db_path, init_db
from backend.settings import env

load_dotenv()  # backend.settings already does this; explicit here too per review

log = logging.getLogger(__name__)

__all__ = ["create_app", "app", "discover_routers"]


def discover_routers(package: ModuleType) -> list[APIRouter]:
    """Every `<package>.<subpackage>.api.router` found one level down.

    A subpackage with no `api.py`, or an `api.py` with no `router`, is
    silently skipped -- that is the normal state for a workstream that has
    not landed yet, not an error.
    """
    routers: list[APIRouter] = []
    prefix = f"{package.__name__}."
    for _finder, name, is_pkg in pkgutil.iter_modules(package.__path__, prefix=prefix):
        if not is_pkg:
            continue
        try:
            module = importlib.import_module(f"{name}.api")
        except ModuleNotFoundError:
            continue
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            routers.append(router)
        elif router is not None:
            log.warning("%s.api.router is not an APIRouter; skipping", name)
    return routers


def _register_routers(app: FastAPI) -> None:
    import backend

    for router in discover_routers(backend):
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

    origins = env("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
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
