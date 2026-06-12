-- 025_fee_snapshots.sql
-- Per-upsert history of delivery fee + timing + minimum order for trend analysis.
-- Written by db.insert_fee_snapshot() on every upsert_listing that carries at
-- least one fee/timing value.

CREATE TABLE IF NOT EXISTS fee_snapshots (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id   uuid NOT NULL REFERENCES platform_listings(id) ON DELETE CASCADE,
    delivery_fee numeric(6,2),
    eta_min      integer,
    eta_max      integer,
    min_order    numeric(6,2),
    captured_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS fee_snapshots_listing_captured_idx
    ON fee_snapshots (listing_id, captured_at DESC);
