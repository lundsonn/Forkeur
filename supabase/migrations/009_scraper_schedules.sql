create table if not exists scraper_schedules (
  platform   text primary key,
  cron       text not null,
  address    text not null,
  max_items  int,
  updated_at timestamptz not null default now()
);

alter table restaurants
  add column if not exists website_searched_at timestamptz;
