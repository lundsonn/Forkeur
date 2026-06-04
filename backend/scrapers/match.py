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
    pairs = matching.block_candidates(rows)
    log_fn(f"{len(pairs)} candidate pairs after blocking")

    counts = {"auto_merge": 0, "queue": 0, "separate": 0}
    proposals: list[dict] = []
    touched_ids: set[str] = set()

    for a, b in pairs:
        if a["id"] in touched_ids or b["id"] in touched_ids:
            log_fn(f"  skip pair {a['id']}/{b['id']} — already merged this run (will reconcile next run)")
            continue
        features = matching.score_pair(a, b)
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

        if decision == matching.Decision.AUTO_MERGE:
            db.merge_restaurants(survivor["id"], loser["id"])
            touched_ids.add(survivor["id"])
            touched_ids.add(loser["id"])
            db.enqueue_decision(
                survivor_id=survivor["id"], loser_id=loser["id"],
                score=float(features.name_sim),
                features={**features.to_dict(), "survivor_name": survivor["name"], "loser_name": loser["name"]},
                status="auto_merged",
            )
        else:  # QUEUE
            db.enqueue_decision(
                survivor_id=survivor["id"], loser_id=loser["id"],
                score=float(features.name_sim),
                features={**features.to_dict(), "survivor_name": survivor["name"], "loser_name": loser["name"]},
                status="queued",
            )

    log_fn(f"auto_merge={counts['auto_merge']} queue={counts['queue']} separate={counts['separate']}")

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
