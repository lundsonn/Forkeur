"""Standalone full-batch scrape, decoupled from the forkeur-backend service.

Runs ubereats, deliveroo, takeaway, direct, direct_menu concurrently; dom_menu
launches once a heavy scraper finishes AND MemAvailable ≥ BATCH_MEM_GATE_GB;
finally runs cross-platform match. Tracks every run in scraper_runs so the
admin dashboard and health checks see it.

Run detached so `systemctl restart forkeur-backend` does NOT kill the scrape:

    cd /opt/forkeur/backend
    DISPLAY=:99 nohup /root/.local/bin/uv run python -m scripts.run_batch_standalone \
        > /tmp/batch_standalone.log 2>&1 &

Env overrides (same as scheduler.py):
    BATCH_MEM_GATE_GB   float, default 2.0
    TAKEAWAY_ZONE_WORKERS / TAKEAWAY_MENU_WORKERS   forwarded to takeaway.py
"""
from __future__ import annotations
import asyncio
import inspect
import logging
import os
import sys
import time
from datetime import datetime

# Playwright scrapers need a display; Xvfb runs on :99 in production.
os.environ.setdefault("DISPLAY", ":99")

import db
from models import ScraperConfig
from scrapers import ubereats, deliveroo, takeaway, direct, direct_menu, dom_menu
from scrapers import match as _match
from scrapers.base import CloudflareBlockedError
import alerting

# ── logging ──────────────────────────────────────────────────────────────────

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_LOG_PATH = f"/tmp/fk_batch_standalone_{_ts}.log"
_log_fh = open(_LOG_PATH, "a")  # noqa: SIM115

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
_log = logging.getLogger("forkeur.batch_standalone")


def _log_fn(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        safe = msg.replace("\r", " ").replace("\n", " | ")
        _log_fh.write(f"{time.strftime('%H:%M:%S')} {safe}\n")
        _log_fh.flush()
    except Exception:
        pass


# ── memory gate ──────────────────────────────────────────────────────────────

_MEM_GATE_GB = float(os.getenv("BATCH_MEM_GATE_GB", "2.0"))
_MEM_GATE_POLL_S = 15
_MEM_GATE_TIMEOUT_S = 3600


def _mem_available_gb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    return float("inf")  # macOS dev: no /proc, never block


# ── scraper registry (no router imports) ─────────────────────────────────────

_SCRAPERS = {
    "ubereats":    ubereats.run,
    "deliveroo":   deliveroo.run,
    "takeaway":    takeaway.run,
    "direct":      direct.run,
    "direct_menu": None,   # special-cased below
    "dom_menu":    dom_menu.run,
}

# Per-platform wall-clock timeouts (seconds).
_TIMEOUTS: dict[str, int] = {
    "ubereats":    90 * 60,
    "deliveroo":   60 * 60,
    "takeaway":   150 * 60,
    "direct":      60 * 60,
    "direct_menu": 15 * 60,
    "dom_menu":    60 * 60,
    "match":       15 * 60,
}

# Local to this process — does NOT share state with the FastAPI router.
_running: set[str] = set()


async def _run_scraper(platform: str) -> None:
    if platform in _running:
        _log_fn(f"[batch] {platform} already running, skipping")
        return

    _running.add(platform)
    run_id = db.create_run(platform)
    timeout = _TIMEOUTS.get(platform, 60 * 60)
    _log_fn(f"[batch] {platform} starting (run={run_id[:8]}, timeout={timeout // 60}min)")

    try:
        if platform == "direct_menu":
            result = await asyncio.wait_for(direct_menu.run(), timeout=timeout)
            db.finish_run(run_id, "success", records_saved=result.get("total_scraped", 0))
            _log_fn(f"[batch] {platform} done — {result.get('total_scraped', 0)} saved")
            return

        scraper_fn = _SCRAPERS[platform]
        sig = inspect.signature(scraper_fn).parameters
        kwargs: dict = {}
        if "run_id" in sig:
            kwargs["run_id"] = run_id

        result = await asyncio.wait_for(
            scraper_fn(ScraperConfig(), _log_fn, **kwargs),
            timeout=timeout,
        )
        db.finish_run(run_id, "success", records_saved=result.records_saved)
        _log_fn(f"[batch] {platform} done — {result.records_saved} saved")

    except asyncio.TimeoutError:
        msg = f"timed out after {timeout // 60} min"
        db.finish_run(run_id, "failed", error_msg=msg)
        alerting.send_failure_alert(platform, msg, run_id)
        _log_fn(f"[batch] {platform} TIMEOUT — {msg}")
    except asyncio.CancelledError:
        db.finish_run(run_id, "failed", error_msg="cancelled")
        _log_fn(f"[batch] {platform} CANCELLED")
        raise
    except CloudflareBlockedError as e:
        db.finish_run(run_id, "blocked", error_msg=str(e))
        alerting.send_failure_alert(platform, str(e), run_id)
        _log_fn(f"[batch] {platform} BLOCKED — {e}")
    except Exception as e:
        db.finish_run(run_id, "failed", error_msg=str(e))
        alerting.send_failure_alert(platform, str(e), run_id)
        _log_fn(f"[batch] {platform} FAILED — {e}")
    finally:
        _running.discard(platform)


async def _run_match() -> None:
    run_id = db.create_run("match")
    _log_fn(f"[batch] match starting (run={run_id[:8]})")
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_match.run_sync, dry_run=False, log_fn=_log_fn),
            timeout=_TIMEOUTS["match"],
        )
        db.finish_run(run_id, "success", records_saved=result["auto_merge"])
        _log_fn(f"[batch] match done — {result['auto_merge']} auto-merged")
    except Exception as e:
        db.finish_run(run_id, "failed", error_msg=str(e))
        alerting.send_failure_alert("match", str(e), run_id)
        _log_fn(f"[batch] match FAILED — {e}")


async def _main() -> int:
    _log_fn(f"[batch] standalone run starting — log={_LOG_PATH}")
    _log_fn(f"[batch] mem gate={_MEM_GATE_GB}GB, poll={_MEM_GATE_POLL_S}s")

    heavy = ["ubereats", "deliveroo", "takeaway", "direct"]
    heavy_tasks = [asyncio.create_task(_run_scraper(p)) for p in heavy]

    async def _gated_dom_menu() -> None:
        if heavy_tasks:
            _log_fn("[batch] dom_menu waiting for first heavy scraper to finish...")
            await asyncio.wait(heavy_tasks, return_when=asyncio.FIRST_COMPLETED)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _MEM_GATE_TIMEOUT_S
        while _mem_available_gb() < _MEM_GATE_GB:
            if loop.time() >= deadline:
                _log_fn(f"[batch] memory gate open (timeout {_MEM_GATE_TIMEOUT_S}s), launching dom_menu anyway")
                break
            avail = _mem_available_gb()
            _log_fn(f"[batch] dom_menu waiting — MemAvailable={avail:.1f}GB < {_MEM_GATE_GB}GB")
            await asyncio.sleep(_MEM_GATE_POLL_S)
        await _run_scraper("dom_menu")

    await asyncio.gather(
        *heavy_tasks,
        _run_scraper("direct_menu"),
        _gated_dom_menu(),
        return_exceptions=True,
    )

    await _run_match()

    _log_fn(f"[batch] all done — log at {_LOG_PATH}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_main()))
    finally:
        try:
            _log_fh.close()
        except Exception:
            pass
