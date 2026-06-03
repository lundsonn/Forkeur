ALTER TABLE platform_listings
  ADD COLUMN IF NOT EXISTS url_type text
  CHECK (url_type IN ('ordering', 'menu', 'website', 'phone'));
