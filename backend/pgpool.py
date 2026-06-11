"""psycopg3 connection pool — the single point of DB access for the backend.

Synchronous on purpose: db.py exposes sync functions called by async scrapers
(directly and via asyncio.to_thread). A sync pool keeps every call site
unchanged. Safe under PgBouncer transaction pooling — no session state is used.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Sequence

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

load_dotenv()

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                dsn = os.environ["DATABASE_URL"]
                _pool = ConnectionPool(
                    dsn,
                    min_size=2,
                    max_size=10,
                    kwargs={"row_factory": dict_row},
                    # PgBouncer transaction pooling multiplexes server
                    # connections per-transaction, so server-side prepared
                    # statements created on one backend break when the client
                    # lands on another ("prepared statement does not exist").
                    # Disable them pool-wide.
                    configure=lambda conn: setattr(conn, "prepare_threshold", None),
                    open=True,
                )
    return _pool


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def fetchall(sql: str, params: Sequence[Any] | dict | None = None) -> list[dict]:
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetchone(sql: str, params: Sequence[Any] | dict | None = None) -> dict | None:
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql: str, params: Sequence[Any] | dict | None = None) -> int:
    """Run a statement, return affected rowcount. Use for INSERT/UPDATE/DELETE
    without RETURNING."""
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount
