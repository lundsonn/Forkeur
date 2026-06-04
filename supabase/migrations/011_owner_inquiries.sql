-- Extend restaurant_claims to support owner inquiries beyond "add URL":
-- new_listing: owner wants their restaurant added to Forkeur
-- remove: owner wants their restaurant removed
-- add_url (default): existing flow — owner adds/updates direct ordering URL

alter table restaurant_claims
  alter column restaurant_id drop not null,
  add column if not exists inquiry_type text not null default 'add_url',
  add column if not exists restaurant_name_free text;
