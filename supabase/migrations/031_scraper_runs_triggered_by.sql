-- Track whether a run was triggered manually (API) or by the cron scheduler.
ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS triggered_by varchar(16);
