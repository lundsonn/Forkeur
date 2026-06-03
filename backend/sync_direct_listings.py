#!/usr/bin/env python3
"""Sync restaurants.order_url → platform_listings(platform='direct')."""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import db
from scrapers.direct_classify import classify_url


def sync(dry_run: bool = False) -> int:
    client = db.get_client()
    restaurants = (
        client.table('restaurants')
        .select('id, name, order_url, phone')
        .not_.is_('order_url', 'null')
        .execute()
    ).data

    print(f"Found {len(restaurants)} restaurants with order_url")
    synced = 0

    for r in restaurants:
        url_type = classify_url(r['order_url'], r.get('phone'))
        data = {
            'restaurant_id': r['id'],
            'platform': 'direct',
            'url': r['order_url'],
            'url_type': url_type,
            'is_available': True,
        }
        label = f"{r['name'][:35]!r:<38} {url_type:<10} {r['order_url'][:55]}"
        print(f"  {'[DRY] ' if dry_run else ''}{label}")
        if not dry_run:
            db.upsert_listing(data)
        synced += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Synced {synced} direct listings")
    return synced


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    sync(dry_run=dry_run)
