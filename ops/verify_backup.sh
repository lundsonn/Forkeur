#!/usr/bin/env bash
#
# verify_backup.sh — restore the latest forkeur pg_dump into a scratch DB and
# sanity-check it. Run this ON THE SERVER as an operator; it needs the postgres
# SUPERUSER and read access to /backups.
#
# Idempotent and non-destructive to the live `forkeur` database: it only ever
# touches a throwaway scratch DB (forkeur_restore_check), which is dropped on
# exit via a trap.
#
# Connection: connects directly to Postgres (PGHOST=127.0.0.1 PGPORT=5433) as
# the postgres superuser. You MUST provide superuser credentials out-of-band —
# either export PGUSER/PGPASSWORD, or set up ~/.pgpass for the postgres role.
#
#   Example:
#     PGUSER=postgres PGPASSWORD=... ./ops/verify_backup.sh
#
# ─── KNOWN LIMITATION (read this) ────────────────────────────────────────────
# The backup cron currently runs:
#     pg_dump -U forkeur_app forkeur | gzip > /backups/forkeur-$(date +%F).gz
# pg_dump as the `forkeur_app` role may NOT dump objects owned by `postgres`
# (extensions, and the `merge_restaurants_atomic` function). A restore can
# therefore "pass" row-count checks while silently missing that function.
# After this script passes, the operator should verify the merge function
# actually restored, e.g.:
#     psql -d forkeur_restore_check -c '\df merge_restaurants_atomic'   # (before drop)
# or, better, fix the cron to dump as the postgres superuser:
#     pg_dump -U postgres forkeur | gzip > /backups/forkeur-$(date +%F).gz
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RESTORE_DB="${RESTORE_DB:-forkeur_restore_check}"

export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5433}"

# Drop the scratch DB no matter how we exit (success, failure, or signal).
cleanup() {
  dropdb --if-exists "$RESTORE_DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ─── 1. Locate the most recent backup ────────────────────────────────────────
latest_backup="$(ls -1t "${BACKUP_DIR}"/forkeur-*.gz 2>/dev/null | head -n 1 || true)"
if [[ -z "${latest_backup}" ]]; then
  echo "FAIL: no backup files matching ${BACKUP_DIR}/forkeur-*.gz found." >&2
  exit 1
fi
echo "Using backup: ${latest_backup}"

# ─── 2. Restore into a fresh scratch DB ──────────────────────────────────────
echo "Recreating scratch database '${RESTORE_DB}'..."
dropdb --if-exists "$RESTORE_DB"
createdb "$RESTORE_DB"

echo "Restoring (this may take a while)..."
gunzip -c "$latest_backup" | psql --quiet --set ON_ERROR_STOP=on "$RESTORE_DB" >/dev/null

# ─── 3. Sanity row-counts on key tables ──────────────────────────────────────
TABLES=(restaurants platform_listings menu_items promotions scraper_runs)

count_table() {
  # Echoes the row count, or "ERR" if the table is missing / unreadable.
  psql --quiet --tuples-only --no-align -d "$RESTORE_DB" \
    -c "SELECT count(*) FROM ${1};" 2>/dev/null | tr -d '[:space:]' || echo "ERR"
}

echo
echo "Row counts in restored '${RESTORE_DB}':"
restaurants_count=0
for t in "${TABLES[@]}"; do
  c="$(count_table "$t")"
  printf '  %-20s %s\n' "$t" "$c"
  if [[ "$t" == "restaurants" ]]; then
    restaurants_count="$c"
  fi
done
echo

# ─── 4. Verdict ──────────────────────────────────────────────────────────────
if [[ "$restaurants_count" == "ERR" || -z "$restaurants_count" || "$restaurants_count" -eq 0 ]]; then
  echo "RESULT: FAIL — 'restaurants' table is empty or unreadable (count=${restaurants_count}); backup is suspect." >&2
  exit 2
fi

echo "RESULT: PASS — backup restored cleanly; restaurants=${restaurants_count}."
echo "(Reminder: confirm merge_restaurants_atomic + extensions were dumped — see KNOWN LIMITATION at top.)"
