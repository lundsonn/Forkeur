-- ============================================================
-- Forkeur — initial schema migration
-- Run in Supabase SQL editor
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- Tables
-- ────────────────────────────────────────────────────────────

create table restaurants (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  slug          text unique not null,
  cuisine       text,
  neighborhood  text,
  lat           numeric(9,6),
  lng           numeric(9,6),
  needs_review  boolean default false,
  created_at    timestamptz default now()
);

create table platform_listings (
  id              uuid primary key default gen_random_uuid(),
  restaurant_id   uuid references restaurants(id) on delete cascade,
  platform        text not null check (platform in ('ubereats', 'deliveroo', 'takeaway')),
  url             text,
  rating          numeric(3,2),
  review_count    integer,
  eta_min         integer,
  eta_max         integer,
  delivery_fee    numeric(6,2),
  min_order       numeric(6,2),
  is_available    boolean default true,
  scraped_at      timestamptz default now()
);

create table menu_items (
  id            uuid primary key default gen_random_uuid(),
  listing_id    uuid references platform_listings(id) on delete cascade,
  catalog_name  text,
  title         text not null,
  price         numeric(6,2)
);

create table restaurant_claims (
  id                uuid primary key default gen_random_uuid(),
  restaurant_id     uuid references restaurants(id) on delete cascade,
  owner_email       text,
  direct_order_url  text,
  verified          boolean default false,
  claimed_at        timestamptz default now()
);

-- ────────────────────────────────────────────────────────────
-- Indexes
-- ────────────────────────────────────────────────────────────

create index on restaurants (slug);
create index on restaurants (needs_review);
create index on platform_listings (restaurant_id);
create index on platform_listings (platform);
create index on platform_listings (scraped_at);
create index on platform_listings (is_available);

-- ────────────────────────────────────────────────────────────
-- Row Level Security
-- ────────────────────────────────────────────────────────────

alter table restaurants         enable row level security;
alter table platform_listings   enable row level security;
alter table menu_items          enable row level security;
alter table restaurant_claims   enable row level security;

-- restaurants: anon read
create policy "anon can read restaurants"
  on restaurants for select
  to anon
  using (true);

-- platform_listings: anon read
create policy "anon can read platform_listings"
  on platform_listings for select
  to anon
  using (true);

-- menu_items: anon read
create policy "anon can read menu_items"
  on menu_items for select
  to anon
  using (true);

-- restaurant_claims: anon INSERT only (no SELECT — server reads via service key)
create policy "anon can insert restaurant_claims"
  on restaurant_claims for insert
  to anon
  with check (true);
