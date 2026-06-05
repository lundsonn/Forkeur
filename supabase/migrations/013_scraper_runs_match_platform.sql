-- Allow the batch matcher job to record scraper_runs rows.
alter table scraper_runs drop constraint if exists scraper_runs_platform_check;
alter table scraper_runs add constraint scraper_runs_platform_check
  check (platform = any (array['ubereats','deliveroo','takeaway','fees','direct','direct_menu','dom_menu','match']));
