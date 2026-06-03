-- Allow 'direct' as a platform (restaurant's own ordering channel)
ALTER TABLE platform_listings DROP CONSTRAINT platform_listings_platform_check;
ALTER TABLE platform_listings ADD CONSTRAINT platform_listings_platform_check
  CHECK (platform = ANY (ARRAY['uber_eats','deliveroo','takeaway','direct']));

-- Phone number for direct/phone ordering
ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS phone text;
