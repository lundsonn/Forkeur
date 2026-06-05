-- Enable RLS on scraper_schedules so anon/public cannot read or write schedule config.
-- The backend uses service_role which bypasses RLS, so no explicit policies needed.

alter table scraper_schedules enable row level security;
