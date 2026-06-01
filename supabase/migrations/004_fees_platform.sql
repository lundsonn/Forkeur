-- Allow 'fees' as a platform value in scraper_runs (fee refresh jobs)
alter table scraper_runs drop constraint scraper_runs_platform_check;
alter table scraper_runs add constraint scraper_runs_platform_check
  check (platform in ('ubereats', 'deliveroo', 'takeaway', 'fees'));
