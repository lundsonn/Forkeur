-- 028_menu_items_listing_id_index.sql
-- menu_items.listing_id is the FK to platform_listings(id) and the filter for
-- every menu read (get_menu_items WHERE listing_id = %s) and the per-listing
-- delete+reinsert in insert_menu_items. It had no index since 001 — those
-- queries table-scanned. Plain (non-CONCURRENTLY) build so it runs inside the
-- migration runner's per-file transaction; the table is small enough that the
-- brief write lock during build is acceptable.

CREATE INDEX IF NOT EXISTS menu_items_listing_id_idx ON menu_items (listing_id);
