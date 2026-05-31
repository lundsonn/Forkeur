from models import ScraperConfig, ScraperResult, RunTriggerIn


def test_scraper_config_defaults():
    c = ScraperConfig()
    assert c.scrape_menus is False
    assert c.max_menus == 3


def test_scraper_config_custom():
    c = ScraperConfig(scrape_menus=True, max_menus=5)
    assert c.scrape_menus is True
    assert c.max_menus == 5


def test_scraper_result_defaults():
    r = ScraperResult(records_saved=2)
    assert r.menu_items_saved == 0


def test_run_trigger_in_defaults():
    body = RunTriggerIn()
    assert body.scrape_menus is False
    assert body.max_menus == 3
