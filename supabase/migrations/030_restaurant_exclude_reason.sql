-- 030: soft-exclude column for non-food / out-of-region restaurants
-- Values: 'non_food:grocery', 'non_food:convenience', 'non_food:press',
--         'non_food:pet', 'non_food:wine', 'non_food:candy',
--         'non_food:florist', 'non_food:video'
-- NULL = normal restaurant (included in public queries).

ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS exclude_reason TEXT;

-- Fast filter: public queries add WHERE r.exclude_reason IS NULL
CREATE INDEX IF NOT EXISTS idx_restaurants_exclude_reason
  ON restaurants (exclude_reason)
  WHERE exclude_reason IS NOT NULL;
