-- 024_scraper_runs_cleanup_platform.sql
-- Allow the stale-data cleanup job to record runs in scraper_runs.

ALTER TABLE scraper_runs DROP CONSTRAINT IF EXISTS scraper_runs_platform_check;
ALTER TABLE scraper_runs ADD CONSTRAINT scraper_runs_platform_check
    CHECK (platform = ANY (ARRAY[
        'ubereats','deliveroo','takeaway','fees','direct',
        'direct_menu','dom_menu','match','enrich','cleanup'
    ]));
