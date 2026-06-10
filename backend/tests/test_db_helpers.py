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


def test_build_insert_composite_conflict_excludes_both():
    sql, params = db._build_insert(
        "platform_listings",
        {"restaurant_id": "r", "platform": "uber_eats", "url": "u"},
        on_conflict="restaurant_id,platform",
    )
    assert "ON CONFLICT (restaurant_id,platform) DO UPDATE SET url = EXCLUDED.url" in sql
    assert "restaurant_id = EXCLUDED" not in sql
    assert "platform = EXCLUDED" not in sql
