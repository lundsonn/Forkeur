-- Soft-delete for cross-platform merges: a merged restaurant points at its
-- survivor instead of being hard-deleted (backend uses the anon key, which has
-- no DELETE grant). Consumers filter `merged_into is null`.
alter table restaurants
  add column if not exists merged_into uuid references restaurants(id) on delete set null;
create index if not exists idx_restaurants_merged_into on restaurants(merged_into);
