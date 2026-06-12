-- 023_menu_items_scraped_at.sql
-- Stamp each menu_item with an insert-time scraped_at so freshness survives even
-- when the parent listing's last_scraped_at is NULL. Drives the COALESCE cleanup
-- predicates (delete_stale_listings / prune_stale_menu_items) that reap rows a
-- fee-only refresh would otherwise leave immortal.

ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS scraped_at timestamptz DEFAULT now();

CREATE INDEX IF NOT EXISTS menu_items_scraped_at_idx ON menu_items (scraped_at);
