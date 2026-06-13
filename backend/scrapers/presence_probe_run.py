"""Presence-probe runner.

For every restaurant currently on exactly ONE of uber_eats/deliveroo/takeaway,
check each platform it is *missing* from: set a delivery pin at the restaurant's
own address, run that platform's light search (scrapers.presence_search), and
classify the outcome (presence_probe.classify_presence) into present/absent/
uncertain. Each result is upserted into ``presence_probes`` — which doubles as a
recovery queue (every ``present`` row is a listing a scraper can pick up).

Two-stage by design:
  * Stage 1 — a bounded validation sample (``--sample N`` checks per missing
    platform). Reports counts + examples + block rate, then STOPS. Aborts early
    if the block/captcha rate climbs (detection canary) — we will not burn the
    production IP.
  * Stage 2 — ``--full`` runs every target.

Pacing / detection canary:
  * Within a platform group, checks run sequentially (concurrency 1) with
    jittered delays — well under a normal scrape's pace.
  * If ``PROXY_SERVER`` is set the three platform groups run concurrently
    (3 browsers); otherwise they run one after another on the datacenter IP.
  * Per group, once enough checks have run, a block rate above ABORT_BLOCK_RATE
    aborts the whole run.

Run:
  uv run python -m scrapers.presence_probe_run --sample 66     # ~200 checks, Stage 1
  uv run python -m scrapers.presence_probe_run --full          # Stage 2
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random

import httpx

from rapidfuzz.distance import JaroWinkler

import db
import pgpool
from matching import normalize_name
from presence_probe import classify_presence
from scrapers import presence_search as psearch
from scrapers.base import browser_session

# Pacing
_MIN_DELAY_S = float(os.getenv("PROBE_MIN_DELAY_S", "4"))
_MAX_DELAY_S = float(os.getenv("PROBE_MAX_DELAY_S", "9"))
# Canary
ABORT_BLOCK_RATE = float(os.getenv("PROBE_ABORT_BLOCK_RATE", "0.35"))
_CANARY_MIN_CHECKS = 20

_PLATFORMS = ("uber_eats", "deliveroo", "takeaway")
_NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
_NOMINATIM_HEADERS = {"User-Agent": "forkeur-presence-probe/1.0 (geraud.marion@gmail.com)"}


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

_TARGETS_SQL = """
WITH delivery_listings AS (
    SELECT restaurant_id, platform, street_address, postal_code
    FROM platform_listings
    WHERE platform IN ('uber_eats', 'deliveroo', 'takeaway')
),
agg AS (
    SELECT restaurant_id, array_agg(DISTINCT platform) AS platforms
    FROM delivery_listings
    GROUP BY restaurant_id
    HAVING count(DISTINCT platform) = 1
)
SELECT
    r.id            AS restaurant_id,
    r.name          AS name,
    r.lat           AS lat,
    r.lng           AS lng,
    r.cuisine       AS cuisine,
    a.platforms[1]  AS present_platform,
    dl.street_address,
    dl.postal_code
FROM agg a
JOIN restaurants r ON r.id = a.restaurant_id AND r.merged_into IS NULL
JOIN delivery_listings dl
    ON dl.restaurant_id = a.restaurant_id AND dl.platform = a.platforms[1]
