-- Track when a listing's menu was last successfully scraped.
-- Used by the frontend to show staleness warnings and by the health endpoint.
ALTER TABLE platform_listings
  ADD COLUMN IF NOT EXISTS last_scraped_at TIMESTAMPTZ;
