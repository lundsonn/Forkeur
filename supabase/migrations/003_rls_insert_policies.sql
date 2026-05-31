-- Allow anon key (used by local backend) to write scraper data

-- scraper_runs: insert + update
create policy "service can insert scraper_runs"
  on scraper_runs for insert to anon with check (true);

create policy "service can update scraper_runs"
  on scraper_runs for update to anon using (true) with check (true);

-- restaurants: insert + update
create policy "service can insert restaurants"
  on restaurants for insert to anon with check (true);

create policy "service can update restaurants"
  on restaurants for update to anon using (true) with check (true);

-- platform_listings: insert + update
create policy "service can insert platform_listings"
  on platform_listings for insert to anon with check (true);

create policy "service can update platform_listings"
  on platform_listings for update to anon using (true) with check (true);

-- menu_items: insert + update + delete
create policy "service can insert menu_items"
  on menu_items for insert to anon with check (true);

create policy "service can update menu_items"
  on menu_items for update to anon using (true) with check (true);

create policy "service can delete menu_items"
  on menu_items for delete to anon using (true);
