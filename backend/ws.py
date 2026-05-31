from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect

# run_id -> asyncio.Queue of log-line dicts
_queues: dict[str, asyncio.Queue] = {}


def get_or_create_queue(run_id: str) -> asyncio.Queue:
    if run_id not in _queues:
        _queues[run_id] = asyncio.Queue()
    return _queues[run_id]


def make_log_fn(run_id: str):
    """Return a synchronous log callback that pushes lines into the run's queue.

    Args:
        run_id: Unique identifier for the scraper run.

    Returns:
        A callable ``log_fn(line: str) -> None`` that enqueues a log message.
        If the queue is full the line is silently dropped.
    """
    queue = get_or_create_queue(run_id)

    def log_fn(line: str) -> None:
        try:
            queue.put_nowait({"type": "log", "line": line})
        except asyncio.QueueFull:
            pass

    return log_fn


async def send_done(run_id: str, records: int) -> None:
    """Enqueue a ``done`` message signalling successful scraper completion.

    Args:
        run_id: Unique identifier for the scraper run.
        records: Number of records persisted by the scraper.
    """
    queue = get_or_create_queue(run_id)
    await queue.put({"type": "done", "records": records})


async def send_error(run_id: str, msg: str) -> None:
    """Enqueue an ``error`` message signalling scraper failure.

    Args:
        run_id: Unique identifier for the scraper run.
        msg: Human-readable error description.
    """
    queue = get_or_create_queue(run_id)
    await queue.put({"type": "error", "msg": msg})


async def ws_endpoint(websocket: WebSocket, run_id: str) -> None:
    """WebSocket handler that streams queued log lines to the connected client.

    The connection is kept open until a ``done`` or ``error`` message is
    dequeued, the client disconnects, or a 120-second idle timeout expires.
    The queue entry for *run_id* is cleaned up on exit regardless.

    Args:
        websocket: The FastAPI WebSocket connection to stream messages over.
        run_id: Unique identifier for the scraper run whose queue to consume.
    """
    await websocket.accept()
    queue = get_or_create_queue(run_id)
    try:
        while True:
            msg = await asyncio.wait_for(queue.get(), timeout=120)
            await websocket.send_text(json.dumps(msg))
            if msg.get("type") in ("done", "error"):
                break
    except (asyncio.TimeoutError, WebSocketDisconnect):
        pass
    finally:
        _queues.pop(run_id, None)
        await websocket.close()
