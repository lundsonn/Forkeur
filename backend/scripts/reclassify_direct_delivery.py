"""Re-classify direct platform_listings that have url_type='website'.

Only upgrades to 'ordering' when the listing URL itself OR a link found on the
page resolves to a known ordering platform hostname (sq-menu, piki-app,
flipdish, obypay, …) as defined by direct_classify._ORDERING_HOSTS / Odoo POS.

No keyword scanning — that produces false positives from generic delivery
mentions ("we deliver via Uber Eats", "livraison possible", etc.).

Usage:
    uv run python scripts/reclassify_direct_delivery.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

import db
import pgpool
from scrapers.base import new_browser, new_page, is_safe_url
from scrapers.direct_classify import _ORDERING_HOSTS, classify_url


def _is_strict_ordering_url(url: str) -> bool:
    """Return True only when url resolves to a known direct-ordering platform."""
    result = classify_url(url)
    return result == 'ordering'


def _fetch_candidates(limit: int | None) -> list[dict]:
    sql = """
        SELECT pl.id, pl.url, r.name
        FROM platform_listings pl
        JOIN restaurants r ON r.id = pl.restaurant_id
        WHERE pl.platform = 'direct'
          AND pl.url_type = 'website'
          AND pl.url IS NOT NULL
          AND pl.url != ''
        ORDER BY r.name
    """
    params: list = []
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    return pgpool.fetchall(sql, params)


async def _find_ordering_link(page, base_url: str) -> str | None:
    """Visit page and return the first href that points to a known ordering platform."""
    try:
        hrefs: list[str] = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('a[href]'))
                .map(a => a.href)
                .filter(h => h.startsWith('http'))
        """)
    except Exception:
        return None

    for href in (hrefs or []):
        if _is_strict_ordering_url(href):
            return href
    return None


async def _check_ordering(page, url: str) -> tuple[bool, str]:
    """Return (is_ordering, reason). Only strict hostname-based detection."""
    if not is_safe_url(url):
        return False, 'unsafe'

    # 1. URL itself is on a known ordering platform
    if _is_strict_ordering_url(url):
        return True, f'url match: {urlparse(url).netloc}'

    # 2. Fetch page and scan anchor hrefs
    try:
        await page.goto(url, timeout=25_000, wait_until='domcontentloaded')
        await page.wait_for_timeout(1_500)
    except Exception as e:
        return False, f'nav error: {e}'

    # Check if we landed on an ordering platform after redirect
    if page.url != url and _is_strict_ordering_url(page.url):
        return True, f'redirect to ordering: {urlparse(page.url).netloc}'

    ordering_link = await _find_ordering_link(page, url)
    if ordering_link:
        return True, f'link on page: {urlparse(ordering_link).netloc}'

    return False, 'no ordering signals'


async def run(limit: int | None, dry_run: bool) -> None:
    candidates = _fetch_candidates(limit)
    total = len(candidates)
    print(f"[reclassify] {total} listings to check (dry_run={dry_run})")

    upgraded = 0
    skipped = 0

    browser = await new_browser(headed=False)
    try:
        page = await new_page(browser)
        for i, row in enumerate(candidates, 1):
            lid, url, name = row["id"], row["url"], row["name"]
            print(f"  [{i}/{total}] {name} — {url[:70]}", end="", flush=True)
            try:
                is_ordering, reason = await _check_ordering(page, url)
            except Exception as e:
                print(f" ERROR: {e}")
                skipped += 1
                continue

            if is_ordering:
                print(f" ✓ {reason} → ordering")
                if not dry_run:
                    db.patch_listing(lid, {"url_type": "ordering"})
                upgraded += 1
            else:
                print(f" — {reason}")
                skipped += 1
    finally:
        await browser.close()

    print(f"\n[reclassify] upgraded={upgraded} skipped={skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.dry_run))
