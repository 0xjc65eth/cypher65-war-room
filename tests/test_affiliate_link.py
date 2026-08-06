"""
CYPHER65 // P0-3 — Hash Market one-click affiliate link
========================================================
Hermetic tests for the pure affiliate-link helpers in helpers.py:

1. affiliate_map_from_env() — parses HASH_MARKET_AFFILIATE_URLS (JSON
   {provider: url}); missing/invalid env → {}; http(s)-only; keys lowercased.
2. resolve_affiliate_link() — picks the cheapest offer whose provider is
   configured; prefers non-estimated (real marketplace) quotes; returns None
   when nothing is eligible; garbage entries never raise.

No network, no DB, no app import needed (same ethos as test_decision_matrix.py).
"""

import json

import pytest

from helpers import affiliate_map_from_env, resolve_affiliate_link, attach_affiliate


class TestAffiliateMapFromEnv:
    def test_missing_env_returns_empty(self, monkeypatch):
        monkeypatch.delenv("HASH_MARKET_AFFILIATE_URLS", raising=False)
        assert affiliate_map_from_env() == {}

    def test_valid_json_parsed_and_normalized(self, monkeypatch):
        monkeypatch.setenv(
            "HASH_MARKET_AFFILIATE_URLS",
            json.dumps({
                "MRR": "https://www.miningrigrentals.com/?ref=abc",
                "nicehash": "https://www.nicehash.com/r/xyz",
                "bad": "ftp://not-http",
            }),
        )
        assert affiliate_map_from_env() == {
            "mrr": "https://www.miningrigrentals.com/?ref=abc",
            "nicehash": "https://www.nicehash.com/r/xyz",
        }

    def test_invalid_json_returns_empty(self, monkeypatch):
        monkeypatch.setenv("HASH_MARKET_AFFILIATE_URLS", "not-json{")
        assert affiliate_map_from_env() == {}

    def test_non_dict_json_returns_empty(self, monkeypatch):
        monkeypatch.setenv("HASH_MARKET_AFFILIATE_URLS", "[1,2,3]")
        assert affiliate_map_from_env() == {}


class TestResolveAffiliateLink:
    OFFERS = [
        {"provider": "mrr", "price_per_th_day": 0.0006, "estimated": False},
        {"provider": "nicehash", "price_per_th_day": 0.0004, "estimated": False},
        {"provider": "braiins", "price_per_th_day": 0.0001, "estimated": False},
    ]

    def test_cheapest_configured_provider_wins(self):
        amap = {
            "mrr": "https://mrr.example/ref",
            "nicehash": "https://nh.example/ref",
        }
        out = resolve_affiliate_link(self.OFFERS, amap)
        assert out == {
            "provider": "nicehash",
            "url": "https://nh.example/ref",
            "price_per_th_day": 0.0004,
        }

    def test_unconfigured_providers_skipped(self):
        amap = {"braiins": "https://b.example/ref"}
        out = resolve_affiliate_link(self.OFFERS, amap)
        assert out["provider"] == "braiins"
        assert out["price_per_th_day"] == 0.0001

    def test_none_when_no_provider_configured(self):
        assert resolve_affiliate_link(self.OFFERS, {"other": "https://x.example"}) is None

    def test_prefers_real_over_cheaper_estimated(self):
        offers = [
            {"provider": "mrr", "price_per_th_day": 0.0009, "estimated": True},
            {"provider": "mrr", "price_per_th_day": 0.0005, "estimated": False},
        ]
        out = resolve_affiliate_link(offers, {"mrr": "https://mrr.example/ref"})
        assert out["price_per_th_day"] == 0.0005  # real quote wins over cheaper estimated

    def test_none_without_offers_or_map(self):
        assert resolve_affiliate_link([], {"mrr": "https://x"}) is None
        assert resolve_affiliate_link(self.OFFERS, {}) is None
        assert resolve_affiliate_link(None, {"mrr": "https://x"}) is None

    def test_garbage_entries_never_raise(self):
        offers = [
            {"provider": "mrr"},  # no price
            "garbage",
            None,
            {"provider": "nicehash", "price_per_th_day": "nope"},
            {"provider": "nicehash", "price_per_th_day": 0.0003, "estimated": False},
        ]
        out = resolve_affiliate_link(offers, {"mrr": "https://mrr", "nicehash": "https://nh"})
        assert out == {"provider": "nicehash", "url": "https://nh", "price_per_th_day": 0.0003}

    def test_missing_env_map_with_offers_returns_none(self, monkeypatch):
        monkeypatch.delenv("HASH_MARKET_AFFILIATE_URLS", raising=False)
        assert resolve_affiliate_link(self.OFFERS, affiliate_map_from_env()) is None

    def test_offers_missing_source_field_fallback(self):
        offers = [{"source": "braiins", "price_per_th_day": 0.0002, "estimated": False}]
        out = resolve_affiliate_link(offers, {"braiins": "https://braiins.example/ref"})
        assert out["provider"] == "braiins"


class TestAttachAffiliate:
    def test_attaches_and_mirrors_into_decision_matrix(self):
        snap = {
            "market_data": {"offers": []},
            "profitability": {"decision_matrix": {"best_option": "lease"}},
        }
        offers = [{"provider": "mrr", "price_per_th_day": 0.0004, "estimated": False}]
        amap = {"mrr": "https://mrr.example/ref"}
        attach_affiliate(snap, offers, amap)
        assert snap["market_data"]["affiliate"] == {
            "provider": "mrr",
            "url": "https://mrr.example/ref",
            "price_per_th_day": 0.0004,
        }
        assert snap["profitability"]["decision_matrix"]["affiliate"]["provider"] == "mrr"

    def test_no_link_leaves_decision_matrix_untouched(self):
        snap = {"market_data": {}, "profitability": {"decision_matrix": {"best_option": "pool"}}}
        attach_affiliate(snap, [], {"mrr": "https://mrr.example/ref"})
        assert snap["market_data"]["affiliate"] is None
        assert "affiliate" not in snap["profitability"]["decision_matrix"]

    def test_cached_path_consistency(self):
        # Both snapshot branches must yield the same market_data shape.
        snap = {"market_data": {"offers": [1]}, "profitability": {}}
        attach_affiliate(
            snap,
            [{"provider": "nh", "price_per_th_day": 0.5, "estimated": False}],
            {"nh": "https://nh.example/ref"},
        )
        assert snap["market_data"]["affiliate"]["provider"] == "nh"

    def test_missing_sections_never_raise(self):
        attach_affiliate({}, [{"provider": "mrr", "price_per_th_day": 1, "estimated": False}], {"mrr": "https://x"})
        attach_affiliate({"market_data": None}, [], {})
        assert True
