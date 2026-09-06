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
import secrets
from contextlib import asynccontextmanager
from types import ModuleType

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.db import db_path, init_db
from backend.settings import env

load_dotenv()  # backend.settings already does this; explicit here too per review

log = logging.getLogger(__name__)

__all__ = ["create_app", "app", "discover_routers"]

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _api_auth_token() -> str:
    return env("API_AUTH_TOKEN").strip()


def _require_api_auth() -> bool:
    return env("REQUIRE_API_AUTH").strip().lower() in _TRUE_VALUES


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
    if _require_api_auth() and not _api_auth_token():
        raise RuntimeError("REQUIRE_API_AUTH is enabled but API_AUTH_TOKEN is empty")
    from backend.demo_limits import enabled as demo_limits_enabled

    if demo_limits_enabled() and (not _require_api_auth() or not _api_auth_token()):
        raise RuntimeError("PUBLIC_DEMO_LIMITS requires bearer authentication")
    from backend.runtime import neatlogs

    neatlogs.initialize()
    try:
        conn = init_db()
        try:
            from backend.runtime.jobs import mark_incomplete_jobs_interrupted

            mark_incomplete_jobs_interrupted(conn)
        finally:
            conn.close()
        log.info("database ready at %s", db_path())
        yield
    finally:
        neatlogs.shutdown()


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

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        """Require a deployment bearer token when one is configured.

        CORS preflights and the liveness endpoint stay public. The token is
        intended for a trusted server-side frontend proxy; it must never be
        placed in a ``NEXT_PUBLIC_*`` variable or shipped to browser code.
        """
        token = _api_auth_token()
        public_health = request.method == "GET" and request.url.path == "/healthz"
        if token and request.method != "OPTIONS" and not public_health:
            authorization = request.headers.get("authorization", "")
            scheme, _, credential = authorization.partition(" ")
            valid = (
                scheme.lower() == "bearer"
                and bool(credential)
                and secrets.compare_digest(credential.encode(), token.encode())
            )
            if not valid:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "authentication required"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        from backend.demo_limits import DemoLimitExceeded, consume_action, enabled

        model_action = None
        if request.method == "POST":
            if request.url.path == "/agents":
                model_action = "create"
            elif request.url.path.startswith("/agents/") and request.url.path.endswith("/run"):
                model_action = "run"
            elif request.url.path.startswith("/agents/") and request.url.path.endswith("/improve"):
                model_action = "improve"
        if model_action and enabled():
            forwarded = request.headers.get("x-demo-client-ip", "").split(",", 1)[0].strip()
            client_address = forwarded or (request.client.host if request.client else "unknown")
            try:
                consume_action(model_action, client_address)
            except DemoLimitExceeded as exc:
                return JSONResponse(
                    status_code=429,
                    content={"detail": str(exc)},
                    headers={"Retry-After": str(exc.retry_after)},
                )
        return await call_next(request)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, object]:
        return {"status": "ok", "db": str(db_path())}

    _register_routers(app)
    return app


app = create_app()
