"""
CYPHER65 // Hashrate Market — Test Suite
=========================================
Tests for services/hashrate_market.py: all provider fetchers,
metrics/scoring, persistence, highlights, and edge cases.

Strategy:
  - Mock the low-level tool functions (get_braiins_orderbook, etc.)
    with controlled dicts so no real HTTP calls are made.
  - For KissMyHash / Parasite, monkeypatch requests.get and the tool
    function respectively.
  - Test compute_metrics + score_offer with known inputs and verify
    the math (BTC/day, cost, revenue, EV, risk level).
"""

import json
import time
import sqlite3
from unittest.mock import ANY, MagicMock, patch

import pytest

from services.hashrate_market import (
    NormalizedOffer,
    _safe_float,
    build_highlights,
    compute_metrics,
    enrich_opportunity_dict,
    fetch_all_offers,
    fetch_braiins_offer,
    fetch_kissmyhash_offer,
    fetch_market_history,
    fetch_mrr_offer,
    fetch_nicehash_offer,
    fetch_parasite_offer,
    persist_market_history,
    score_offer,
)


# ══════════════════════════════════════════════════════════════════════
#  Helper: build a mock tool function / data dict
# ══════════════════════════════════════════════════════════════════════

def _mock_tool(data: dict, raises: bool = False):
    """Return a callable that simulates a solo_mining_advisor tool.

    The real tool functions (get_braiins_orderbook, etc.) take NO arguments;
    they're called as ``get_braiins_orderbook()`` in the provider fetchers.
    Our mock must accept either:
      - Zero arguments  (``mock()`` — for service-code calls)
      - Two arguments   (``mock(name, params)`` — for opportunity_engine calls)
    This is handled via ``*args`` + ``**kwargs``.

    Parameters
    ----------
    data : dict
        Return value when the tool is called (e.g. {"price_btc_per_ph_day": ...}).
    raises : bool
        If True, the mock raises RuntimeError instead of returning data.
    """
    def _fn(*args, **kwargs):  # noqa: ARG001
        if raises:
            raise RuntimeError("API unreachable")
        return data
    return _fn


# ══════════════════════════════════════════════════════════════════════
#  _safe_float helper
# ══════════════════════════════════════════════════════════════════════

class TestSafeFloat:
    def test_none_returns_default(self):
        assert _safe_float(None, 42.0) == 42.0

    def test_string_number(self):
        assert _safe_float("123.45") == 123.45

    def test_int_returns_float(self):
        assert _safe_float(42) == 42.0

    def test_float_passthrough(self):
        assert _safe_float(3.14, 0.0) == 3.14

    def test_invalid_string_returns_default(self):
        assert _safe_float("not-a-number", -1.0) == -1.0

    def test_empty_string_returns_default(self):
        assert _safe_float("", 0.0) == 0.0

    def test_list_returns_default(self):
        assert _safe_float([1, 2, 3], 99.0) == 99.0

    def test_dict_returns_default(self):
        assert _safe_float({"a": 1}, 0.5) == 0.5

    def test_implicit_default_zero(self):
        assert _safe_float(None) == 0.0

    def test_negative_float_passthrough(self):
        assert _safe_float(-42.5) == -42.5


# ══════════════════════════════════════════════════════════════════════
#  NormalizedOffer
# ══════════════════════════════════════════════════════════════════════

class TestNormalizedOffer:
    def test_to_dict_includes_all_fields(self):
        o = NormalizedOffer(
            provider="braiins",
            hashrate=1000.0,
            price_per_th_day=0.0000005,
            duration_days=1.0,
            fee_pct=0.0,
            algorithm="sha256",
            meta={"source": "test"},
        )
        d = o.to_dict()
        assert d["provider"] == "braiins"
        assert d["hashrate"] == 1000.0
        assert d["price_per_th_day"] == 0.0000005
        assert d["duration_days"] == 1.0
        assert d["fee_pct"] == 0.0
        assert d["algorithm"] == "sha256"
        assert d["meta"] == {"source": "test"}

    def test_default_meta_is_empty_dict(self):
        o = NormalizedOffer(
            provider="test", hashrate=500.0, price_per_th_day=1e-6,
            duration_days=1.0, fee_pct=0.0, algorithm="sha256",
        )
        assert o.meta == {}


# ══════════════════════════════════════════════════════════════════════
#  fetch_braiins_offer
# ══════════════════════════════════════════════════════════════════════

