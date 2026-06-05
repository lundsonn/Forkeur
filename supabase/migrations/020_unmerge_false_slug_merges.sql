-- Undo false merges caused by slug_match firing on Takeaway ?c_id= chain URLs.
-- Only recovers cases where the wrong listing is identifiable by URL content.

-- 1. Chamas Tacos Ecuyer: re-create restaurant, move ecuyer Deliveroo listing back.
DO $$
DECLARE v_new uuid := gen_random_uuid();
BEGIN
  -- Only run if the listing still points to the wrong restaurant.
  IF EXISTS (
    SELECT 1 FROM platform_listings
    WHERE id = 'c0b3ec78-4da4-40ea-b0f7-f0b318216ccb'
      AND url ILIKE '%ecuyer%'
      AND restaurant_id = '843d15c9-2fc5-483c-a322-19989c1eacc1'
  ) THEN
    INSERT INTO restaurants (id, name)
    VALUES (v_new, 'Chamas Tacos Ecuyer')
    ON CONFLICT DO NOTHING;

    UPDATE platform_listings
      SET restaurant_id = v_new
    WHERE id = 'c0b3ec78-4da4-40ea-b0f7-f0b318216ccb';
  END IF;
END $$;

-- 2. Late Night Pizza Liège listing: delete (out of Brussels scope, wrong city).
DELETE FROM platform_listings
WHERE id = '846d1fb0-7117-4778-af5c-7ed23e7c20b9'
  AND url ILIKE '%liege%';

-- 3. Le Pain Quotidien — the merged loser ("Le Pain Quotidien Louise") had
--    Deliveroo Lepoutre, Takeaway Lepoutre-Waterloo, and UberEats Sablon listings.
--    These are distinct LPQ locations, not "Louise". Re-create them as separate.
DO $$
DECLARE v_lepoutre uuid := gen_random_uuid();
        v_sablon   uuid := gen_random_uuid();
BEGIN
  -- Move Deliveroo Lepoutre
  IF EXISTS (SELECT 1 FROM platform_listings WHERE id = 'da99fbda-9b54-42f4-b8f7-32f0d25c5b8d' AND restaurant_id = '0a38bc9f-a3c7-4cea-8bef-d98d002b35be') THEN
    INSERT INTO restaurants (id, name) VALUES (v_lepoutre, 'Le Pain Quotidien Lepoutre') ON CONFLICT DO NOTHING;
    UPDATE platform_listings SET restaurant_id = v_lepoutre WHERE id = 'da99fbda-9b54-42f4-b8f7-32f0d25c5b8d';
    -- Takeaway Lepoutre-Waterloo goes with same restaurant
    UPDATE platform_listings SET restaurant_id = v_lepoutre WHERE id = '5b8d0815-8153-4a31-b14e-509e37831c22' AND restaurant_id = '0a38bc9f-a3c7-4cea-8bef-d98d002b35be';
  END IF;

  -- Move UberEats Sablon
  IF EXISTS (SELECT 1 FROM platform_listings WHERE id = 'f51eeb31-151b-49e1-a600-3d548989c9ff' AND restaurant_id = '0a38bc9f-a3c7-4cea-8bef-d98d002b35be') THEN
    INSERT INTO restaurants (id, name) VALUES (v_sablon, 'Le Pain Quotidien Sablon') ON CONFLICT DO NOTHING;
    UPDATE platform_listings SET restaurant_id = v_sablon WHERE id = 'f51eeb31-151b-49e1-a600-3d548989c9ff';
  END IF;
END $$;

-- 4. Delete the false auto_merged decision rows so the queue is clean.
--    (Decision audit is preserved in loser_name/survivor_name in features JSONB.)
DELETE FROM restaurant_match_decisions
WHERE status = 'auto_merged'
  AND (features->>'slug_match')::boolean = true
  AND features->>'loser_name' IN (
    'Chamas Tacos Ecuyer',
    'Carrefour Express Rogier',
    'Domino''s Pizza Evere',
    'Late Night Pizza Etterbeek',
    'Le Pain Quotidien Louise'
  );

-- Note: Carrefour Express Rogier and Domino's Pizza Evere have no identifiable
-- remaining listings. Their data was lost in the merge dedup. Re-scraping
-- Deliveroo/UberEats/Takeaway will re-discover them as new restaurants.
