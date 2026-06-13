"""Standalone DDL migration runner for the self-hosted Postgres.

Run as the `postgres` SUPERUSER, connecting DIRECTLY to Postgres (:5433),
NOT through PgBouncer. The backend app role (`forkeur_app`) lacks CREATE
privilege, so DDL migrations must not run inside the app process.

DSN comes from env `MIGRATE_DATABASE_URL` (fallback `DATABASE_URL_SUPERUSER`).
The app `DATABASE_URL` (PgBouncer / app role) is never used here.

Usage:
    uv run python ops/migrate.py up           # apply pending migrations
    uv run python ops/migrate.py up --check    # list pending, exit 1 if any
    uv run python ops/migrate.py check         # same as `up --check`
    uv run python ops/migrate.py baseline      # record all files as applied (no SQL)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

# backend/ops/migrate.py -> parents[2] == repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"

_TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     text PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


def _resolve_dsn() -> str:
    """Return the superuser DSN, or exit(2) with guidance if unset."""
    dsn = os.environ.get("MIGRATE_DATABASE_URL") or os.environ.get(
        "DATABASE_URL_SUPERUSER"
    )
    if not dsn:
        print(
            "Set MIGRATE_DATABASE_URL to a postgres-superuser DSN pointing at "
            "Postgres directly (e.g. "
            "postgresql://postgres:PW@127.0.0.1:5433/forkeur)",
            file=sys.stderr,
        )
        sys.exit(2)
    return dsn


def list_migration_files(migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Return sorted .sql filenames in the migrations dir."""
    if not migrations_dir.is_dir():
        print(f"Migrations dir not found: {migrations_dir}", file=sys.stderr)
        sys.exit(2)
    return sorted(p.name for p in migrations_dir.glob("*.sql"))


def pending_migrations(all_files: list[str], applied: set[str]) -> list[str]:
    """Pure helper: sorted migration filenames not yet applied.

    Kept dependency-free and importable for unit testing.
    """
    return sorted(f for f in all_files if f not in applied)


class TrackingTableMissing(Exception):
    """Raised when schema_migrations does not exist yet (baseline not run)."""


def compute_pending_via_pool(pgpool) -> list[str]:
    """Read-only pending check for backend startup, using the app pool.

    `pgpool` is the backend's pgpool module (exposes `fetchall`). The app role
    can SELECT but cannot run DDL — this NEVER applies anything. Raises
    TrackingTableMissing if the tracking table is absent (operator must run
    baseline). Importing this module does not execute any CLI/argparse code.
    """
    all_files = list_migration_files()
    try:
        rows = pgpool.fetchall("SELECT version FROM schema_migrations")
    except Exception as exc:  # noqa: BLE001
        # 42P01 = undefined_table. Detect via psycopg sqlstate if present.
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate == "42P01" or "schema_migrations" in str(exc):
            raise TrackingTableMissing(str(exc)) from exc
        raise
    applied = {r["version"] for r in rows}
    return pending_migrations(all_files, applied)


def _ensure_tracking_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(_TRACKING_TABLE_SQL)
    conn.commit()


def _applied_versions(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def cmd_up(conn: psycopg.Connection, check: bool) -> int:
    _ensure_tracking_table(conn)
    all_files = list_migration_files()
    applied = _applied_versions(conn)
    pending = pending_migrations(all_files, applied)

    if check:
        if pending:
            print("Pending migrations:")
            for f in pending:
                print(f"  {f}")
            return 1
        print("No pending migrations.")
        return 0

    if not pending:
        print("already up to date")
        return 0

    for filename in pending:
        path = MIGRATIONS_DIR / filename
        print(f"applying {filename} ...")
        sql = path.read_text()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (filename,),
                )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 — report and abort
            conn.rollback()
            print(f"FAILED on {filename}: {exc}", file=sys.stderr)
            return 1
        print(f"  ok {filename}")

    print(f"applied {len(pending)} migrations")
    return 0


def cmd_baseline(conn: psycopg.Connection) -> int:
    """Record every migration file as applied WITHOUT executing its SQL.

    For the existing live DB that already has 001..027 applied but no
    tracking table.
    """
    _ensure_tracking_table(conn)
    all_files = list_migration_files()
    recorded = 0
    with conn.cursor() as cur:
        for filename in all_files:
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s) "
                "ON CONFLICT (version) DO NOTHING",
                (filename,),
            )
            recorded += cur.rowcount
    conn.commit()
    print(f"baseline: recorded {recorded} migrations (of {len(all_files)} files)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DDL migration runner")
    sub = parser.add_subparsers(dest="command")

    p_up = sub.add_parser("up", help="apply pending migrations (default)")
    p_up.add_argument(
        "--check",
        action="store_true",
        help="list pending migrations and exit 1 if any; apply nothing",
    )
    sub.add_parser("check", help="alias for `up --check`")
    sub.add_parser("baseline", help="record all files as applied without running SQL")

    args = parser.parse_args(argv)
    command = args.command or "up"

    dsn = _resolve_dsn()
    print(f"migrations dir: {MIGRATIONS_DIR}")
    with psycopg.connect(dsn, autocommit=False) as conn:
        if command == "baseline":
            return cmd_baseline(conn)
        if command == "check":
            return cmd_up(conn, check=True)
        # command == "up"
        return cmd_up(conn, check=getattr(args, "check", False))


if __name__ == "__main__":
    sys.exit(main())