class TestFetchBraiinsOffer:
    """Uses monkeypatch to replace agents.solo_mining_advisor.tools.get_braiins_orderbook."""

    def _mock(self, data: dict, monkeypatch, raises=False):
        monkeypatch.setattr(
            "services.hashrate_market.get_braiins_orderbook",
            _mock_tool(data, raises=raises),
        )

    def test_success_returns_offer(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.000500}, monkeypatch)
        offer = fetch_braiins_offer()
        assert offer is not None
        assert offer.provider == "braiins"
        assert offer.price_per_th_day == pytest.approx(5e-10)  # 0.000500 / 1_000_000
        assert offer.hashrate == 1000.0  # DEFAULT_RENTAL_HASHRATE_TH
        assert offer.algorithm == "sha256"

    def test_none_data_returns_none(self, monkeypatch):
        self._mock(None, monkeypatch)
        assert fetch_braiins_offer() is None

    def test_error_key_returns_none(self, monkeypatch):
        self._mock({"error": "no data"}, monkeypatch)
        assert fetch_braiins_offer() is None

    def test_zero_price_returns_none(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.0}, monkeypatch)
        assert fetch_braiins_offer() is None

    def test_negative_price_returns_none(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": -0.001}, monkeypatch)
        assert fetch_braiins_offer() is None

    def test_tool_raises_returns_none(self, monkeypatch):
        self._mock({}, monkeypatch, raises=True)
        # fetch_braiins_offer doesn't catch the exception; fetch_all_offers does
        with pytest.raises(RuntimeError):
            fetch_braiins_offer()

    def test_missing_price_key_returns_none(self, monkeypatch):
        self._mock({"available_asks": 5}, monkeypatch)
        # data is truthy and no error key, but 'price_btc_per_ph_day' not in data
        assert fetch_braiins_offer() is None

    def test_success_sets_meta_fields(self, monkeypatch):
        self._mock({
            "price_btc_per_ph_day": 0.000123,
            "available_asks": 10,
            "available_bids": 3,
            "price_unit": "BTC",
            "price_raw": "0.000123456",
        }, monkeypatch)
        offer = fetch_braiins_offer()
        assert offer is not None
        assert offer.meta["available_asks"] == 10
        assert offer.meta["available_bids"] == 3
        assert offer.meta["price_unit"] == "BTC"
        assert offer.meta["source"] == "hashpower.braiins.com"


# ══════════════════════════════════════════════════════════════════════
#  fetch_mrr_offer
# ══════════════════════════════════════════════════════════════════════

class TestFetchMrtOffer:
    def _mock(self, data: dict, monkeypatch, raises=False):
        monkeypatch.setattr(
            "services.hashrate_market.get_mrr_listings",
            _mock_tool(data, raises=raises),
        )

    def test_success_returns_offer(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.000400, "best_rig_hash_th": "2000"}, monkeypatch)
        offer = fetch_mrr_offer()
        assert offer is not None
        assert offer.provider == "mrr"
        assert offer.price_per_th_day == pytest.approx(4e-10)
        assert offer.hashrate == 2000.0

    def test_none_data_returns_none(self, monkeypatch):
        self._mock(None, monkeypatch)
        assert fetch_mrr_offer() is None

    def test_error_key_returns_none(self, monkeypatch):
        self._mock({"error": "auth failed"}, monkeypatch)
        assert fetch_mrr_offer() is None

    def test_needs_auth_returns_none(self, monkeypatch):
        self._mock({"needs_auth": True}, monkeypatch)
        assert fetch_mrr_offer() is None

    def test_zero_price_returns_none(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.0, "best_rig_hash_th": 1000}, monkeypatch)
        assert fetch_mrr_offer() is None

    def test_uses_default_hashrate_when_missing(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.000300}, monkeypatch)
        offer = fetch_mrr_offer()
        assert offer is not None
        assert offer.hashrate == 1000.0  # DEFAULT_RENTAL_HASHRATE_TH
        assert offer.price_per_th_day == pytest.approx(3e-10)

    def test_zero_hashrate_uses_default(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.000300, "best_rig_hash_th": 0}, monkeypatch)
        offer = fetch_mrr_offer()
        assert offer is not None
        assert offer.hashrate == 1000.0  # fallback to default

    def test_sets_meta_fields(self, monkeypatch):
        self._mock({
            "price_btc_per_ph_day": 0.000200,
            "best_rig_name": "Antminer S21",
            "total_listings": 15,
        }, monkeypatch)
        offer = fetch_mrr_offer()
        assert offer.meta["rig_name"] == "Antminer S21"
        assert offer.meta["total_listings"] == 15
        assert offer.meta["source"] == "miningrigrentals.com"


