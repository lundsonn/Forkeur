-- 027_presence_probes.sql
-- Presence probe: per (restaurant, missing_platform) record of whether a
-- restaurant currently on exactly ONE delivery platform ALSO exists on a
-- platform it is missing from. Written by the presence-probe runner.
--
-- The outcome is deliberately 3-way and must never collapse to a binary:
--   present   - a candidate confidently matches the venue, deliverable to the
--               restaurant's own pin -> recoverable (a scraper can pick it up)
--   absent    - search succeeded, no candidate corroborates -> genuine exclusive
--   uncertain - a candidate was found but proximity/cuisine/name did not
--               corroborate confidently, OR the search itself was blocked/captcha'd
--
-- This table doubles as the recovery queue: every `present` row is a listing a
-- scraper can go back and pick up.
--
-- Platform-name gotcha: missing_platform uses the platform_listings form with an
-- underscore ('uber_eats'), NOT the scraper_runs form ('ubereats').
--
-- Apply as the postgres superuser, then:
--   GRANT SELECT, INSERT, UPDATE, DELETE ON presence_probes TO forkeur_app;

CREATE TABLE IF NOT EXISTS presence_probes (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    restaurant_id        uuid NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    missing_platform     text NOT NULL CHECK (missing_platform IN ('uber_eats', 'deliveroo', 'takeaway')),
    outcome              text NOT NULL CHECK (outcome IN ('present', 'absent', 'uncertain')),
    matched_url          text,
    candidate_distance_m numeric,
    candidate_name       text,
    pin_address          text,
    block_reason         text,
    checked_at           timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_presence_probe
    ON presence_probes (restaurant_id, missing_platform);

CREATE INDEX IF NOT EXISTS idx_presence_probe_outcome
    ON presence_probes (outcome);
