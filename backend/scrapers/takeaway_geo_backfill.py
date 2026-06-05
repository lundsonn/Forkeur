"""One-shot geo backfill for existing Takeaway listings.

Visits each takeaway menu URL, extracts JSON-LD (server-rendered, no scroll needed),
saves lat/lng/cuisine/phone/neighborhood to the restaurant record.

Skips restaurants that already have geo_source='takeaway'.
Uses headed Chromium (CF bypass) with a single browser context.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Callable

import db
from scrapers.base import browser_session, new_page, wait_for_cf_clear, noop_log, CloudflareBlockedError
from scrapers.takeaway import _JSONLD_EVAL

WORKERS = 3
BATCH_PAUSE_S = 1.5  # between pages per worker


async def run(log_fn: Callable[[str], None] = noop_log) -> dict:
    """Backfill lat/lng for all takeaway restaurants missing venue-grade geo."""
    client = db.get_client()

    # Fetch all takeaway listings without takeaway-grade geo
    res = (
        client.table("platform_listings")
        .select("restaurant_id, url, restaurants(id, name, geo_source, lat)")
        .eq("platform", "takeaway")
        .execute()
    )

    targets = [
        {"rid": row["restaurant_id"], "url": row["url"], "name": (row.get("restaurants") or {}).get("name", "")}
        for row in res.data
        if (row.get("restaurants") or {}).get("geo_source") != "takeaway"
        and (row.get("restaurants") or {}).get("lat") is None
    ]

    log_fn(f"Backfill: {len(targets)} takeaway restaurants need geo")
    if not targets:
        return {"updated": 0}

    updated = 0
    failed = 0

    async with browser_session(lang="fr-BE", headed=True) as browser:
        slices = [targets[w::WORKERS] for w in range(WORKERS)]

        async def _worker(wid: int, items: list) -> None:
            nonlocal updated, failed
            page = await new_page(browser, lang="fr-BE")
            try:
                for item in items:
                    try:
                        try:
                            await page.goto(item["url"], wait_until="domcontentloaded", timeout=45000)
                        except Exception:
                            pass

                        title = await page.title()
                        if "just a moment" in title.lower():
                            cleared = await wait_for_cf_clear(page, timeout_s=60)
                            if not cleared:
                                log_fn(f"  CF not cleared: {item['name']}")
                                failed += 1
                                continue

                        rinfo = await page.evaluate(_JSONLD_EVAL)
                        if not rinfo or rinfo.get("lat") is None:
                            log_fn(f"  No JSON-LD geo: {item['name']}")
                            failed += 1
                            continue

                        enriched: dict = {"name": item["name"]}
                        enriched["lat"] = rinfo["lat"]
                        enriched["lng"] = rinfo["lng"]
                        enriched["geo_source"] = "takeaway"
                        if rinfo.get("neighborhood"):
                            enriched["neighborhood"] = rinfo["neighborhood"]
                        if rinfo.get("cuisine"):
                            enriched["cuisine"] = rinfo["cuisine"]
                        if rinfo.get("phone"):
                            enriched["phone"] = rinfo["phone"]

                        try:
                            db.upsert_restaurant(enriched)
                            updated += 1
                            log_fn(f"  geo saved: {item['name']} ({rinfo['lat']:.4f},{rinfo['lng']:.4f})")
                        except ValueError as e:
                            log_fn(f"  upsert error: {item['name']}: {e}")
                            failed += 1

                    except CloudflareBlockedError:
                        log_fn(f"  CF blocked: {item['name']}")
                        failed += 1
                    except Exception as exc:
                        log_fn(f"  error: {item['name']}: {exc}")
                        failed += 1

                    await asyncio.sleep(BATCH_PAUSE_S)
            finally:
                await page.close()

        await asyncio.gather(*[_worker(w, s) for w, s in enumerate(slices) if s])

    log_fn(f"Done — updated: {updated}, failed/skipped: {failed}")
    return {"updated": updated, "failed": failed}


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    async def main():
        result = await run(log_fn=print)
        print(result)

    asyncio.run(main())
