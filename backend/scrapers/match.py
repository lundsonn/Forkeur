"""Batch restaurant matcher job.

Loads all restaurants, blocks candidates, scores, and either executes merges
(auto-merge band) + enqueues review rows (queue band), or — in dry-run — just
counts and logs proposed actions without writing.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import db
import matching
from models import ScraperConfig, ScraperResult


def _survivor_loser(a: dict, b: dict) -> tuple[dict, dict]:
    """Oldest created_at survives; tiebreak by most non-null fields."""
    def score(r: dict) -> tuple:
        non_null = sum(1 for k in ("phone", "website", "lat", "cuisine", "image_url") if r.get(k))
        return (r.get("created_at") or "", -non_null)
    return (a, b) if score(a) <= score(b) else (b, a)


def run_sync(*, dry_run: bool, log_fn) -> dict:
    rows = db.load_restaurants_for_match()
    log_fn(f"Loaded {len(rows)} restaurants")

    # Warm the matching cache so each restaurant's values are computed once.
    for _r in rows:
        matching.normalize_name(_r["name"])
        matching.normalize_match_key(_r["name"])
        matching.domain_of(_r.get("website"))
        matching.phone_digits(_r.get("phone"))

    pairs = matching.block_candidates(rows)
    log_fn(f"{len(pairs)} candidate pairs after blocking")

    # Load supplementary data for enhanced scoring
    menus_raw = db.load_menu_items_for_match()
    slugs = db.load_slugs_for_match()
    # Build chain_names: significant first tokens appearing 3+ times.
    # Uses significant_first_token (not full normalize_match_key) so
    # "McDonald's Bascule" and "McDonald's Bourse" both count as "mcdonalds".
    tok_counts: dict[str, int] = {}
    for r in rows:
        tok = matching.significant_first_token(r["name"])
        if tok and len(tok) >= 4:
            tok_counts[tok] = tok_counts.get(tok, 0) + 1
    chain_names = {tok for tok, count in tok_counts.items() if count >= 3}
    log_fn(
        f"Supplementary: {len(menus_raw)} restaurants with menus, "
        f"{len(chain_names)} chain names"
    )

    counts = {"auto_merge": 0, "queue": 0, "separate": 0}
    proposals: list[dict] = []
    touched_ids: set[str] = set()

    for a, b in pairs:
        if a["id"] in touched_ids or b["id"] in touched_ids:
            log_fn(f"  skip pair {a['id']}/{b['id']} — already merged this run (will reconcile next run)")
            continue
        features = matching.score_pair(a, b, menus=menus_raw, chain_names=chain_names, slugs=slugs)
        decision = matching.decide(features)
        counts[decision.value] += 1
        if decision == matching.Decision.SEPARATE:
            continue

        survivor, loser = _survivor_loser(a, b)
        proposals.append({
            "survivor_id": survivor["id"], "survivor_name": survivor["name"],
            "loser_id": loser["id"], "loser_name": loser["name"],
            "decision": decision.value, "features": features.to_dict(),
        })

        if dry_run:
            continue

        feat_payload = {**features.to_dict(),
                        "survivor_name": survivor["name"], "loser_name": loser["name"]}
        # Isolate each pair: a single failed merge/enqueue must not abort the
        # whole batch — log it and move on so the rest still reconciles.
        try:
            if decision == matching.Decision.AUTO_MERGE:
                db.merge_restaurants(survivor["id"], loser["id"])
                touched_ids.add(survivor["id"])
                touched_ids.add(loser["id"])
                db.enqueue_decision(
                    survivor_id=survivor["id"], loser_id=loser["id"],
                    score=float(features.name_sim), features=feat_payload,
                    status="auto_merged",
                )
            else:  # QUEUE
                db.enqueue_decision(
                    survivor_id=survivor["id"], loser_id=loser["id"],
                    score=float(features.name_sim), features=feat_payload,
                    status="queued",
                )
        except Exception as e:
            log_fn(f"  pair {survivor['id']}<-{loser['id']} failed ({decision.value}): {e}")
            continue

    log_fn(f"auto_merge={counts['auto_merge']} queue={counts['queue']} separate={counts['separate']}")

    # --- Re-score stale queued decisions ---
    # Pairs created before venue coords were extracted have geo_dist=null.
    # Re-score them now that both sides may be venue-grade.
    rows_by_id = {str(r["id"]): r for r in rows}
    stale = db.get_stale_queued_decisions()
    log_fn(f"Re-score pass: {len(stale)} stale queued decisions with null geo_dist")
    rescored = {"upgraded": 0, "refreshed": 0}

    for dec in stale:
        sid = str(dec["survivor_id"])
        lid = str(dec["loser_id"])
        ra = rows_by_id.get(sid)
        rb = rows_by_id.get(lid)
        if not ra or not rb:
            continue
        if not (matching.is_venue_grade(ra) and matching.is_venue_grade(rb)):
            continue

        features = matching.score_pair(ra, rb, menus=menus_raw, chain_names=chain_names, slugs=slugs)
        if features.geo_dist is None:
            continue  # still not both venue-grade after re-check

        decision = matching.decide(features)
        feat_payload = {**features.to_dict(), "survivor_name": ra["name"], "loser_name": rb["name"]}

        if dry_run:
            rescored["refreshed"] += 1
            log_fn(f"  DRY rescore {ra['name']} / {rb['name']}: geo_dist={features.geo_dist:.0f}m → {decision.value}")
            continue

        try:
            if decision == matching.Decision.AUTO_MERGE and sid not in touched_ids and lid not in touched_ids:
                db.merge_restaurants(sid, lid)
                touched_ids.add(sid)
                touched_ids.add(lid)
                db.enqueue_decision(
                    survivor_id=sid, loser_id=lid,
                    score=float(features.name_sim), features=feat_payload, status="auto_merged",
                )
                counts["auto_merge"] += 1
                rescored["upgraded"] += 1
                log_fn(f"  upgraded {ra['name']} / {rb['name']}: geo_dist={features.geo_dist:.0f}m → auto_merged")
            else:
                db.enqueue_decision(
                    survivor_id=sid, loser_id=lid,
                    score=float(features.name_sim), features=feat_payload, status="queued",
                )
                rescored["refreshed"] += 1
        except Exception as e:
            log_fn(f"  rescore {sid}<-{lid} failed: {e}")

    log_fn(f"Re-score: upgraded={rescored['upgraded']} refreshed={rescored['refreshed']}")

    if dry_run:
        out_dir = os.path.join(os.path.dirname(__file__), "..", "match_output")
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = os.path.join(out_dir, f"dry-run-{stamp}.json")
        with open(path, "w") as f:
            json.dump({"counts": counts, "proposals": proposals}, f, indent=2, ensure_ascii=False)
        log_fn(f"DRY RUN — wrote {len(proposals)} proposals to {path}")

    return {**counts, "proposals": len(proposals)}


async def run(config: ScraperConfig, log_fn, **kwargs) -> ScraperResult:
    """Async adapter for the scraper router. dry_run via config.target == 'dry-run'."""
    import asyncio
    dry = (config.target or "").lower() == "dry-run"
    result = await asyncio.to_thread(run_sync, dry_run=dry, log_fn=log_fn)
    return ScraperResult(records_saved=result["auto_merge"])
