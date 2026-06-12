-- 021_contact_enrichment.sql
-- Multi-source contact enrichment with corroboration.
--
-- Phone data from any single scraped source is only ~63% reliable (measured:
-- FSQ vs existing DB phone agree 63% even on exact name + <30m matches). So we
-- never blind-overwrite: every source writes a *candidate* row, and a resolver
-- computes the winning phone + a confidence tier from cross-source agreement.
--
-- order_channel captures whether a venue takes orders directly (own site / phone)
-- or only redirects to a platform we already cover (UberEats/Deliveroo/Takeaway),
-- which determines whether it has any "order direct" advantage to surface.

CREATE TABLE IF NOT EXISTS restaurant_contact_candidates (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    restaurant_id uuid NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    source        text NOT NULL,    -- 'google_maps' | 'website' | 'fsq' | 'osm' | 'kbo' | 'jsonld' | 'modal'
    phone_e164    text,             -- E.164 normalized; NULL when the source yielded no phone
    phone_raw     text,             -- as-seen, for audit
    website       text,
    order_channel text,             -- 'direct' | 'covered_platform' | 'unknown'
    covered_via   text,             -- platform domain matched, when order_channel='covered_platform'
    name_match    int,              -- 0-100 fuzzy score of source name vs restaurant name (provenance)
    fetched_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (restaurant_id, source)  -- one row per source per restaurant; re-runs upsert in place
);

CREATE INDEX IF NOT EXISTS idx_rcc_restaurant ON restaurant_contact_candidates(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_rcc_phone      ON restaurant_contact_candidates(phone_e164);

-- Resolved/derived fields cached on restaurants for cheap reads.
ALTER TABLE restaurants
    ADD COLUMN IF NOT EXISTS phone_confidence     text,        -- 'high' | 'medium' | 'low'
    ADD COLUMN IF NOT EXISTS phone_source         text,        -- winning source(s), e.g. 'google_maps+website'
    ADD COLUMN IF NOT EXISTS order_channel        text,        -- 'direct' | 'covered_platform' | 'unknown'
    ADD COLUMN IF NOT EXISTS contacts_enriched_at timestamptz;

-- Offline Foursquare OS Places slice (Brussels), used as a supplementary
-- corroboration source. Loaded once from the public dataset; matched by name+geo.
CREATE TABLE IF NOT EXISTS fsq_places (
    fsq_place_id text PRIMARY KEY,
    name         text,
    latitude     double precision,
    longitude    double precision,
    tel          text,
    website      text,
    email        text,
    categories   text[]
);
CREATE INDEX IF NOT EXISTS idx_fsq_latlng ON fsq_places(latitude, longitude);

-- Allow the enrichment job to record runs in scraper_runs.
ALTER TABLE scraper_runs DROP CONSTRAINT IF EXISTS scraper_runs_platform_check;
ALTER TABLE scraper_runs ADD CONSTRAINT scraper_runs_platform_check
    CHECK (platform = ANY (ARRAY[
        'ubereats','deliveroo','takeaway','fees','direct',
        'direct_menu','dom_menu','match','enrich'
    ]));
