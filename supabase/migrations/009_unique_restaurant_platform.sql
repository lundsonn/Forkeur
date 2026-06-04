-- Prevent duplicate platform listings for the same restaurant.
-- upsert_listing() already enforces this in code; this makes it a hard
-- DB guarantee so concurrent inserts or manual imports can't produce dups.
ALTER TABLE platform_listings
  ADD CONSTRAINT uq_restaurant_platform UNIQUE (restaurant_id, platform);
