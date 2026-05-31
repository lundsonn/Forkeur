from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import scheduler as sched
import ws as ws_mod
from routers import scrapers, runs, schedule, data


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched.start()
    yield
    sched.shutdown()


app = FastAPI(title="Forkeur Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scrapers.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(schedule.router, prefix="/api")
app.include_router(data.router, prefix="/api")


@app.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    await ws_mod.ws_endpoint(websocket, run_id)


# Serve React build in prod
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
