-- ─────────────────────────────────────────────────────────────────────────────
-- forkeur — Supabase Schema
-- Run this in: Supabase Dashboard → SQL Editor → New Query → Run
-- ─────────────────────────────────────────────────────────────────────────────

-- One record per physical restaurant (independent of platform)
create table restaurants (
  id           uuid default gen_random_uuid() primary key,
  name         text not null,
  city         text not null default 'Brussels',
  address      text,
  cuisine      text[],                -- e.g. ['Burgers', 'Fast Food']
  created_at   timestamptz default now(),
  updated_at   timestamptz default now()
);

-- One record per restaurant × platform combination
-- e.g. McDonald's on Uber Eats = 1 row, McDonald's on Deliveroo = 1 row
create table platform_listings (
  id                 uuid default gen_random_uuid() primary key,
  restaurant_id      uuid references restaurants(id) on delete cascade,
  platform           text not null check (platform in ('uber_eats', 'deliveroo', 'takeaway')),
  platform_url       text,
  delivery_fee_cents integer,         -- always store money as integers (cents)
  delivery_fee_label text,            -- human-readable: "€3.99" or "Free"
  min_order_cents    integer,
  eta_min            integer,         -- minutes
  eta_max            integer,
  eta_label          text,            -- human-readable: "10–20 min"
  rating             numeric(3,1),
  rating_count       text,            -- "20000+" as returned by platform
  hero_image_url     text,
  is_open            boolean default true,
  scraped_at         timestamptz default now(),

  unique(restaurant_id, platform)
);

-- One record per menu item per platform listing
-- Prices differ per platform — that's the whole point!
create table menu_items (
  id            uuid default gen_random_uuid() primary key,
  listing_id    uuid references platform_listings(id) on delete cascade,
  name          text not null,
  description   text,
  price_cents   integer,              -- e.g. 620 = €6.20
  price_label   text,                 -- "€6.20"
  category      text,
  image_url     text
);

-- Restaurants that have their own direct ordering page
create table direct_links (
  id              uuid default gen_random_uuid() primary key,
  restaurant_id   uuid references restaurants(id) on delete cascade,
  url             text not null,
  phone           text,
  notes           text,
  is_verified     boolean default false,
  added_at        timestamptz default now()
);

-- ── Indexes (makes searches fast) ────────────────────────────────────────────
create index on restaurants (city);
create index on restaurants using gin(to_tsvector('simple', name));  -- full-text search
create index on platform_listings (restaurant_id);
create index on platform_listings (platform);
create index on platform_listings (delivery_fee_cents);
create index on menu_items (listing_id);

-- ── Row-Level Security (safe to query from the browser) ───────────────────────
alter table restaurants       enable row level security;
alter table platform_listings enable row level security;
alter table menu_items        enable row level security;
alter table direct_links      enable row level security;

-- Public read: all this data is publicly visible on the delivery apps anyway
create policy "Public read" on restaurants       for select using (true);
create policy "Public read" on platform_listings for select using (true);
create policy "Public read" on menu_items        for select using (true);
create policy "Public read" on direct_links      for select using (true);

-- ── Useful view: cheapest platform per restaurant ─────────────────────────────
-- Use this to power "X is cheapest right now" badges
create or replace view cheapest_per_restaurant as
select distinct on (restaurant_id)
  restaurant_id,
  platform,
  delivery_fee_cents,
  delivery_fee_label,
  eta_label,
  rating
from platform_listings
where is_open = true
  and delivery_fee_cents is not null
order by restaurant_id, delivery_fee_cents asc;
