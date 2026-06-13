"""Unit tests for the pure pending_migrations() helper — no DB required."""
from ops.migrate import pending_migrations


def test_all_pending():
    files = ["001_a.sql", "002_b.sql", "003_c.sql"]
    assert pending_migrations(files, set()) == files


def test_none_pending():
    files = ["001_a.sql", "002_b.sql"]
    applied = {"001_a.sql", "002_b.sql"}
    assert pending_migrations(files, applied) == []


def test_partial_pending():
    files = ["001_a.sql", "002_b.sql", "003_c.sql"]
    applied = {"001_a.sql"}
    assert pending_migrations(files, applied) == ["002_b.sql", "003_c.sql"]


def test_result_is_sorted_regardless_of_input_order():
    files = ["003_c.sql", "001_a.sql", "002_b.sql"]
    assert pending_migrations(files, set()) == [
        "001_a.sql",
        "002_b.sql",
        "003_c.sql",
    ]


def test_duplicate_numeric_prefixes_sort_lexically():
    files = ["008_last_scraped_at.sql", "008_restaurant_website.sql", "009_x.sql"]
    assert pending_migrations(files, {"009_x.sql"}) == [
        "008_last_scraped_at.sql",
        "008_restaurant_website.sql",
    ]


def test_applied_not_in_files_is_ignored():
    # An applied version no longer present as a file must not appear as pending.
    files = ["001_a.sql"]
    applied = {"001_a.sql", "999_ghost.sql"}
    assert pending_migrations(files, applied) == []
