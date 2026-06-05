-- Geo + website scored restaurant matcher.
-- 1) geo_source: which platform set restaurants.lat/lng, so the matcher can
--    distinguish venue-grade coords (uber_eats/direct) from Deliveroo's
--    delivery-zone centroid (geohash) and Takeaway (none).
alter table restaurants
  add column if not exists geo_source text;

-- 2) restaurant_match_decisions: doubles as review queue + audit log.
create table if not exists restaurant_match_decisions (
  id           uuid primary key default gen_random_uuid(),
  survivor_id  uuid references restaurants(id) on delete cascade,
  loser_id     uuid references restaurants(id) on delete set null,
  score        numeric,
  features     jsonb,
  status       text not null,  -- auto_merged | queued | approved | rejected | separated
  created_at   timestamptz default now(),
  resolved_at  timestamptz,
  resolved_by  text
);

-- Prevent re-queuing the same unordered pair repeatedly.
create unique index if not exists uq_match_pair
  on restaurant_match_decisions (
    least(survivor_id, loser_id),
    greatest(survivor_id, loser_id)
  );

create index if not exists idx_match_status
  on restaurant_match_decisions (status);

-- RLS on, no anon write policy (service_role bypasses RLS) — per project convention.
alter table restaurant_match_decisions enable row level security;
