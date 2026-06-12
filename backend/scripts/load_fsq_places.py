"""Load the Brussels slice of Foursquare OS Places into the `fsq_places` table.

FSQ OS Places is a free, Apache-2.0 POI dataset (100M+ places, monthly refresh).
We use it as a supplementary corroboration source for restaurant phones/websites,
matched by name+geo. The official feed moved to a token-gated portal; the
community Hugging Face mirror (do-me/foursquare_places_100M, a consolidated
single GeoParquet built from the FSQ release) is anonymous and queryable over
httpfs, so we pull the Brussels bbox directly without downloading 10 GB.

Idempotent: truncates and reloads. Run from backend/:
    uv run --with duckdb python scripts/load_fsq_places.py
"""
import os
import sys
from urllib.parse import urlparse

import duckdb

# do-me consolidated mirror; anonymous. Brussels bbox covers the 19 communes
# plus near periphery (Forkeur's delivery zones).
FSQ_PARQUET = (
    "https://huggingface.co/datasets/do-me/foursquare_places_100M/"
    "resolve/main/foursquare_places.parquet"
)
BBOX = dict(min_lat=50.76, max_lat=50.92, min_lng=4.24, max_lng=4.49)


def _pg_attach_string(database_url: str) -> str:
    u = urlparse(database_url)
    parts = [
        f"dbname={u.path.lstrip('/')}",
        f"user={u.username}",
        f"host={u.hostname or '127.0.0.1'}",
        f"port={u.port or 5432}",
    ]
    if u.password:
        parts.append(f"password={u.password}")
    return " ".join(parts)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL not set")

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL postgres; LOAD postgres;")
    con.execute("SET http_keep_alive=true; SET http_timeout=180000;")
    con.execute(f"ATTACH '{_pg_attach_string(database_url)}' AS pg (TYPE postgres)")

    print("Pulling Brussels slice from FSQ mirror (~60s)...")
    con.execute(
        f"""
        CREATE TEMP TABLE bxl AS
        SELECT fsq_place_id, name, latitude, longitude, tel, website, email,
               fsq_category_labels AS categories
        FROM read_parquet('{FSQ_PARQUET}')
        WHERE latitude  BETWEEN {BBOX['min_lat']} AND {BBOX['max_lat']}
          AND longitude BETWEEN {BBOX['min_lng']} AND {BBOX['max_lng']}
        """
    )
    n, tel = con.execute(
        "SELECT count(*), count(tel) FILTER (WHERE tel <> '') FROM bxl"
    ).fetchone()
    print(f"  {n} Brussels places, {tel} with phone")

    con.execute("TRUNCATE pg.fsq_places")
    con.execute(
        """
        INSERT INTO pg.fsq_places
            (fsq_place_id, name, latitude, longitude, tel, website, email, categories)
        SELECT fsq_place_id, name, latitude, longitude,
               nullif(tel, ''), nullif(website, ''), nullif(email, ''), categories
        FROM bxl
        """
    )
    loaded = con.execute("SELECT count(*) FROM pg.fsq_places").fetchone()[0]
    print(f"Loaded {loaded} rows into fsq_places")


if __name__ == "__main__":
    main()
