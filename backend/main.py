from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import auth
import scheduler as sched
import ws as ws_mod
from routers import scrapers, runs, schedule, data, websites, claims as claims_router_mod, cleanup, public
from routers.auth_router import router as auth_router

_PUBLIC_PATHS = {"/api/auth/login"}
_PUBLIC_POST_PATHS = {"/api/claims"}
# Only paths under these prefixes require auth; everything else (static assets) is public.
_AUTH_PREFIXES = ("/api/", "/ws/")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Static files and anything outside the API surface pass through.
        if not any(path.startswith(p) for p in _AUTH_PREFIXES):
            return await call_next(request)
        # Explicitly public API paths.
        if path in _PUBLIC_PATHS:
            return await call_next(request)
        if path in _PUBLIC_POST_PATHS and request.method == "POST":
            return await call_next(request)
        # Public read API for the frontend — unauthenticated GETs.
        if path.startswith("/api/public/") and request.method == "GET":
            return await call_next(request)

        # WebSocket: token comes as ?token= query param (browsers can't send headers)
        if path.startswith("/ws/"):
            token = request.query_params.get("token", "")
        else:
            header = request.headers.get("Authorization", "")
            token = header.removeprefix("Bearer ").strip()

        if not auth.verify_token(token):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)


_REQUIRED_ENV = ("DATABASE_URL", "JWT_SECRET", "ADMIN_PASSWORD")


def _check_required_env() -> None:
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_required_env()
    import db
    import pgpool
    pgpool.get_pool()  # open the pool eagerly so a bad DATABASE_URL fails fast
    # On a fresh process start, any run still marked 'running' is orphaned —
    # the previous process was killed and those runs will never finish.
    cleaned = db.orphan_stale_runs(max_age_hours=0)
    if cleaned:
        import logging
        logging.getLogger(__name__).warning("Startup: marked %d orphaned runs as failed", cleaned)
    sched.start()
    yield
    sched.shutdown()
    db.close_client()  # closes the pool via the back-compat shim


app = FastAPI(title="Forkeur Backend", lifespan=lifespan, docs_url=None, redoc_url=None)

_cors_origins_env = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:8000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins_env.split(",") if o.strip()],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(AuthMiddleware)

app.include_router(auth_router, prefix="/api")
app.include_router(scrapers.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(schedule.router, prefix="/api")
app.include_router(data.router, prefix="/api")
app.include_router(websites.router, prefix="/api")
app.include_router(claims_router_mod.router, prefix="/api")
app.include_router(cleanup.router, prefix="/api")
app.include_router(public.router, prefix="/api")


@app.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    await ws_mod.ws_endpoint(websocket, run_id)


# Serve React build in prod
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
