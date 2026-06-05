-- Remove anon write policies added in 003 and 014.
-- The backend must use SUPABASE_SERVICE_KEY (service_role) for writes, not the public anon key.
-- The anon key is embedded in the public JS bundle and must only be used for reads.

drop policy if exists "service can insert scraper_runs"         on scraper_runs;
drop policy if exists "service can update scraper_runs"         on scraper_runs;
drop policy if exists "service can insert restaurants"          on restaurants;
drop policy if exists "service can update restaurants"          on restaurants;
drop policy if exists "service can insert platform_listings"    on platform_listings;
drop policy if exists "service can update platform_listings"    on platform_listings;
drop policy if exists "service can insert menu_items"           on menu_items;
drop policy if exists "service can update menu_items"           on menu_items;
drop policy if exists "service can delete menu_items"           on menu_items;
drop policy if exists "anon can insert match decisions"         on restaurant_match_decisions;
drop policy if exists "anon can update match decisions"         on restaurant_match_decisions;