# ══════════════════════════════════════════════════════════════════════
#  fetch_nicehash_offer
# ══════════════════════════════════════════════════════════════════════

class TestFetchNicehashOffer:
    def _mock(self, data: dict, monkeypatch, raises=False):
        monkeypatch.setattr(
            "services.hashrate_market.get_nicehash_orderbook",
            _mock_tool(data, raises=raises),
        )

    def test_success_returns_offer(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.000600, "best_order_speed_ph": 0.5}, monkeypatch)
        offer = fetch_nicehash_offer()
        assert offer is not None
        assert offer.provider == "nicehash"
        assert offer.price_per_th_day == pytest.approx(6e-10)
        assert offer.hashrate == 500.0  # 0.5 PH/s * 1000

    def test_none_data_returns_none(self, monkeypatch):
        self._mock(None, monkeypatch)
        assert fetch_nicehash_offer() is None

    def test_error_key_returns_none(self, monkeypatch):
        self._mock({"error": "rate limited"}, monkeypatch)
        assert fetch_nicehash_offer() is None

    def test_zero_price_returns_none(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.0}, monkeypatch)
        assert fetch_nicehash_offer() is None

    def test_default_hashrate_when_speed_missing(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.000500}, monkeypatch)
        offer = fetch_nicehash_offer()
        assert offer is not None
        assert offer.hashrate == 1000.0  # default

    def test_zero_speed_uses_default(self, monkeypatch):
        self._mock({"price_btc_per_ph_day": 0.000500, "best_order_speed_ph": 0}, monkeypatch)
        offer = fetch_nicehash_offer()
        assert offer.hashrate == 1000.0

    def test_sets_meta_fields(self, monkeypatch):
        self._mock({
            "price_btc_per_ph_day": 0.000500,
            "available_orders": 25,
            "algorithm": "SHA256",
            "market": "hashpower",
        }, monkeypatch)
        offer = fetch_nicehash_offer()
        assert offer.meta["available_orders"] == 25
        assert offer.meta["algorithm"] == "SHA256"
        assert offer.meta["market"] == "hashpower"
        assert offer.meta["source"] == "api2.nicehash.com"


# ══════════════════════════════════════════════════════════════════════
#  fetch_kissmyhash_offer
# ══════════════════════════════════════════════════════════════════════

