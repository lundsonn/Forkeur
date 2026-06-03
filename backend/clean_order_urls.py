#!/usr/bin/env python3
"""
Null out junk order_url values in restaurants table.
Idempotent — safe to re-run.

Usage:
  cd backend && uv run python clean_order_urls.py [--dry-run]
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from scrapers.direct_classify import _JUNK_RE
import db


def clean(dry_run: bool = False) -> int:
    client = db.get_client()
    rows = (
        client.table('restaurants')
        .select('id, name, order_url')
        .not_.is_('order_url', 'null')
        .execute()
    ).data

    nulled = 0
    for row in rows:
        url = row['order_url']
        if _JUNK_RE.search(url):
            print(f"  NULL: {row['name'][:40]!r:<44} {url[:70]}")
            if not dry_run:
                client.table('restaurants').update({'order_url': None}).eq('id', row['id']).execute()
            nulled += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Nulled {nulled} junk order_url rows")
    return nulled


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    clean(dry_run=dry_run)
