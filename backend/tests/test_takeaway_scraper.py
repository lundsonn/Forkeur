from scrapers.takeaway import _parse_float, _parse_eta_min, _parse_eta_max


def test_parse_float_numeric():
    assert _parse_float("8.99") == 8.99


def test_parse_float_comma():
    assert _parse_float("8,99") == 8.99


def test_parse_float_with_currency():
    assert _parse_float("€ 12.50") == 12.50


def test_parse_float_none():
    assert _parse_float(None) is None


def test_parse_float_empty():
    assert _parse_float("") is None


def test_parse_eta_min_range():
    assert _parse_eta_min("30-45") == 30


def test_parse_eta_min_single():
    assert _parse_eta_min("20") == 20


def test_parse_eta_min_none():
    assert _parse_eta_min(None) is None


def test_parse_eta_max_range():
    assert _parse_eta_max("30-45") == 45


def test_parse_eta_max_no_dash():
    assert _parse_eta_max("20") is None


def test_parse_eta_max_none():
    assert _parse_eta_max(None) is None