class TestFetchKissmyhashOffer:
    def test_success_via_api(self, monkeypatch):
        """API returns valid price → returns KissMyHash offer."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"price_btc_per_ph_day": 0.000700}
        monkeypatch.setattr("requests.get", MagicMock(return_value=mock_resp))
        offer = fetch_kissmyhash_offer()
        assert offer is not None
        assert offer.provider == "kissmyhash"
        assert offer.price_per_th_day == pytest.approx(7e-10)

    def test_fallback_to_nicehash_when_api_fails(self, monkeypatch):
        """requests.get raises → falls back to NiceHash +10% markup."""
        monkeypatch.setattr("requests.get", MagicMock(side_effect=ConnectionError("timeout")))
        monkeypatch.setattr(
            "services.hashrate_market.get_nicehash_orderbook",
            lambda: {"price_btc_per_ph_day": 0.000500, "best_order_speed_ph": 1.0},
        )
        offer = fetch_kissmyhash_offer()
        assert offer is not None
        assert offer.provider == "kissmyhash"
        # NiceHash price = 0.000500 / 1e6 = 5e-10, markup * 1.10 = 5.5e-10
        assert offer.price_per_th_day == pytest.approx(5.5e-10)
        assert offer.meta["source"] == "derived_from_nicehash"
        assert offer.meta["markup_pct"] == 10.0

    def test_fallback_to_nicehash_when_api_returns_no_price(self, monkeypatch):
        """API returns OK but no price → falls back."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"status": "no_data"}
        monkeypatch.setattr("requests.get", MagicMock(return_value=mock_resp))
        monkeypatch.setattr(
            "services.hashrate_market.get_nicehash_orderbook",
            lambda: {"price_btc_per_ph_day": 0.000400, "best_order_speed_ph": 2.0},
        )
        offer = fetch_kissmyhash_offer()
        assert offer is not None
        assert offer.provider == "kissmyhash"
        assert offer.price_per_th_day == pytest.approx(4.4e-10)

    def test_nicehash_also_fails(self, monkeypatch):
        """Both API and NiceHash fallback fail → None."""
        monkeypatch.setattr("requests.get", MagicMock(side_effect=Exception("API down")))
        monkeypatch.setattr(
            "services.hashrate_market.get_nicehash_orderbook",
            lambda: None,
        )
        offer = fetch_kissmyhash_offer()
        assert offer is None

    def test_api_http_error_fallback(self, monkeypatch):
        """API returns !ok → falls back."""
        mock_resp = MagicMock()
        mock_resp.ok = False
        monkeypatch.setattr("requests.get", MagicMock(return_value=mock_resp))
        monkeypatch.setattr(
            "services.hashrate_market.get_nicehash_orderbook",
            lambda: {"price_btc_per_ph_day": 0.000300, "best_order_speed_ph": 1.0},
        )
        offer = fetch_kissmyhash_offer()
        assert offer is not None
        assert offer.price_per_th_day == pytest.approx(3.3e-10)

    def test_api_zero_price_ignored(self, monkeypatch):
        """API returns zero price → treated as no data → fallback."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"price_btc_per_ph_day": 0.0}
        monkeypatch.setattr("requests.get", MagicMock(return_value=mock_resp))
        monkeypatch.setattr(
            "services.hashrate_market.get_nicehash_orderbook",
            lambda: {"price_btc_per_ph_day": 0.000200, "best_order_speed_ph": 1.0},
        )
        offer = fetch_kissmyhash_offer()
        assert offer is not None  # fallback
        assert offer.price_per_th_day == pytest.approx(2.2e-10)


# ══════════════════════════════════════════════════════════════════════
#  fetch_parasite_offer
# ══════════════════════════════════════════════════════════════════════

class TestFetchParasiteOffer:
    def _mock_parasite(self, data: dict, monkeypatch):
        # fetch_parasite_offer imports get_parasite_pool_stats INSIDE the function
        # (not at module level), so we must patch the original module path.
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.get_parasite_pool_stats",
            lambda: data,
        )

    def test_success_returns_offer(self, monkeypatch):
        self._mock_parasite({
            "pool_hashrate": 6e20 * 0.01,  # 1% of network (~6 EH/s)
            "pool_workers": 1500,
            "pool_users": 750,
            "pool_highest_diff": "128.5T",
            "pool_status": "active",
        }, monkeypatch)
        offer = fetch_parasite_offer()
        assert offer is not None
        assert offer.provider == "parasite"
        assert offer.algorithm == "sha256"
        assert offer.fee_pct == 1.0
        assert 1e-8 <= offer.price_per_th_day < 1e-4  # realistic range (can be exactly 1e-8)
        assert offer.meta["pool_workers"] == 1500
        assert offer.meta["pool_users"] == 750
        assert offer.meta["label"] == "Parasite Pool (own hardware required)"

    def test_error_data_returns_none(self, monkeypatch):
        self._mock_parasite({"error": "API not available"}, monkeypatch)
        assert fetch_parasite_offer() is None

    def test_empty_status_returns_none(self, monkeypatch):
        self._mock_parasite({"pool_status": "empty"}, monkeypatch)
        assert fetch_parasite_offer() is None

    def test_zero_hashrate_returns_none(self, monkeypatch):
        self._mock_parasite({"pool_hashrate": 0, "pool_status": "active"}, monkeypatch)
        assert fetch_parasite_offer() is None

    def test_none_pool_stats_returns_none(self, monkeypatch):
        self._mock_parasite(None, monkeypatch)
        assert fetch_parasite_offer() is None

    def test_tool_exception_returns_none(self, monkeypatch):
        """Exception inside fetch_parasite_offer caught and returns None."""
        def _raise(*args):
            raise RuntimeError("pool stats crash")
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.get_parasite_pool_stats",
            _raise,
        )
        offer = fetch_parasite_offer()
        assert offer is None

    def test_meta_disclaimer_set(self, monkeypatch):
        self._mock_parasite({
            "pool_hashrate": 6e20 * 0.005,
            "pool_workers": 100,
            "pool_users": 50,
            "pool_status": "active",
        }, monkeypatch)
        offer = fetch_parasite_offer()
        assert offer is not None
        assert "disclaimer" in offer.meta
        assert "rental marketplace" in offer.meta["disclaimer"]


# ══════════════════════════════════════════════════════════════════════
#  fetch_all_offers — orchestration
# ══════════════════════════════════════════════════════════════════════

class TestFetchAllOffers:
    def test_returns_multiple_offers(self, monkeypatch):
        """All 5 providers return valid data → 5 offers."""
        # Braiins
        monkeypatch.setattr(
            "services.hashrate_market.get_braiins_orderbook",
            lambda: {"price_btc_per_ph_day": 0.000500},
        )
        # MRR
        monkeypatch.setattr(
            "services.hashrate_market.get_mrr_listings",
            lambda: {"price_btc_per_ph_day": 0.000400, "best_rig_hash_th": "1000"},
        )
        # NiceHash
        monkeypatch.setattr(
            "services.hashrate_market.get_nicehash_orderbook",
            lambda: {"price_btc_per_ph_day": 0.000600, "best_order_speed_ph": 1.0},
        )
        # KissMyHash — mock requests.get to return valid price
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"price_btc_per_ph_day": 0.000700}
        monkeypatch.setattr("requests.get", MagicMock(return_value=mock_resp))
        # Parasite
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.get_parasite_pool_stats",
            lambda: {
                "pool_hashrate": 6e20 * 0.01,
                "pool_workers": 100,
                "pool_status": "active",
            },
        )

        offers = fetch_all_offers()
        providers = {o.provider for o in offers}
        assert providers == {"braiins", "mrr", "nicehash", "kissmyhash", "parasite"}
        assert len(offers) == 5

    def test_isolates_failures(self, monkeypatch):
        """One provider fails → others still appear."""
        # Braiins fails (raises)
        monkeypatch.setattr(
            "services.hashrate_market.get_braiins_orderbook",
            lambda: (_ for _ in ()).throw(RuntimeError("Braiins down")),
        )
        # MRR succeeds
        monkeypatch.setattr(
            "services.hashrate_market.get_mrr_listings",
            lambda: {"price_btc_per_ph_day": 0.000400, "best_rig_hash_th": "1000"},
        )
        # NiceHash fails (returns None)
        monkeypatch.setattr(
            "services.hashrate_market.get_nicehash_orderbook",
            lambda: None,
        )
        # KissMyHash — API fails, NiceHash fallback also fails
        monkeypatch.setattr("requests.get", MagicMock(side_effect=Exception("timeout")))
        # Parasite fails
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.get_parasite_pool_stats",
            lambda: None,
        )

        offers = fetch_all_offers()
        assert len(offers) == 1
        assert offers[0].provider == "mrr"

    def test_all_fail_return_empty(self, monkeypatch):
        """All providers fail → empty list."""
        monkeypatch.setattr(
            "services.hashrate_market.get_braiins_orderbook",
            lambda: None,
        )
        monkeypatch.setattr(
            "services.hashrate_market.get_mrr_listings",
            lambda: {"error": "no auth"},
        )
        monkeypatch.setattr(
            "services.hashrate_market.get_nicehash_orderbook",
            lambda: None,
        )
        monkeypatch.setattr("requests.get", MagicMock(side_effect=Exception("down")))
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.get_parasite_pool_stats",
            lambda: None,
        )

        offers = fetch_all_offers()
        assert offers == []


# ══════════════════════════════════════════════════════════════════════
#  compute_metrics
# ══════════════════════════════════════════════════════════════════════

class TestComputeMetrics:
    """Verify the math behind compute_metrics with controlled inputs."""

    KNOWN_NET_HR = 6e20  # ~600 EH/s (DEFAULT_NETWORK_HASHRATE)

    def _offer(self, price_per_th_day=1e-9, hashrate=1000.0, duration=1.0, fee=0.0):
        return NormalizedOffer(
            provider="test",
            hashrate=hashrate,
            price_per_th_day=price_per_th_day,
            duration_days=duration,
            fee_pct=fee,
            algorithm="sha256",
        )

    def test_positive_ev_returns_low_risk(self):
        """Cheap hashrate → positive EV → LOW risk."""
        offer = self._offer(price_per_th_day=1e-10)  # extremely cheap
        m = compute_metrics(offer, self.KNOWN_NET_HR)
        assert m["risk_level"] == "LOW"
        assert m["expected_value_btc"] > 0
        assert m["score"] > 0

    def test_negative_ev_returns_high_risk(self):
        """Expensive hashrate → negative EV → HIGH risk.

        Revenue ≈ (1000×1e12 / 6e20) × 144 × 3.125 = 0.00075 BTC/day
        Break-even price = 0.00075 / 1000 = 7.5e-7 BTC/TH/day
        With price=1e-6 (> breakeven): cost > revenue → negative EV.
        """
        offer = self._offer(price_per_th_day=1e-6)
        m = compute_metrics(offer, self.KNOWN_NET_HR)
        assert m["risk_level"] == "HIGH", f"Expected HIGH, got {m['risk_level']}. EV={m['expected_value_btc']}, score={m['score']}"
        assert m["expected_value_btc"] < 0

    def test_neutral_ev_medium_risk(self):
        """Slightly positive EV → MEDIUM risk.

        Revenue = (1000×1e12 / 6e20) × 144 × 3.125 = 0.00075 BTC/day
        Cost = 1000 × price
        For ROI = 0.04 (4%): 1.04 × 1000 × price = 0.00075 → price = 7.21e-7
        ROI = 0.04 is below the 0.05 MEDIUM→LOW threshold.
        """
        offer = self._offer(price_per_th_day=7.21e-7)
        m = compute_metrics(offer, self.KNOWN_NET_HR)
        assert m["risk_level"] == "MEDIUM", f"Expected MEDIUM, got {m['risk_level']}. score={m['score']}, EV={m['expected_value_btc']}, roi≈{m['score']/100}"

    def test_estimated_cost_includes_fee(self):
        """Fee percentage is included in cost calculation."""
        # Without fee: cost = hashrate * price_per_th_day
        # With 10% fee: cost = hashrate * price_per_th_day * 1.10
        offer = self._offer(price_per_th_day=1e-9, fee=10.0)
        m = compute_metrics(offer, self.KNOWN_NET_HR)
        expected_cost = 1000.0 * 1e-9 * 1.0 * 1.10
        assert m["estimated_cost_btc"] == pytest.approx(expected_cost)

    def test_revenue_scales_with_hashrate(self):
        """2x hashrate → 2x revenue."""
        off1 = self._offer(hashrate=1000.0)
        off2 = self._offer(hashrate=2000.0)
        m1 = compute_metrics(off1, self.KNOWN_NET_HR)
        m2 = compute_metrics(off2, self.KNOWN_NET_HR)
        assert m2["estimated_revenue_btc"] == pytest.approx(m1["estimated_revenue_btc"] * 2.0)

    def test_longer_duration_increases_cost_and_revenue(self):
        """Duration > 1 → both cost and revenue scale linearly."""
        offer = self._offer(price_per_th_day=1e-9, duration=7.0)
        m = compute_metrics(offer, self.KNOWN_NET_HR)
        # Cost = hashrate * price_per_th_day * duration * (1+fee)
        assert m["estimated_cost_btc"] == pytest.approx(1000.0 * 1e-9 * 7.0)
        # Revenue = daily_revenue * duration
        daily_rev = (1000e12 / self.KNOWN_NET_HR) * 144 * 3.125
        assert m["estimated_revenue_btc"] == pytest.approx(daily_rev * 7.0)

    def test_network_hashrate_zero_fallsback_to_default(self):
        """network_hashrate=0 → uses DEFAULT_NETWORK_HASHRATE."""
        offer = self._offer()
        m = compute_metrics(offer, network_hashrate=0)
        assert m["network_hashrate"] == 6e20

    def test_network_hashrate_none_fallsback_to_default(self):
        """network_hashrate=None → uses DEFAULT_NETWORK_HASHRATE."""
        offer = self._offer()
        m = compute_metrics(offer, network_hashrate=None)
        assert m["network_hashrate"] == 6e20

    def test_all_output_keys_present(self):
        """compute_metrics returns all expected keys."""
        m = compute_metrics(self._offer(), self.KNOWN_NET_HR)
        expected_keys = {
            "score", "estimated_cost_btc", "estimated_revenue_btc",
            "expected_value_btc", "risk_level", "network_hashrate", "duration_days",
        }
        assert set(m.keys()) == expected_keys

    def test_roi_rounding(self):
        """Score is roi * 100 rounded to 2 decimals."""
        offer = self._offer(price_per_th_day=5e-10)
        m = compute_metrics(offer, self.KNOWN_NET_HR)
        assert isinstance(m["score"], float)
        # score should have at most 2 decimal places
        score_str = str(m["score"])
        if "." in score_str:
            decimals = len(score_str.split(".")[1])
            assert decimals <= 2


# ══════════════════════════════════════════════════════════════════════
#  score_offer wrapper
# ══════════════════════════════════════════════════════════════════════

class TestScoreOffer:
    def test_returns_offer_and_metrics(self):
        o = NormalizedOffer(
            provider="nicehash", hashrate=500.0,
            price_per_th_day=2e-9, duration_days=1.0,
            fee_pct=0.0, algorithm="sha256",
        )
        s = score_offer(o, network_hashrate=6e20)
        # price_per_th_day=2e-9 → f"{2e-9:.6f}" → "0.000000" (rounded to 6 decimal places)
        assert s["id"] == "nicehash_0.000000"
        assert s["provider"] == "nicehash"
        assert s["hashrate"] == 500.0
        assert "metrics" in s
        assert s["metrics"]["risk_level"] in ("LOW", "MEDIUM", "HIGH")


# ══════════════════════════════════════════════════════════════════════
#  enrich_opportunity_dict
# ══════════════════════════════════════════════════════════════════════

class TestEnrichOpportunityDict:
    def test_attaches_metrics(self):
        opp = {"platform": "braiins", "price": 0.000500}
        result = enrich_opportunity_dict(opp, network_hashrate=6e20)
        assert "metrics" in result
        assert result["metrics"]["score"] >= -9999  # sanity

    def test_metrics_for_negative_price(self):
        """Price <= 0 → _empty_metrics."""
        opp = {"platform": "braiins", "price": -0.001}
        result = enrich_opportunity_dict(opp, network_hashrate=6e20)
        assert result["metrics"]["score"] == 0.0
        assert result["metrics"]["risk_level"] == "UNKNOWN"

    def test_metrics_for_missing_price(self):
        opp = {"platform": "mrr"}
        result = enrich_opportunity_dict(opp, network_hashrate=6e20)
        assert result["metrics"]["risk_level"] == "UNKNOWN"

    def test_inherits_network_from_snapshot(self):
        """network_hashrate=None but snapshot has network.hashrate."""
        opp = {"platform": "braiins", "price": 0.000200}
        snap = {"network": {"hashrate": 5.5e20}}
        result = enrich_opportunity_dict(opp, snapshot=snap, network_hashrate=None)
        assert result["metrics"]["network_hashrate"] == 5.5e20

    def test_empty_metrics_for_zero_price(self):
        opp = {"platform": "mrr", "price": 0}
        result = enrich_opportunity_dict(opp, network_hashrate=6e20)
        assert result["metrics"]["risk_level"] == "UNKNOWN"


# ══════════════════════════════════════════════════════════════════════
#  build_highlights
# ══════════════════════════════════════════════════════════════════════

class TestBuildHighlights:
    def test_empty_when_no_prices(self):
        highlights = build_highlights(snapshot=None, last_known_prices=None)
        assert highlights == []

    def test_empty_when_prices_none(self):
        highlights = build_highlights(
            snapshot=None,
            last_known_prices={"braiins": None, "mrr": None},
        )
        assert highlights == []

    def test_returns_offers_from_cache(self):
        prices = {
            "braiins": {"price": 0.000500, "ts": int(time.time()), "label": "Braiins"},
            "mrr": {"price": 0.000400, "ts": int(time.time()), "label": "MRR"},
        }
        highlights = build_highlights(
            snapshot={"network": {"hashrate": 6e20}},
            last_known_prices=prices,
            max_items=5,
        )
        assert len(highlights) == 2
        providers = {h["provider"] for h in highlights}
        assert providers == {"braiins", "mrr"}
        # Sorted by score descending
        assert highlights[0]["metrics"]["score"] >= highlights[1]["metrics"]["score"]

    def test_stale_prices_filtered(self):
        """Prices older than 2x max_age_seconds are excluded entirely."""
        too_old_ts = int(time.time()) - 700  # > 2 * 300s grace
        prices = {
            "braiins": {"price": 0.000500, "ts": too_old_ts, "label": "Braiins"},
        }
        highlights = build_highlights(
            snapshot=None,
            last_known_prices=prices,
            max_items=5,
            max_age_seconds=300,  # 5 min max
        )
        assert highlights == []

    def test_stale_within_grace_included_with_flag(self):
        """Data within 1x-2x max_age is kept but flagged as _stale (SWR)."""
        stale_ts = int(time.time()) - 400  # within 2x grace (600s)
        prices = {
            "braiins": {"price": 0.000500, "ts": stale_ts, "label": "Braiins"},
        }
        highlights = build_highlights(
            snapshot=None,
            last_known_prices=prices,
            max_items=5,
            max_age_seconds=300,
        )
        assert len(highlights) == 1
        assert highlights[0]["meta"]["_stale"] is True
        assert highlights[0]["meta"]["_age_s"] > 300

    def test_fresh_prices_included(self):
        """Prices within max_age_seconds are included."""
        fresh_ts = int(time.time()) - 60  # 1 min ago
        prices = {
            "braiins": {"price": 0.000500, "ts": fresh_ts, "label": "Braiins"},
        }
        highlights = build_highlights(
            snapshot=None,
            last_known_prices=prices,
            max_items=5,
            max_age_seconds=300,
        )
        assert len(highlights) == 1

    def test_zero_price_filtered(self):
        prices = {
            "braiins": {"price": 0.0, "ts": int(time.time()), "label": "Braiins"},
        }
        highlights = build_highlights(snapshot=None, last_known_prices=prices)
        assert highlights == []

    def test_respects_max_items(self):
        prices = {
            "a": {"price": 0.000500, "ts": int(time.time()), "label": "A"},
            "b": {"price": 0.000400, "ts": int(time.time()), "label": "B"},
            "c": {"price": 0.000300, "ts": int(time.time()), "label": "C"},
        }
        highlights = build_highlights(
            snapshot=None,
            last_known_prices=prices,
            max_items=2,
        )
        assert len(highlights) == 2

    def test_zero_max_age_ignores_cache_expiry(self):
        """max_age_seconds=0 → no age filtering."""
        old_ts = int(time.time()) - 99999
        prices = {
            "braiins": {"price": 0.000500, "ts": old_ts, "label": "Old"},
        }
        highlights = build_highlights(
            snapshot=None,
            last_known_prices=prices,
            max_age_seconds=0,
        )
        assert len(highlights) == 1

    def test_inherits_network_from_snapshot(self):
        prices = {
            "braiins": {"price": 0.000500, "ts": int(time.time()), "label": "B"},
        }
        highlights = build_highlights(
            snapshot={"network": {"hashrate": 5e20}},
            last_known_prices=prices,
        )
        assert highlights[0]["metrics"]["network_hashrate"] == 5e20


# ══════════════════════════════════════════════════════════════════════
#  Persistence
# ══════════════════════════════════════════════════════════════════════

class TestPersistence:
    @pytest.fixture
    def conn(self):
        """In-memory SQLite with the required schema."""
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("""
            CREATE TABLE IF NOT EXISTS hashrate_market_history (
                ts INTEGER, provider TEXT, hashrate REAL,
                price_per_th_day REAL, duration_days REAL, fee_pct REAL,
                algorithm TEXT, score REAL, raw_data TEXT
            )
        """)
        yield c
        c.close()

    def _offer(self, provider="braiins", price=5e-10):
        return NormalizedOffer(
            provider=provider, hashrate=1000.0,
            price_per_th_day=price, duration_days=1.0,
            fee_pct=0.0, algorithm="sha256",
        )

    def test_persist_empty_offers_does_nothing(self, conn):
        persist_market_history(conn, [])
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM hashrate_market_history")
        assert c.fetchone()["cnt"] == 0

    def test_persist_single_offer(self, conn):
        persist_market_history(conn, [self._offer()])
        c = conn.cursor()
        c.execute("SELECT * FROM hashrate_market_history")
        row = c.fetchone()
        assert row["provider"] == "braiins"
        assert row["hashrate"] == 1000.0
        assert row["score"] is not None

    def test_persist_multiple_offers(self, conn):
        offers = [
            self._offer("braiins", 5e-10),
            self._offer("mrr", 3e-10),
            self._offer("nicehash", 4e-10),
        ]
        persist_market_history(conn, offers)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM hashrate_market_history")
        assert c.fetchone()["cnt"] == 3

    def test_raw_data_is_json(self, conn):
        persist_market_history(conn, [self._offer()])
        c = conn.cursor()
        c.execute("SELECT raw_data FROM hashrate_market_history")
        raw = c.fetchone()["raw_data"]
        parsed = json.loads(raw)
        assert parsed["provider"] == "braiins"

    def test_fetch_market_history_returns_recent_first(self, conn):
        persist_market_history(conn, [
            self._offer("mrr", 3e-10),
        ])
        # Manually add an older row with a different TS
        c = conn.cursor()
        old_ts = 1000
        c.execute(
            "INSERT INTO hashrate_market_history "
            "(ts, provider, hashrate, price_per_th_day, duration_days, fee_pct, algorithm, score, raw_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (old_ts, "braiins", 1000.0, 5e-10, 1.0, 0.0, "sha256", 10.0, "{}"),
        )
        conn.commit()

        rows = fetch_market_history(conn, limit=10)
        # Should be ordered ts DESC, so the newest (mrr) comes first
        assert len(rows) == 2
        assert rows[0]["provider"] != "braiins" or rows[0]["ts"] > rows[1]["ts"]

    def test_fetch_respects_limit(self, conn):
        offers = [self._offer(f"p{i}", 1e-9) for i in range(5)]
        persist_market_history(conn, offers)
        rows = fetch_market_history(conn, limit=3)
        assert len(rows) == 3

    def test_fetch_has_all_keys(self, conn):
        persist_market_history(conn, [self._offer()])
        row = fetch_market_history(conn, limit=1)[0]
        expected = {"ts", "provider", "hashrate", "price_per_th_day",
                    "duration_days", "fee_pct", "algorithm", "score", "raw_data"}
        assert set(row.keys()) == expected
