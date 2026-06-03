-- Structured promotions table: one row per promotion per listing
CREATE TABLE promotions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id  UUID NOT NULL REFERENCES platform_listings(id) ON DELETE CASCADE,
  promo_type  TEXT NOT NULL,   -- free_delivery | bogo | pct_discount | abs_discount | free_item | spend_save | other
  label       TEXT NOT NULL,   -- raw label from platform (kept for display)
  value       NUMERIC,         -- 20 for "20% off", 5.0 for "€5 off", 0 for free delivery
  min_order   NUMERIC,         -- minimum order in EUR (e.g. 20 for "spend €20")
  scraped_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_promotions_listing  ON promotions(listing_id);
CREATE INDEX idx_promotions_type     ON promotions(promo_type);
CREATE INDEX idx_promotions_scraped  ON promotions(scraped_at DESC);

ALTER TABLE promotions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Promotions are publicly readable" ON promotions FOR SELECT USING (true);
