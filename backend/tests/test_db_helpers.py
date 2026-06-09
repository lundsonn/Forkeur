import db


def test_build_insert_simple():
    sql, params = db._build_insert("restaurants", {"name": "X", "slug": "x"})
    assert sql == 'INSERT INTO restaurants (name, slug) VALUES (%s, %s) RETURNING id'
    assert params == ["X", "x"]


def test_build_insert_on_conflict():
    sql, params = db._build_insert(
        "restaurants", {"name": "X", "slug": "x"}, on_conflict="slug"
    )
    assert "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name" in sql
    assert params == ["X", "x"]


def test_build_update():
    sql, params = db._build_update("restaurants", {"cuisine": "Pizza"}, "id", "abc")
    assert sql == 'UPDATE restaurants SET cuisine = %s WHERE id = %s'
    assert params == ["Pizza", "abc"]
