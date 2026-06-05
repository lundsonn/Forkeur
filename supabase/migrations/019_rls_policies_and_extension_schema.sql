-- Tail-end audit cleanup:
--
-- 1. H1 — restaurant_match_decisions and scraper_schedules have RLS enabled
--    with no policy. Backend already uses service_role (which bypasses RLS),
--    so reads work; PostgREST anon clients return empty silently. Add an
--    explicit service-role-only policy. It documents intent and silences
--    the "rls_enabled_no_policy" linter without giving anon any extra access.
--
-- 2. unaccent / pg_trgm extensions live in `public`, exposing all their
--    functions (similarity, show_trgm, gtrgm_*, …) as EXECUTE-able by anon.
--    Confirmed zero indexes use gin_trgm_ops / gist_trgm_ops, so moving the
--    extensions to the `extensions` schema (which Supabase already provides)
--    is a no-op for query behaviour and removes the anon attack surface.

create policy "service_role manages match decisions"
  on public.restaurant_match_decisions
  for all
  to service_role
  using (true)
  with check (true);

create policy "service_role manages scraper schedules"
  on public.scraper_schedules
  for all
  to service_role
  using (true)
  with check (true);

alter extension unaccent set schema extensions;
alter extension pg_trgm set schema extensions;
