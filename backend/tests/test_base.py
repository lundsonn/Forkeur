import pytest
from scrapers.base import check_cloudflare, CloudflareBlockedError, parse_menu_price


def test_check_cloudflare_raises_on_challenge():
    with pytest.raises(CloudflareBlockedError):
        check_cloudflare("Just a moment...")


def test_check_cloudflare_passes_on_normal_title():
    check_cloudflare("Uber Eats Belgium")  # should not raise


# ── parse_menu_price ──────────────────────────────────────────────────────


def test_parse_menu_price_non_zero_ending_00_regression():
    # BUG: "0,00" substring matched inside "€10,00" → collapsed to 0.0
    assert parse_menu_price("€10,00") == 10.0
    assert parse_menu_price("€20,00") == 20.0
    assert parse_menu_price("€100,00") == 100.0


def test_parse_menu_price_true_zero():
    assert parse_menu_price("€0,00") == 0.0


def test_parse_menu_price_free_words():
    assert parse_menu_price("Gratis") == 0.0
    assert parse_menu_price("Gratuit") == 0.0
    assert parse_menu_price("Free") == 0.0


def test_parse_menu_price_free_word_not_inside_other_word():
    # "free" must not match inside "freekick" / "freshly" etc.; price still wins
    assert parse_menu_price("Freekick €12,00") == 12.0


def test_parse_menu_price_vanaf_prefix():
    assert parse_menu_price("vanaf €12,50") == 12.5


def test_parse_menu_price_range_takes_low():
    assert parse_menu_price("€10,00 - €14,00") == 10.0


def test_parse_menu_price_cents_path_unchanged():
    assert parse_menu_price(1250, is_cents=True) == 12.5
