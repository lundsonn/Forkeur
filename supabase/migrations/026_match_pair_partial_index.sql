-- 026_match_pair_partial_index.sql
-- Fix: uq_match_pair (from 012) collides when a survivor absorbs a 2nd loser.
--
-- merge_restaurants_atomic deletes the loser row; loser_id has ON DELETE SET NULL
-- (012:12), so the resolved decision's key collapses from (survivor, loser) to
-- (survivor, survivor) via LEAST/GREATEST. A survivor that later absorbs another
-- loser produces a second (survivor, survivor) key and trips the unique index —
-- the delete inside merge_restaurants_atomic aborts and the merge silently fails
-- (observed: ghost-kitchen phone clusters put many losers on one survivor, so
-- auto-merge stalled at a fixed non-zero count, never converging).
--
-- Make the uniqueness apply only to live (unresolved) decisions. Resolved rows
-- (loser_id IS NULL after a merge) are historical and must not constrain new pairs.

DROP INDEX IF EXISTS uq_match_pair;

CREATE UNIQUE INDEX IF NOT EXISTS uq_match_pair
  ON restaurant_match_decisions (
    LEAST(survivor_id, loser_id),
    GREATEST(survivor_id, loser_id)
  )
  WHERE loser_id IS NOT NULL;
