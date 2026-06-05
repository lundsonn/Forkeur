-- Allow 'direct' as a platform value in scraper_runs
ALTER TABLE scraper_runs DROP CONSTRAINT IF EXISTS scraper_runs_platform_check;
ALTER TABLE scraper_runs ADD CONSTRAINT scraper_runs_platform_check
  CHECK (platform IN ('ubereats', 'deliveroo', 'takeaway', 'fees', 'direct'));
