-- supabase/migrations/002_scraper_runs.sql
create table scraper_runs (
  id            uuid primary key default gen_random_uuid(),
  platform      text not null check (platform in ('ubereats', 'deliveroo', 'takeaway')),
  status        text not null check (status in ('running', 'success', 'failed', 'blocked', 'partial')),
  started_at    timestamptz default now(),
  finished_at   timestamptz,
  records_saved integer default 0,
  error_msg     text
);

create index on scraper_runs (platform);
create index on scraper_runs (status);
create index on scraper_runs (started_at desc);

alter table scraper_runs enable row level security;
create policy "anon can read scraper_runs"
  on scraper_runs for select to anon using (true);
