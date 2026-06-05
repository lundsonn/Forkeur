from __future__ import annotations

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
from routers import scrapers, runs, schedule, data, websites, claims as claims_router_mod, cleanup
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

        # WebSocket: token comes as ?token= query param (browsers can't send headers)
        if path.startswith("/ws/"):
            token = request.query_params.get("token", "")
        else:
            header = request.headers.get("Authorization", "")
            token = header.removeprefix("Bearer ").strip()

        if not auth.verify_token(token):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import db
    # On a fresh process start, any run still marked 'running' is orphaned —
    # the previous process was killed and those runs will never finish.
    cleaned = db.orphan_stale_runs(max_age_hours=0)
    if cleaned:
        import logging
        logging.getLogger(__name__).warning("Startup: marked %d orphaned runs as failed", cleaned)
    sched.start()
    yield
    sched.shutdown()


app = FastAPI(title="Forkeur Backend", lifespan=lifespan, docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    await ws_mod.ws_endpoint(websocket, run_id)


# Serve React build in prod
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
