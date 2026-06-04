from unittest.mock import patch
import matching


def _r(name, **kw):
    base = {"id": kw.get("id", name), "name": name, "website": None, "phone": None,
            "lat": None, "lng": None, "geo_source": None, "cuisine": None,
            "created_at": "2026-01-01T00:00:00Z"}
    base.update(kw)
    return base


def test_match_job_dry_run_writes_nothing():
    from scrapers import match
    rows = [_r("Pizza Minute", id="1", website="https://pz.be"),
            _r("PizzaMinute", id="2", website="http://pz.be")]
    with patch("db.load_restaurants_for_match", return_value=rows), \
         patch("db.merge_restaurants") as merge, \
         patch("db.enqueue_decision") as enq:
        result = match.run_sync(dry_run=True, log_fn=lambda m: None)
    merge.assert_not_called()
    enq.assert_not_called()
    assert result["auto_merge"] >= 1


def test_match_job_executes_merges_when_not_dry_run():
    from scrapers import match
    rows = [_r("Pizza Minute", id="1", website="https://pz.be"),
            _r("PizzaMinute", id="2", website="http://pz.be")]
    with patch("db.load_restaurants_for_match", return_value=rows), \
         patch("db.merge_restaurants") as merge, \
         patch("db.enqueue_decision") as enq:
        match.run_sync(dry_run=False, log_fn=lambda m: None)
    assert merge.call_count == 1
    assert enq.call_count == 1


def test_match_job_enqueues_names_in_features():
    from scrapers import match
    rows = [_r("Pizza Minute", id="1", website="https://pz.be"),
            _r("PizzaMinute", id="2", website="http://pz.be")]
    with patch("db.load_restaurants_for_match", return_value=rows), \
         patch("db.merge_restaurants"), \
         patch("db.enqueue_decision") as enq:
        match.run_sync(dry_run=False, log_fn=lambda m: None)
    assert enq.call_count == 1
    feats = enq.call_args.kwargs["features"]
    assert "survivor_name" in feats and "loser_name" in feats
    assert {feats["survivor_name"], feats["loser_name"]} == {"Pizza Minute", "PizzaMinute"}
