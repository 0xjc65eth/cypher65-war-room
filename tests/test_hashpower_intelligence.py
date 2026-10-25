import copy

from services.hashrate_market import (
    NormalizedOffer,
    build_highlights,
    build_market_intelligence,
    market_rankings_view,
)


def offer(provider, price, hashrate, fetched_at):
    return NormalizedOffer(
        provider=provider,
        hashrate=hashrate,
        price_per_th_day=price,
        duration_days=1,
        fee_pct=0,
        algorithm="sha256",
        source="api:" + provider,
        meta={"fetched_at": fetched_at},
    )


def test_no_data_and_partial_provider_availability_are_distinct():
    no_data = build_market_intelligence([], {}, now=1000)
    assert no_data["status"] == "NO DATA"
    assert no_data["available_provider_count"] == 0
    assert no_data["total_provider_count"] == 3
    assert no_data["providers"]["mrr"]["freshness"] == "NO DATA"
    assert no_data["providers"]["mrr"]["cheapest"] is None
    assert no_data["rankings"] == {
        "cheapest": None,
        "best_score": None,
        "freshest": None,
        "most_capacity": None,
    }

    partial = build_market_intelligence(
        [offer("braiins", 1e-6, 10, 990)],
        {"braiins": {"ts": 995}, "mrr": {"ts": 980}},
        now=1000,
    )
    assert partial["status"] == "PARTIAL"
    assert partial["available_provider_count"] == 1
    assert partial["providers"]["braiins"] == {
        "status": "AVAILABLE",
        "freshness": "LIVE",
        "quote_age_seconds": 10,
        "cache_age_seconds": 5,
        "source": "api:braiins",
        "estimated": False,
        "cheapest": True,
        "best_score": True,
        "freshest": True,
        "most_capacity": True,
    }
    assert partial["providers"]["mrr"]["status"] == "UNAVAILABLE"
    assert partial["providers"]["mrr"]["cache_age_seconds"] == 20
    assert partial["cache_age_source"] == "mrr"
    assert partial["providers"]["mrr"]["cheapest"] is None
    assert partial["providers"]["nicehash"]["cheapest"] is None


def test_stale_cached_quote_is_not_reported_as_live():
    intelligence = build_market_intelligence(
        [offer("mrr", 2e-6, 20, 600)],
        {"mrr": {"ts": 800, "price": 2e-3, "source": "cache"}},
        now=1000,
        stale_after_seconds=120,
    )
    assert intelligence["status"] == "PARTIAL"
    assert intelligence["providers"]["mrr"]["freshness"] == "STALE"
    assert intelligence["providers"]["mrr"]["quote_age_seconds"] == 400
    assert intelligence["providers"]["mrr"]["cache_age_seconds"] == 200
    assert intelligence["rankings"]["freshest"] is None


def test_rankings_are_deterministic_and_independent():
    offers = [
        offer("braiins", 3e-6, 100, 990),
        offer("mrr", 1e-6, 30, 980),
        offer("nicehash", 2e-6, 500, 995),
    ]
    intelligence = build_market_intelligence(offers, {}, now=1000)
    assert intelligence["status"] == "AVAILABLE"
    assert intelligence["available_provider_count"] == 3
    assert intelligence["fresh_provider_count"] == 3
    assert intelligence["rankings"]["cheapest"] == "mrr"
    assert intelligence["rankings"]["best_score"] == "mrr"
    assert intelligence["rankings"]["freshest"] == "nicehash"
    assert intelligence["rankings"]["most_capacity"] == "nicehash"
    assert intelligence["providers"]["nicehash"]["freshest"] is True


def test_cache_timestamp_does_not_upgrade_undated_offer_to_live():
    intelligence = build_market_intelligence(
        [NormalizedOffer("braiins", 10, 1e-6, 1, 0, "sha256")],
        {"braiins": {"ts": 990}},
        now=1000,
    )
    provider = intelligence["providers"]["braiins"]
    assert provider["freshness"] == "UNKNOWN"
    assert provider["quote_age_seconds"] is None
    assert provider["cache_age_seconds"] == 10
    assert intelligence["fresh_provider_count"] == 0
    assert intelligence["cache_age_source"] == "braiins"


def test_invalid_and_estimated_offers_do_not_count_as_available():
    offers = [
        offer("braiins", float("nan"), 10, 990),
        NormalizedOffer("mrr", 10, 1e-6, 1, 0, "sha256", estimated=True),
    ]
    intelligence = build_market_intelligence(offers, {}, now=1000)
    assert intelligence["status"] == "NO DATA"
    assert intelligence["available_provider_count"] == 0
    assert intelligence["rankings"] == {
        "cheapest": None,
        "best_score": None,
        "freshest": None,
        "most_capacity": None,
    }


def test_market_intelligence_does_not_mutate_input_offers():
    source_offer = offer("mrr", 1e-6, 20, 990)
    before = copy.deepcopy(source_offer)
    build_market_intelligence([source_offer], {}, now=1000)
    assert source_offer == before


def test_cached_raw_offer_keeps_quote_age_separate_from_cache_age():
    cached_offer = offer("mrr", 1e-6, 20, 600)
    intelligence = build_market_intelligence(
        [],
        {"mrr": {"ts": 990, "value": cached_offer}},
        now=1000,
    )
    provider = intelligence["providers"]["mrr"]
    assert provider["freshness"] == "STALE"
    assert provider["quote_age_seconds"] == 400
    assert provider["cache_age_seconds"] == 10
    assert intelligence["rankings"]["freshest"] is None


def test_rankings_reject_nonfinite_and_invalid_inputs():
    result = market_rankings_view([
        {"provider": "broken", "price_per_th_day": float("nan"), "hashrate": 100},
        {"provider": "zero", "price_per_th_day": 1e-6, "hashrate": 0},
    ])
    assert result == {"cheapest": None, "best_score": None, "freshest": None, "most_capacity": None}


def test_highlights_reject_undated_future_and_nonfinite_cache_entries(monkeypatch):
    monkeypatch.setattr("services.hashrate_market.time.time", lambda: 1000)
    prices = {
        "undated": {"price": 1e-3},
        "future": {"price": 1e-3, "ts": 10**12},
        "invalid": {"price": float("inf"), "ts": 990},
        "valid": {"price": 1e-3, "ts": 990},
    }
    highlights = build_highlights(last_known_prices=prices, max_age_seconds=300)
    assert [item["provider"] for item in highlights] == ["valid"]


def test_stale_and_unknown_quote_age_do_not_claim_freshness():
    stale = offer("braiins", 1e-6, 10, 1)
    stale.meta["_stale"] = True
    intelligence = build_market_intelligence(
        [stale, NormalizedOffer("mrr", 10, 1e-6, 1, 0, "sha256")],
        {},
        now=1000,
    )
    assert intelligence["providers"]["braiins"]["freshness"] == "STALE"
    assert intelligence["providers"]["mrr"]["freshness"] == "UNKNOWN"
    assert intelligence["fresh_provider_count"] == 0
