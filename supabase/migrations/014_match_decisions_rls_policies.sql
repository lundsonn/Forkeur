-- Backend uses the anon key with per-table policies (see migration 003).
-- Allow it to read/write the match-decisions queue/log table.
create policy "service can insert match_decisions"
  on restaurant_match_decisions for insert to anon with check (true);
create policy "service can update match_decisions"
  on restaurant_match_decisions for update to anon using (true) with check (true);
create policy "service can select match_decisions"
  on restaurant_match_decisions for select to anon using (true);
create policy "service can delete match_decisions"
  on restaurant_match_decisions for delete to anon using (true);
