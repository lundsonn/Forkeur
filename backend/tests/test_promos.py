import pytest
from scrapers.promos import classify_promo, extract_min_order, parse_promo_texts


# ── extract_min_order ─────────────────────────────────────────────────────────

class TestExtractMinOrder:
    def test_en_over(self):
        assert extract_min_order("Free delivery on orders over €15") == 15.0

    def test_en_of_more(self):
        assert extract_min_order("on orders of €10 or more") == 10.0

    def test_fr_des(self):
        assert extract_min_order("dès €20") == 20.0

    def test_fr_a_partir_de(self):
        assert extract_min_order("à partir de 12€") == 12.0

    def test_nl_vanaf(self):
        assert extract_min_order("vanaf €25") == 25.0

    def test_de_ab(self):
        assert extract_min_order("ab €12 Bestellwert") == 12.0

    def test_en_spend(self):
        assert extract_min_order("spend €30") == 30.0

    def test_minimum_keyword(self):
        assert extract_min_order("minimum €18") == 18.0

    def test_no_match_returns_none(self):
        assert extract_min_order("Free delivery") is None

    def test_decimal_amount(self):
        assert extract_min_order("dès €12.50") == 12.5


# ── classify_promo ────────────────────────────────────────────────────────────

class TestClassifyPromo:
    def test_free_delivery_en(self):
        r = classify_promo("Free delivery on orders over €15")
        assert r["promo_type"] == "free_delivery"
        assert r["min_order"] == 15.0

    def test_free_delivery_fr(self):
        r = classify_promo("Livraison gratuite dès €20")
        assert r["promo_type"] == "free_delivery"

    def test_free_delivery_zero_euro(self):
        r = classify_promo("€0 delivery on orders over €10")
        assert r["promo_type"] == "free_delivery"

    def test_bogo_en(self):
        r = classify_promo("Buy 1 get 1 free")
        assert r["promo_type"] == "bogo"

    def test_bogo_fr(self):
        r = classify_promo("1 plat acheté = 1 offert")
        assert r["promo_type"] == "bogo"

    def test_bogo_2_for_1(self):
        r = classify_promo("2-for-1 on all burgers")
        assert r["promo_type"] == "bogo"

    def test_pct_discount(self):
        r = classify_promo("Get 20% off your order")
        assert r["promo_type"] == "pct_discount"
        assert r["value"] == 20.0

    def test_pct_discount_large(self):
        r = classify_promo("50% off first order")
        assert r["promo_type"] == "pct_discount"
        assert r["value"] == 50.0

    def test_abs_discount_save(self):
        r = classify_promo("Save €5 on your order")
        assert r["promo_type"] == "abs_discount"
        assert r["value"] == 5.0

    def test_free_item(self):
        r = classify_promo("Add a free item to your order")
        assert r["promo_type"] == "free_item"

    def test_free_item_fr(self):
        r = classify_promo("1 article offert dès €25")
        assert r["promo_type"] == "free_item"
        assert r["min_order"] == 25.0

    def test_spend_save(self):
        r = classify_promo("Spend €30 save €5")
        assert r["promo_type"] == "spend_save"

    def test_other_fallback(self):
        r = classify_promo("Loyalty points")
        assert r["promo_type"] == "other"
        assert r["value"] is None

    def test_label_preserved(self):
        text = "Free delivery on orders over €15"
        r = classify_promo(text)
        assert r["label"] == text


# ── parse_promo_texts ─────────────────────────────────────────────────────────

class TestParsePromoTexts:
    def test_returns_classified_list(self):
        results = parse_promo_texts(["Free delivery", "20% off"])
        assert len(results) == 2
        types = {r["promo_type"] for r in results}
        assert "free_delivery" in types
        assert "pct_discount" in types

    def test_deduplicates_case_insensitive(self):
        results = parse_promo_texts(["Free delivery", "FREE DELIVERY", "free delivery"])
        assert len(results) == 1

    def test_skips_empty_strings(self):
        results = parse_promo_texts(["", "  ", "Free delivery"])
        assert len(results) == 1

    def test_empty_input(self):
        assert parse_promo_texts([]) == []

    def test_whitespace_stripped(self):
        results = parse_promo_texts(["  Free delivery  "])
        assert results[0]["label"] == "Free delivery"
