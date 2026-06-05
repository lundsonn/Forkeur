import pytest
from scrapers.direct_classify import classify_url, _JUNK_RE


# ── classify_url ──────────────────────────────────────────────────────────────

def test_sq_menu_is_ordering():
    assert classify_url('https://www.sq-menu.com/api/fb/v4pnd') == 'ordering'

def test_piki_app_is_ordering():
    assert classify_url('https://piki-app.com/vendor/pizza/categories') == 'ordering'

def test_odoo_pos_self_is_ordering():
    assert classify_url('https://restaurant.odoo.com/pos-self/15') == 'ordering'

def test_odoo_non_pos_is_website():
    assert classify_url('https://restaurant.odoo.com/shop') == 'website'

def test_lightspeed_is_ordering():
    assert classify_url('https://order.lightspeedrestaurant.com/abc') == 'ordering'

def test_clickeat_is_ordering():
    assert classify_url('https://clickeat.be/restaurant/pizza') == 'ordering'

def test_menu_path_is_menu():
    assert classify_url('https://example.com/menu') == 'menu'

def test_carte_path_is_menu():
    assert classify_url('https://example.com/notre-carte') == 'menu'

def test_menukaart_path_is_menu():
    assert classify_url('https://example.com/menukaart') == 'menu'

def test_kaart_path_is_menu():
    assert classify_url('https://example.com/kaart/gerechten') == 'menu'

def test_plain_website_fallback():
    assert classify_url('https://myrestaurant.be') == 'website'

def test_none_with_phone_returns_phone():
    assert classify_url(None, phone='+32471234567') == 'phone'

def test_none_without_phone_returns_website():
    assert classify_url(None) == 'website'

def test_empty_string_with_phone_returns_phone():
    assert classify_url('', phone='+32471234567') == 'phone'

def test_ordering_takes_precedence_over_menu_path():
    assert classify_url('https://www.sq-menu.com/api/menu/v4pnd') == 'ordering'


# ── _JUNK_RE ──────────────────────────────────────────────────────────────────

def test_junk_google_searchviewer():
    assert _JUNK_RE.search('https://google.com/searchviewer?q=restaurant')

def test_junk_zenchef():
    assert _JUNK_RE.search('https://bookings.zenchef.com/results?rid=123')

def test_junk_tablebooker():
    assert _JUNK_RE.search('https://www.tablebooker.com/r/myrestaurant')

def test_junk_pdf():
    assert _JUNK_RE.search('https://myrestaurant.be/menu.pdf')

def test_junk_linktree():
    assert _JUNK_RE.search('https://linktr.ee/myrestaurant')

def test_junk_digilink():
    assert _JUNK_RE.search('https://digilink.io/myrestaurant')

def test_not_junk_sq_menu():
    assert not _JUNK_RE.search('https://burger.sq-menu.com/order')

def test_not_junk_normal_website():
    assert not _JUNK_RE.search('https://myrestaurant.be')
