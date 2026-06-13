"""Operational metrics / health endpoint.

Exposes GET /api/metrics/health — a JSON snapshot of operational signals
(DB connectivity, connection-pool stats, pending migrations, per-platform
scraper freshness). Auth-protected like the rest of /api via require_auth.

Each section is wrapped in its own try/except so a single failing probe
degrades that section to {"error": ...} instead of 500-ing the whole
endpoint — health checks must stay observable even when one signal is down.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

import pgpool
from routers.auth_router import require_auth

router = APIRouter(
    prefix="/metrics",
    tags=["metrics"],
    dependencies=[Depends(require_auth)],
)


@router.get("/health", response_model=None)
async def health() -> dict:
    out: dict = {}

    # 1. DB connectivity
    try:
        pgpool.fetchone("SELECT 1")
        out["db"] = {"ok": True}
    except Exception as e:  # noqa: BLE001 — surface, don't crash
        out["db"] = {"ok": False, "error": str(e)}

    # 2. Connection pool stats (surfaces exhaustion via requests_waiting > 0)
    try:
        out["pool"] = pgpool.get_pool().get_stats()
    except Exception as e:  # noqa: BLE001
        out["pool"] = {"error": str(e)}

    # 3. Pending migrations
    try:
        from ops.migrate import compute_pending_via_pool, TrackingTableMissing

        try:
            pending = compute_pending_via_pool(pgpool)
            out["migrations"] = {"pending": pending, "count": len(pending)}
        except TrackingTableMissing:
            out["migrations"] = {
                "pending": None,
                "note": "tracking table not initialized; run make migrate-baseline",
            }
    except Exception as e:  # noqa: BLE001
        out["migrations"] = {"error": str(e)}

    # 4. Per-platform scraper freshness (latest run per platform)
    try:
        rows = pgpool.fetchall(
            """
            SELECT DISTINCT ON (platform) platform, status, started_at, finished_at
            FROM scraper_runs
            ORDER BY platform, started_at DESC
            """
        )
        now = datetime.now(timezone.utc)
        scrapers = []
        for r in rows:
            started_at = r.get("started_at")
            age_seconds = None
            if started_at is not None:
                age_seconds = (now - started_at).total_seconds()
            scrapers.append(
                {
                    "platform": r.get("platform"),
                    "status": r.get("status"),
                    "age_seconds": age_seconds,
                }
            )
        out["scrapers"] = scrapers
    except Exception as e:  # noqa: BLE001
        out["scrapers"] = {"error": str(e)}

    return out
