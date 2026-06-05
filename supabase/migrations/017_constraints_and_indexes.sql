-- Hardening pass: add missing constraints + indexes flagged in the codebase review.
-- All statements are idempotent so this migration is safe to re-run.

-- 1. Missing FK index on the matching review queue.
create index if not exists idx_match_loser_id
  on restaurant_match_decisions (loser_id);

-- 2. CHECK constraint on the match decision status (previously any string was accepted).
alter table restaurant_match_decisions
  drop constraint if exists match_status_check;
alter table restaurant_match_decisions
  add constraint match_status_check
  check (status in ('auto_merged', 'queued', 'approved', 'rejected', 'separated'));

-- 3. Prevent self-merges (survivor == loser would silently corrupt the merge logic).
alter table restaurant_match_decisions
  drop constraint if exists match_distinct_pair;
alter table restaurant_match_decisions
  add constraint match_distinct_pair
  check (survivor_id is null or loser_id is null or survivor_id <> loser_id);

-- 4. Promotions: dedupe by (listing_id, label). The application replaces all
--    promos for a listing on each scrape but a partial failure could leave
--    duplicates; this catches the case.
create unique index if not exists uq_promotions_listing_label
  on promotions (listing_id, label);

-- 5. restaurant_claims: enforce the new_listing↔restaurant_id pairing
--    introduced informally in migration 011 (NULL restaurant_id is only valid
--    for inquiry_type='new_listing').
alter table restaurant_claims
  drop constraint if exists claims_restaurant_or_freeform;
alter table restaurant_claims
  add constraint claims_restaurant_or_freeform
  check (
    (inquiry_type = 'new_listing' and restaurant_id is null)
    or (inquiry_type <> 'new_listing' and restaurant_id is not null)
  ) not valid;
-- not valid: legacy rows are not retro-checked. New writes are enforced.

-- 6. owner_email: format check (regex is intentionally loose; pydantic does the
--    strict parse in the API layer). Old NULLs preserved via NOT VALID.
alter table restaurant_claims
  drop constraint if exists claims_owner_email_format;
alter table restaurant_claims
  add constraint claims_owner_email_format
  check (owner_email is null or owner_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$')
  not valid;

-- 7. Transactional merge RPC. Previously merge_restaurants() ran a sequence of
--    individual PostgREST writes; a mid-operation failure left the DB in an
--    inconsistent state (listings moved but loser not deleted, or vice versa).
--    This wraps the whole sequence in a single transaction with proper locks.
create or replace function merge_restaurants_atomic(
  p_survivor uuid,
  p_loser uuid
) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_loser_listing record;
  v_clash_id uuid;
begin
  if p_survivor = p_loser then return; end if;

  -- Lock both rows for the duration of the merge so concurrent matchers can't
  -- both try to fold the same loser into different survivors.
  perform 1 from restaurants where id in (p_survivor, p_loser) for update;

  if not exists (select 1 from restaurants where id = p_survivor)
     or not exists (select 1 from restaurants where id = p_loser) then
    return;
  end if;

  -- Move listings, resolving (restaurant_id, platform) conflicts by keeping
  -- the row with the most recent last_scraped_at.
  for v_loser_listing in
    select id, platform, last_scraped_at
    from platform_listings
    where restaurant_id = p_loser
  loop
    select id into v_clash_id
    from platform_listings
    where restaurant_id = p_survivor
      and platform = v_loser_listing.platform
    limit 1;

    if v_clash_id is not null then
      if coalesce(v_loser_listing.last_scraped_at, 'epoch'::timestamptz)
         > coalesce(
             (select last_scraped_at from platform_listings where id = v_clash_id),
             'epoch'::timestamptz
           ) then
        delete from platform_listings where id = v_clash_id;
      else
        delete from platform_listings where id = v_loser_listing.id;
        continue;
      end if;
    end if;

    update platform_listings
      set restaurant_id = p_survivor
      where id = v_loser_listing.id;
  end loop;

  -- Fill survivor nulls from loser.
  update restaurants s
    set phone       = coalesce(s.phone,       l.phone),
        website     = coalesce(s.website,     l.website),
        lat         = coalesce(s.lat,         l.lat),
        lng         = coalesce(s.lng,         l.lng),
        geo_source  = coalesce(s.geo_source,  l.geo_source),
        cuisine     = coalesce(s.cuisine,     l.cuisine),
        image_url   = coalesce(s.image_url,   l.image_url)
    from restaurants l
    where s.id = p_survivor
      and l.id = p_loser;

  delete from restaurants where id = p_loser;
end;
$$;

-- NOTE: The platform naming split (platform_listings.platform = 'uber_eats'
-- vs. scraper_runs.platform = 'ubereats') is documented in CLAUDE.md. A future
-- migration should normalize both to a single value, but doing so requires a
-- coordinated code change across both the backend and the Next.js app and is
-- intentionally out of scope here.
