"""Standalone takeaway full-run, decoupled from the forkeur-backend service.

Run detached so a `systemctl restart forkeur-backend` (e.g. a colleague deploying)
does NOT orphan the scrape:

    cd /opt/forkeur/backend
    nohup /root/.local/bin/uv run python -m scripts.run_takeaway_standalone \
        > /tmp/takeaway_standalone.log 2>&1 &

Tracks the run in scraper_runs (create_run / finish_run) just like the router,
so the admin dashboard and health checks still see it. Logs both to stdout and
to the per-run file the router uses (/tmp/fk_takeaway_<id8>.log).
"""
from __future__ import annotations
import asyncio
import sys
import time

import db
from models import ScraperConfig
from scrapers import takeaway


async def _main() -> int:
    run_id = db.create_run("takeaway")
    log_path = f"/tmp/fk_takeaway_{run_id[:8]}.log"
    log_fh = open(log_path, "a")  # noqa: SIM115

    def log_fn(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            safe = msg.replace("\r", " ").replace("\n", " | ")
            log_fh.write(f"{time.strftime('%H:%M:%S')} {safe}\n")
            log_fh.flush()
        except Exception:
            pass

    log_fn(f"[standalone] takeaway run {run_id} starting (detached from backend service)")
    config = ScraperConfig()  # defaults = full run, menus included
    try:
        result = await takeaway.run(config, log_fn, run_id=run_id)
        db.finish_run(run_id, "success", records_saved=result.records_saved)
        log_fn(f"[standalone] done — {result.records_saved} listings saved")
        return 0
    except Exception as exc:  # noqa: BLE001
        db.finish_run(run_id, "failed", error_msg=f"[standalone] {exc}")
        log_fn(f"[standalone] FAILED — {exc}")
        return 1
    finally:
        try:
            log_fh.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
