-- Close the hole flagged by the post-017 security audit:
-- restaurant_claims had an INSERT policy for `anon`, but RLS itself was
-- disabled — so PostgREST exposed full CRUD on the table to anonymous users.
-- That leaked every owner's email and let any visitor delete or rewrite the
-- claims queue.
--
-- Backend writes always use service_role (which bypasses RLS), so re-enabling
-- RLS doesn't break the legitimate flow; the existing anon INSERT policy is
-- preserved so a direct PostgREST POST from the public site would still work
-- if we ever wire it. No SELECT/UPDATE/DELETE policies for anon/authenticated:
-- only service_role can read or mutate.

alter table public.restaurant_claims enable row level security;

-- Defensive: re-assert the insert policy in case the prior environment was
-- modified out of band. CREATE POLICY is not IF NOT EXISTS, so drop first.
drop policy if exists "anon can insert restaurant_claims" on public.restaurant_claims;
create policy "anon can insert restaurant_claims"
  on public.restaurant_claims
  for insert
  to anon
  with check (true);
