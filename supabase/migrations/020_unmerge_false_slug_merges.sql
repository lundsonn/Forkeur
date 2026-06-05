-- Undo false merges caused by slug_match firing on Takeaway ?c_id= chain URLs.
-- restaurants.slug + is_chain are NOT NULL → supply both when re-creating rows.
-- Idempotent: guarded by IF EXISTS on the specific misplaced listing ids.

-- 1. Chamas Tacos Ecuyer: re-create restaurant, move ecuyer Deliveroo listing back.
DO $$
DECLARE v_new uuid := gen_random_uuid();
BEGIN
  IF EXISTS (
    SELECT 1 FROM platform_listings
    WHERE id = 'c0b3ec78-4da4-40ea-b0f7-f0b318216ccb'
      AND url ILIKE '%ecuyer%'
      AND restaurant_id = '843d15c9-2fc5-483c-a322-19989c1eacc1'
  ) THEN
    INSERT INTO restaurants (id, name, slug, is_chain)
      VALUES (v_new, 'Chamas Tacos Ecuyer', 'chamas-tacos-ecuyer-' || substr(v_new::text,1,8), false)
      ON CONFLICT DO NOTHING;
    UPDATE platform_listings SET restaurant_id = v_new WHERE id = 'c0b3ec78-4da4-40ea-b0f7-f0b318216ccb';
  END IF;
END $$;

-- 2. Late Night Pizza Liège listing: delete (out of Brussels scope, wrong city).
DELETE FROM platform_listings
WHERE id = '846d1fb0-7117-4778-af5c-7ed23e7c20b9' AND url ILIKE '%liege%';

-- 3. Le Pain Quotidien — re-split Lepoutre (deliveroo+takeaway) + Sablon (uber_eats)
--    from the false "Louise" merge. These are distinct LPQ locations.
DO $$
DECLARE v_lepoutre uuid := gen_random_uuid();
        v_sablon   uuid := gen_random_uuid();
BEGIN
  IF EXISTS (SELECT 1 FROM platform_listings WHERE id = 'da99fbda-9b54-42f4-b8f7-32f0d25c5b8d' AND restaurant_id = '0a38bc9f-a3c7-4cea-8bef-d98d002b35be') THEN
    INSERT INTO restaurants (id, name, slug, is_chain)
      VALUES (v_lepoutre, 'Le Pain Quotidien Lepoutre', 'le-pain-quotidien-lepoutre-' || substr(v_lepoutre::text,1,8), false) ON CONFLICT DO NOTHING;
    UPDATE platform_listings SET restaurant_id = v_lepoutre WHERE id = 'da99fbda-9b54-42f4-b8f7-32f0d25c5b8d';
    UPDATE platform_listings SET restaurant_id = v_lepoutre WHERE id = '5b8d0815-8153-4a31-b14e-509e37831c22' AND restaurant_id = '0a38bc9f-a3c7-4cea-8bef-d98d002b35be';
  END IF;
  IF EXISTS (SELECT 1 FROM platform_listings WHERE id = 'f51eeb31-151b-49e1-a600-3d548989c9ff' AND restaurant_id = '0a38bc9f-a3c7-4cea-8bef-d98d002b35be') THEN
    INSERT INTO restaurants (id, name, slug, is_chain)
      VALUES (v_sablon, 'Le Pain Quotidien Sablon', 'le-pain-quotidien-sablon-' || substr(v_sablon::text,1,8), false) ON CONFLICT DO NOTHING;
    UPDATE platform_listings SET restaurant_id = v_sablon WHERE id = 'f51eeb31-151b-49e1-a600-3d548989c9ff';
  END IF;
END $$;

-- 4. Delete the false auto_merged decision rows.
DELETE FROM restaurant_match_decisions
WHERE status = 'auto_merged'
  AND (features->>'slug_match')::boolean = true
  AND features->>'loser_name' IN (
    'Chamas Tacos Ecuyer', 'Carrefour Express Rogier', 'Domino''s Pizza Evere',
    'Late Night Pizza Etterbeek', 'Le Pain Quotidien Louise'
  );

-- Note: Carrefour Express Rogier + Domino's Pizza Evere had no identifiable
-- remaining listings (lost in merge dedup). Re-scraping re-discovers them.