"""


def load_targets() -> list[dict]:
    """One row per single-platform restaurant (present platform + own address)."""
    return pgpool.fetchall(_TARGETS_SQL)


def build_checks(targets: list[dict]) -> list[dict]:
    """Expand each restaurant into one check per *missing* platform."""
    checks: list[dict] = []
    for t in targets:
        for plat in _PLATFORMS:
            if plat == t["present_platform"]:
                continue
            checks.append({**t, "missing_platform": plat})
    return checks


def sample_checks(checks: list[dict], per_platform: int) -> list[dict]:
    """A balanced sample: up to ``per_platform`` checks for each missing platform."""
    out: list[dict] = []
    for plat in _PLATFORMS:
        pool = [c for c in checks if c["missing_platform"] == plat]
        random.shuffle(pool)
        out.extend(pool[:per_platform])
    random.shuffle(out)
    return out


# ---------------------------------------------------------------------------
# Pin address
# ---------------------------------------------------------------------------

async def _reverse_geocode(lat: float, lng: float, client: httpx.AsyncClient) -> str | None:
    try:
        resp = await client.get(
            _NOMINATIM_REVERSE,
            params={"lat": lat, "lon": lng, "format": "jsonv2"},
            headers=_NOMINATIM_HEADERS,
            timeout=10.0,
        )
        if resp.status_code == 200:
            return (resp.json() or {}).get("display_name")
    except Exception:
        pass
    return None


async def resolve_pin_address(check: dict, client: httpx.AsyncClient) -> str | None:
    """Street-address string for the typeahead. Own listing first, else reverse-geocode."""
    addr = (check.get("street_address") or "").strip()
    if addr:
        postal = (check.get("postal_code") or "").strip()
        return f"{addr}, {postal} Bruxelles" if postal else f"{addr}, Bruxelles"
    if check.get("lat") is not None and check.get("lng") is not None:
        await asyncio.sleep(1.1)  # Nominatim ToS: max 1 req/s
        return await _reverse_geocode(check["lat"], check["lng"], client)
    return None


# ---------------------------------------------------------------------------
# Single check
# ---------------------------------------------------------------------------

async def _run_search(browser, check: dict, pin_address: str | None):
    plat = check["missing_platform"]
    name = check["name"]
    if plat == "uber_eats":
        return await psearch.ubereats_search(browser, target_name=name, address=pin_address)
    if plat == "deliveroo":
        return await psearch.deliveroo_search(browser, target_name=name, address=pin_address)
    return await psearch.takeaway_search(browser, target_name=name, postal_code=check.get("postal_code"))


def _store(check: dict, result, pin_address: str | None) -> None:
    data = {
        "restaurant_id": check["restaurant_id"],
        "missing_platform": check["missing_platform"],
        "outcome": result.outcome,
        "matched_url": result.matched_url,
        "candidate_distance_m": result.candidate_distance_m,
        "candidate_name": result.candidate_name,
        "pin_address": pin_address,
        "block_reason": result.block_reason,
    }
    sql, params = db._build_insert(
        "presence_probes", data,
        on_conflict="restaurant_id,missing_platform",
        returning="id",
    )
    pgpool.fetchone(sql, params)


# ---------------------------------------------------------------------------
# Platform group (sequential, paced, canary)
# ---------------------------------------------------------------------------

class AbortRun(Exception):
    pass


async def _run_group(plat: str, checks: list[dict], client: httpx.AsyncClient, stats: dict, log) -> None:
    if not checks:
        return
    headed = psearch.SEARCHERS[plat][1]
    async with browser_session(lang="fr-BE", headed=headed) as browser:
        done = blocked = 0
        for i, check in enumerate(checks):
            pin = await resolve_pin_address(check, client)
            try:
                cands, is_blocked, reason = await _run_search(browser, check, pin)
            except Exception as exc:  # noqa: BLE001 — never let one check kill the group
                cands, is_blocked, reason = [], True, f"error:{type(exc).__name__}"
            # A non-blocked search that returned ZERO cards is a failed search, not
            # a proven negative: even when our venue is absent the area still lists
            # other restaurants. Treat empty as uncertain, never absent.
            if not is_blocked and not cands:
                is_blocked, reason = True, "no_candidates"
            result = classify_presence(
                lat=check["lat"], lng=check["lng"], cuisine=check.get("cuisine"),
                name=check["name"], candidates=cands, missing_platform=plat,
                blocked=is_blocked, block_reason=reason,
            )
            # Takeaway's public commune page exposes only ~27 venues (not the full
            # commune, not pin-sorted), so a non-hit there cannot prove absence.
            # Keep present-hits (a venue in the ~27 IS really on takeaway) but
            # downgrade absent -> uncertain so we never claim a false exclusive.
            if plat == "takeaway" and result.outcome == "absent":
                result.outcome = "uncertain"
                result.block_reason = "partial_coverage"
            # Auditability: on any non-present outcome that actually searched cards,
            # record the closest-by-name card seen (matched_url stays null — it is
            # NOT a match) so a human can sanity-check "nearest name was X".
            if cands and result.outcome != "present" and not result.candidate_name:
                tgt = normalize_name(check["name"])
                best = max(cands, key=lambda c: JaroWinkler.similarity(tgt, normalize_name(c.name)))
                result.candidate_name = best.name
            _store(check, result, pin)

            done += 1
            stats[result.outcome] += 1
            if is_blocked:
                blocked += 1
                stats["blocked"] += 1
            log(f"[{plat}] {done}/{len(checks)} {check['name'][:32]!r} "
                f"cards={len(cands)} -> {result.outcome}"
                + (f" ({result.block_reason})" if result.block_reason else "")
                + (f" {result.candidate_distance_m:.0f}m" if result.candidate_distance_m else ""))

            # Detection canary.
            if done >= _CANARY_MIN_CHECKS and blocked / done > ABORT_BLOCK_RATE:
                raise AbortRun(f"{plat}: block rate {blocked}/{done} > {ABORT_BLOCK_RATE:.0%} — aborting to protect the IP")

            if i < len(checks) - 1:
                await asyncio.sleep(random.uniform(_MIN_DELAY_S, _MAX_DELAY_S))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def run_probe(*, sample_per_platform: int | None, log=print) -> dict:
    targets = load_targets()
    checks = build_checks(targets)
    total_targets = len(targets)
    if sample_per_platform is not None:
        checks = sample_checks(checks, sample_per_platform)
    by_plat = {p: [c for c in checks if c["missing_platform"] == p] for p in _PLATFORMS}
    log(f"Targets: {total_targets} single-platform restaurants; "
        f"{len(checks)} checks ({', '.join(f'{p}={len(by_plat[p])}' for p in _PLATFORMS)})")

    stats = {"present": 0, "absent": 0, "uncertain": 0, "blocked": 0}
    use_proxy = bool(os.getenv("PROXY_SERVER"))
    log(f"Proxy: {'ON — platform groups run concurrently' if use_proxy else 'OFF — sequential, concurrency 1'}")

    run_id = db.create_run("match")  # diagnostic; logged under the cross-platform reconciliation channel
    aborted: str | None = None
    async with httpx.AsyncClient() as client:
        try:
            groups = [_run_group(p, by_plat[p], client, stats, log) for p in _PLATFORMS]
            if use_proxy:
                await asyncio.gather(*groups)
            else:
                for g in groups:
                    await g
        except AbortRun as exc:
            aborted = str(exc)
            log(f"ABORT: {aborted}")

    saved = stats["present"] + stats["absent"] + stats["uncertain"]
    db.finish_run(run_id, "failed" if aborted else "success", records_saved=saved,
                  error_msg=aborted)
    stats.update(targets=total_targets, checks=len(checks), aborted=aborted, run_id=run_id)
    return stats


def report(stats: dict, examples: int = 18) -> None:
    print("\n=== Presence probe — summary ===")
    n = max(stats["present"] + stats["absent"] + stats["uncertain"], 1)
    for k in ("present", "absent", "uncertain"):
        print(f"  {k:9} {stats[k]:5}  ({stats[k] / n:5.1%})")
    print(f"  blocked   {stats['blocked']:5}  ({stats['blocked'] / n:5.1%} of checks)")
    if stats.get("aborted"):
        print(f"  ABORTED: {stats['aborted']}")
    rows = pgpool.fetchall(
        "SELECT pp.missing_platform, pp.outcome, pp.candidate_distance_m, pp.matched_url, "
        "pp.candidate_name, r.name AS restaurant, pp.block_reason "
        "FROM presence_probes pp JOIN restaurants r ON r.id = pp.restaurant_id "
        "ORDER BY pp.checked_at DESC LIMIT %s", [examples])
    print(f"\n=== {len(rows)} most-recent example rows (eyeball these) ===")
    for r in rows:
        d = f"{r['candidate_distance_m']:.0f}m" if r["candidate_distance_m"] is not None else "-"
        print(f"  [{r['missing_platform']:9}] {r['outcome']:9} {d:>7}  {r['restaurant'][:30]:30} "
              f"-> {r['candidate_name'] or r['block_reason'] or ''} {r['matched_url'] or ''}")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sample", type=int, metavar="N", help="Stage 1: up to N checks per missing platform")
    g.add_argument("--full", action="store_true", help="Stage 2: every target")
    args = ap.parse_args()
    stats = asyncio.run(run_probe(sample_per_platform=None if args.full else args.sample))
    report(stats)


if __name__ == "__main__":
    main()
