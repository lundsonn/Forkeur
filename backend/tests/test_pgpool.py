import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)


def test_fetchone_returns_dict():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    import pgpool
    pgpool.close_pool()  # reset any pool from a previous test
    row = pgpool.fetchone("select 1 as n, 'x' as s")
    assert row == {"n": 1, "s": "x"}


def test_fetchall_returns_list_of_dicts():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    import pgpool
    rows = pgpool.fetchall("select * from (values (1),(2)) as t(n) order by n")
    assert rows == [{"n": 1}, {"n": 2}]


def test_execute_returns_rowcount():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    import pgpool
    n = pgpool.execute("select 1")
    assert isinstance(n, int)
