"""Tests for _validate_order_url SSRF protection in db.py."""
import pytest
from db import _validate_order_url


# ---------------------------------------------------------------------------
# _validate_order_url  (SSRF protection)
# ---------------------------------------------------------------------------

def test_validate_accepts_normal_https():
    _validate_order_url("https://myrestaurant.be/order")  # no exception


def test_validate_accepts_http():
    _validate_order_url("http://myrestaurant.be/order")


def test_validate_rejects_localhost():
    with pytest.raises(ValueError):
        _validate_order_url("http://localhost:8080/order")


def test_validate_rejects_127():
    with pytest.raises(ValueError):
        _validate_order_url("http://127.0.0.1/order")


def test_validate_rejects_private_192():
    with pytest.raises(ValueError):
        _validate_order_url("http://192.168.1.1/order")


def test_validate_rejects_private_10():
    with pytest.raises(ValueError):
        _validate_order_url("http://10.0.0.1/order")


def test_validate_rejects_ftp_scheme():
    with pytest.raises(ValueError, match="not allowed"):
        _validate_order_url("ftp://myrestaurant.be/order")


def test_validate_rejects_no_domain():
    with pytest.raises(ValueError, match="not allowed"):
        _validate_order_url("http://localhost/")


def test_validate_rejects_interactsh():
    with pytest.raises(ValueError):
        _validate_order_url("https://foo.interactsh.com/order")
