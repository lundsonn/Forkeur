"""
Find and merge restaurant rows that represent the same place but were scraped
under slightly different names on different platforms.

Matching criterion:
  - All tokens of the shorter name are a subset of the longer name's tokens
  - Jaccard similarity ≥ 0.6
  - No platform overlap (same restaurant can't be on same platform twice)

Usage:
    cd backend
    uv run python scripts/merge_restaurant_dupes.py            # dry-run
    uv run python scripts/merge_restaurant_dupes.py --execute  # perform merges
"""
from __future__ import annotations
import argparse
import os
import re
import sys
import unicodedata
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# Tokens to ignore during matching
_STOPWORDS = {
    "le", "la", "les", "au", "aux", "un", "une", "de", "du", "des",
    "the", "a", "an", "en", "van", "het", "and", "et",
    "restaurant", "brasserie", "cafe", "snack",
}

_JUNK_PATTERNS = re.compile(
    r'^(environ\s+\d|around\s+\d|pre[\s-]?order\s+\d|pré[\s-]?commande\s+\d'
    r'|article\s+offert|\d+e?\s*à\s*moiti|\d+\s*%\s+off|-\s*\d+\s*%'
    r'|•\s*à\s+partir|\d+e\s+à\s+moitié)',
    re.IGNORECASE,
)


def _normalize_tokens(name: str) -> frozenset[str]:
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)
    tokens = s.split()
    return frozenset(
        t for t in tokens
        if t not in _STOPWORDS and len(t) >= 2 and not t.isdigit()
    )


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_candidate(tok_a: frozenset, tok_b: frozenset, min_j: float) -> bool:
    shorter, longer = (tok_a, tok_b) if len(tok_a) <= len(tok_b) else (tok_b, tok_a)
    if len(shorter) < 2:
        return False
    if not shorter.issubset(longer):
        return False
    return _jaccard(tok_a, tok_b) >= min_j


def _fetch_all(table: str, select: str, page: int = 1000) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        batch = client.table(table).select(select).range(offset, offset + page - 1).execute().data
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--min-jaccard", type=float, default=0.7)
    args = parser.parse_args()

    print("Fetching restaurants…")
    restaurants = _fetch_all("restaurants", "id,name,slug,cuisine,image_url")
    print(f"  {len(restaurants)} rows")

    print("Fetching platform listings…")
    listings = _fetch_all("platform_listings", "id,restaurant_id,platform")
    print(f"  {len(listings)} rows")

    rid_to_platforms: dict[str, set[str]] = defaultdict(set)
    for lst in listings:
        rid_to_platforms[lst["restaurant_id"]].add(lst["platform"])

    # Filter junk restaurants before processing
    restaurants = [r for r in restaurants if not _JUNK_PATTERNS.match(r["name"].strip())]
    print(f"  {len(restaurants)} after junk filter")

    rid_to_info: dict[str, dict] = {r["id"]: r for r in restaurants}
    rid_to_tokens: dict[str, frozenset] = {r["id"]: _normalize_tokens(r["name"]) for r in restaurants}

    # Build inverted index: token → [restaurant_ids]
    token_index: dict[str, list[str]] = defaultdict(list)
    for rid, toks in rid_to_tokens.items():
        for tok in toks:
            token_index[tok].append(rid)

    # Find merge candidates
    seen: set[tuple[str, str]] = set()
    candidates: list[tuple[dict, dict, float]] = []

    for rids in token_index.values():
        if len(rids) < 2:
            continue
        for i in range(len(rids)):
            for j in range(i + 1, len(rids)):
                rid_a, rid_b = rids[i], rids[j]
                key = (min(rid_a, rid_b), max(rid_a, rid_b))
                if key in seen:
                    continue
                seen.add(key)

                tok_a = rid_to_tokens[rid_a]
                tok_b = rid_to_tokens[rid_b]

                if not _is_candidate(tok_a, tok_b, args.min_jaccard):
                    continue

                # Skip if they share a platform — definitely different branches
                plats_a = rid_to_platforms.get(rid_a, set())
                plats_b = rid_to_platforms.get(rid_b, set())
                if plats_a & plats_b:
                    continue

                j_score = _jaccard(tok_a, tok_b)
                candidates.append((rid_to_info[rid_a], rid_to_info[rid_b], j_score))

    candidates.sort(key=lambda x: -x[2])

    print(f"\nFound {len(candidates)} merge candidates (min_jaccard={args.min_jaccard})")
    if not candidates:
        return

    print("\nTop candidates:")
    for ra, rb, j in candidates[:40]:
        plats_a = sorted(rid_to_platforms.get(ra["id"], set()))
        plats_b = sorted(rid_to_platforms.get(rb["id"], set()))
        print(f"  [{j:.2f}] '{ra['name']}' [{','.join(plats_a)}]")
        print(f"         '{rb['name']}' [{','.join(plats_b)}]")

    if len(candidates) > 40:
        print(f"  … and {len(candidates) - 40} more")

    if not args.execute:
        print(f"\nDry-run. Pass --execute to merge {len(candidates)} pairs.")
        return

    print(f"\nMerging {len(candidates)} pairs…")
    merged = errors = 0

    for ra, rb, _ in candidates:
        plats_a = rid_to_platforms.get(ra["id"], set())
        plats_b = rid_to_platforms.get(rb["id"], set())
        # Keep the one with more platforms; tie → keep more complete data (has image)
        if len(plats_a) > len(plats_b):
            keep, drop = ra, rb
        elif len(plats_b) > len(plats_a):
            keep, drop = rb, ra
        else:
            keep = ra if ra.get("image_url") else rb
            drop = rb if keep["id"] == ra["id"] else ra

        try:
            # Enrich keeper with any data the dropped row has that the keeper lacks
            updates: dict = {}
            if not keep.get("cuisine") and drop.get("cuisine"):
                updates["cuisine"] = drop["cuisine"]
            if not keep.get("image_url") and drop.get("image_url"):
                updates["image_url"] = drop["image_url"]
            if updates:
                client.table("restaurants").update(updates).eq("id", keep["id"]).execute()

            # Re-home all listings from drop → keep
            client.table("platform_listings").update(
                {"restaurant_id": keep["id"]}
            ).eq("restaurant_id", drop["id"]).execute()

            # Delete the orphaned restaurant
            client.table("restaurants").delete().eq("id", drop["id"]).execute()

            merged += 1
            print(f"  ✓ '{drop['name']}' → '{keep['name']}'")
        except Exception as exc:
            errors += 1
            print(f"  ✗ {drop['id']}: {exc}", file=sys.stderr)

    print(f"\nDone — {merged} merged, {errors} errors")


if __name__ == "__main__":
    main()
