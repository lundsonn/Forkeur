import pytest
from scrapers.base import check_cloudflare, CloudflareBlockedError


def test_check_cloudflare_raises_on_challenge():
    with pytest.raises(CloudflareBlockedError):
        check_cloudflare("Just a moment...")


def test_check_cloudflare_passes_on_normal_title():
    check_cloudflare("Uber Eats Belgium")  # should not raise
