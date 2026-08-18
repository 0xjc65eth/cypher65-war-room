"""
Unit tests for hashrate market parsers.
Tests both the raw API wrappers (tools.py) and the normalization layer (hashrate_market.py).
"""

import json
import time
from unittest.mock import patch, MagicMock, PropertyMock
import pytest

from services.hashrate_market import (
    NormalizedOffer,
    clear_fetch_cache,
    fetch_braiins_offer,
    fetch_nicehash_offer,
    fetch_mrr_offer,
    fetch_parasite_offer,
    fetch_all_offers,
    DEFAULT_RENTAL_HASHRATE_TH,
)


@pytest.fixture(autouse=True)
def _clear_fetch_cache():
    """Clear the module-level provider fetch cache between tests.

    fetch_all_offers() caches per-provider results for a TTL; without this,
    a test that patches providers to return None can receive offers cached by
    an earlier test in the same process.
    """
    clear_fetch_cache()
    yield
    clear_fetch_cache()


# ══════════════════════════════════════════════════════════════════════════
#  TOOLS LAYER — agents/solo_mining_advisor/tools.py
#  get_braiins_orderbook, get_mrr_listings, get_nicehash_orderbook
# ══════════════════════════════════════════════════════════════════════════


class TestGetBraiinsOrderbook:
    """Tests for get_braiins_orderbook() — Braiins Hashpower marketplace."""

    def _make_mock(self, monkeypatch, settings_data, orderbook_data):
        """Helper: mock requests.get to return settings then orderbook based on URL."""
        mock_settings = MagicMock()
        mock_settings.status_code = 200
        mock_settings.json.return_value = settings_data

        mock_orderbook = MagicMock()
        mock_orderbook.status_code = 200
        mock_orderbook.json.return_value = orderbook_data

        def _fake_get(url, **kw):
            if "settings" in url:
                return mock_settings
            return mock_orderbook

        monkeypatch.setattr("agents.solo_mining_advisor.tools.requests.get", _fake_get)

    def test_success_with_asks(self, monkeypatch):
        """When asks exist, return lowest ask price in BTC/PH/day."""
        # Issue #267: official settings field is `hr_unit` (not price_unit).
        settings = {"hr_unit": "PH/day"}
        orderbook = {
            "asks": [
                {"price_sat": "5000", "amount": "10.5"},
                {"price_sat": "5200", "amount": "5.0"},
            ],
            "bids": [
                {"price_sat": "4800", "amount": "2.0"},
            ],
        }
        self._make_mock(monkeypatch, settings, orderbook)
        from agents.solo_mining_advisor.tools import get_braiins_orderbook

        result = get_braiins_orderbook()
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result["price_btc_per_ph_day"] == pytest.approx(
            5000 / 100_000_000, rel=1e-6
        )
        assert result["available_asks"] == 2
        assert result["price_raw_unit"] == "PH/day"

    def test_success_with_bids_only(self, monkeypatch):
        """When only bids exist, use highest bid as best price."""
        settings = {"hr_unit": "PH/day"}
        orderbook = {
            "asks": [],
            "bids": [
                {"price_sat": "4900", "amount": "3.0"},
            ],
        }
        self._make_mock(monkeypatch, settings, orderbook)
        from agents.solo_mining_advisor.tools import get_braiins_orderbook

        result = get_braiins_orderbook()
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result["price_btc_per_ph_day"] == pytest.approx(
            4900 / 100_000_000, rel=1e-6
        )

    def test_empty_orderbook(self, monkeypatch):
        """Empty asks AND bids should return error."""
        settings = {"hr_unit": "PH/day"}
        orderbook = {"asks": [], "bids": []}
        self._make_mock(monkeypatch, settings, orderbook)
        from agents.solo_mining_advisor.tools import get_braiins_orderbook

        result = get_braiins_orderbook()
        assert "error" in result

    def test_http_error(self, monkeypatch):
        """Non-200 status should return error dict."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_braiins_orderbook

        result = get_braiins_orderbook()
        assert "error" in result

    def test_connection_error(self, monkeypatch):
        """Connection failure should return error dict."""

        def _raise(*a, **kw):
            raise Exception("Connection refused")

        monkeypatch.setattr("agents.solo_mining_advisor.tools.requests.get", _raise)
        from agents.solo_mining_advisor.tools import get_braiins_orderbook

        result = get_braiins_orderbook()
        assert "error" in result
        assert "unreachable" in result["error"].lower()

    def test_price_sat_is_zero(self, monkeypatch):
        """If best ask has zero price_sat, return error."""
        settings = {"hr_unit": "PH/day"}
        orderbook = {
            "asks": [
                {"price_sat": "0", "amount": "10.0"},
            ],
            "bids": [],
        }
        self._make_mock(monkeypatch, settings, orderbook)
        from agents.solo_mining_advisor.tools import get_braiins_orderbook

        result = get_braiins_orderbook()
        assert "error" in result


class TestGetMrrListings:
    """Tests for get_mrr_listings() — MiningRigRentals marketplace."""

    def test_needs_auth_when_no_keys(self, monkeypatch):
        """When no API key/secret are provided, return needs_auth dict."""
        monkeypatch.delenv("MRR_API_KEY", raising=False)
        monkeypatch.delenv("MRR_API_SECRET", raising=False)
        from agents.solo_mining_advisor.tools import get_mrr_listings

        result = get_mrr_listings(api_key="", api_secret="")
        assert result.get("needs_auth") is True

    def test_success_with_listings(self, monkeypatch):
        """When MRR API returns valid listings, return cheapest price.
        MRR structure: rig["hashrate"]["advertised"]["hash"] for TH/s,
                       rig["price"]["BTC"] for BTC pricing (has 'price' and 'hour' keys).
        """
        monkeypatch.setenv("MRR_API_KEY", "test-key")
        monkeypatch.setenv("MRR_API_SECRET", "test-secret")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "data": {
                "records": [
                    {
                        "hashrate": {"advertised": {"hash": "100.0"}},
                        "price": {"BTC": {"price": "0.00005", "hour": "0.00005"}},
                        "type": "sha256",
                    },
                    {
                        "hashrate": {"advertised": {"hash": "200.0"}},
                        "price": {"BTC": {"price": "0.00006", "hour": "0.00006"}},
                        "type": "sha256",
                    },
                ]
            },
        }
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_mrr_listings

        result = get_mrr_listings()
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "price_btc_per_ph_day" in result
        assert result["total_listings"] == 2

    def test_empty_records(self, monkeypatch):
        """No records should return error dict."""
        monkeypatch.setenv("MRR_API_KEY", "test-key")
        monkeypatch.setenv("MRR_API_SECRET", "test-secret")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "records": []}
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_mrr_listings

        result = get_mrr_listings()
        assert "error" in result

    def test_api_failure(self, monkeypatch):
        """API success=false should return error dict."""
        monkeypatch.setenv("MRR_API_KEY", "test-key")
        monkeypatch.setenv("MRR_API_SECRET", "test-secret")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": False, "message": "rate limit"}
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_mrr_listings

        result = get_mrr_listings()
        assert "error" in result


class TestGetNicehashOrderbook:
    """Tests for get_nicehash_orderbook() — NiceHash hashpower marketplace."""

    # Audit 18-Aug (Sev-1): the real API declares priceFactor=1e18 (EH) and
    # marketFactor=1e18 — `price` is BTC/EH/day, NOT BTC/TH/day. The old
    # mocks omitted the factors, which is exactly why the 1e6× unit bug
    # slipped through. These tests now use the REAL payload shape.
    REAL_FACTORS = {
        "priceFactor": "1000000000000000000.00000000",
        "marketFactor": "1000000000000000000.00000000",
        "displayPriceFactor": "EH",
        "displayMarketFactor": "EH",
    }

    def test_success_with_orders(self, monkeypatch):
        """When orders exist at stats.BTC.orders, return cheapest with correct
        priceFactor/marketFactor conversion (audit 18-Aug fix)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "stats": {
                "BTC": {
                    **self.REAL_FACTORS,
                    "orders": [
                        {
                            "alive": True,
                            "price": "0.68",
                            "acceptedSpeed": "0.0005",
                            "type": "STANDARD",
                        },
                        {
                            "alive": True,
                            "price": "0.70",
                            "acceptedSpeed": "0.0006",
                            "type": "STANDARD",
                        },
                        {
                            "alive": False,
                            "price": "0.30",
                            "acceptedSpeed": "0.0001",
                            "type": "STANDARD",
                        },
                    ],
                }
            }
        }
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_nicehash_orderbook

        result = get_nicehash_orderbook()
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        # price 0.68 BTC/EH/day ÷ priceFactor 1e18 × 1e12 = 6.8e-7 BTC/TH/day
        # (= 68 sats/TH/d — the real market price, ~fair value).
        # per-PH = per-TH × 1000 (1 PH = 1000 TH).
        assert result["price_btc_per_th_day"] == pytest.approx(6.8e-7, rel=1e-6)
        assert result["price_btc_per_ph_day"] == pytest.approx(6.8e-7 * 1000, rel=1e-6)
        # acceptedSpeed 0.0005 EH = 5e14 H/s = 500 TH/s = 0.5 PH/s
        assert result["best_order_speed_ph"] == pytest.approx(0.5, rel=1e-6)
        assert result["available_orders"] == 2

    def test_ghost_orders_ignored(self, monkeypatch):
        """Orders with acceptedSpeed=0 (no rigs matched) must NOT win as
        cheapest — they poisoned the panel with absurd ROI (audit 18-Aug)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "stats": {
                "BTC": {
                    **self.REAL_FACTORS,
                    "orders": [
                        {
                            "alive": True,
                            "price": "0.0001",
                            "acceptedSpeed": "0.0",
                            "type": "STANDARD",
                        },
                        {
                            "alive": True,
                            "price": "0.68",
                            "acceptedSpeed": "0.0005",
                            "type": "STANDARD",
                        },
                    ],
                }
            }
        }
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_nicehash_orderbook

        result = get_nicehash_orderbook()
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        # The ghost order (0.0001, speed 0) is filtered: the real 0.68 wins.
        assert result["price_btc_per_th_day"] == pytest.approx(6.8e-7, rel=1e-6)
        assert result["available_orders"] == 1

    def test_junk_order_rejected(self, monkeypatch):
        """A junk/market order (limit=0, price ~6000× below the book but
        acceptedSpeed>0) must NOT win as cheapest — it made the panel show
        ROI +5.4M% (cost≈0). Cheapest must come from the sane price cluster
        (book captured live from api2.nicehash.com, 18-Aug)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "stats": {
                "BTC": {
                    **self.REAL_FACTORS,
                    "orders": [
                        {
                            "alive": True,
                            "price": "0.00010000",
                            "acceptedSpeed": "0.00080172",
                            "limit": "0.00000000",
                            "rigsCount": 121,
                            "type": "STANDARD",
                        },
                        {
                            "alive": True,
                            "price": "0.10000000",
                            "acceptedSpeed": "0.00005010",
                            "type": "STANDARD",
                        },
                        {
                            "alive": True,
                            "price": "0.10010000",
                            "acceptedSpeed": "0.00034359",
                            "type": "STANDARD",
                        },
                        {
                            "alive": True,
                            "price": "0.58760000",
                            "acceptedSpeed": "0.00007158",
                            "type": "STANDARD",
                        },
                        {
                            "alive": True,
                            "price": "0.67550000",
                            "acceptedSpeed": "0.00004503",
                            "type": "STANDARD",
                        },
                        {
                            "alive": True,
                            "price": "0.67550000",
                            "acceptedSpeed": "0.00012760",
                            "type": "STANDARD",
                        },
                        {
                            "alive": True,
                            "price": "0.68000000",
                            "acceptedSpeed": "0.00026485",
                            "type": "STANDARD",
                        },
                        {
                            "alive": True,
                            "price": "0.68230000",
                            "acceptedSpeed": "0.00011453",
                            "type": "STANDARD",
                        },
                    ],
                }
            }
        }
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_nicehash_orderbook

        result = get_nicehash_orderbook()
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        # The junk 0.0001 and the sub-floor 0.10/0.1001 orders (all < 20% of
        # the book median 0.63155) are rejected: cheapest = 0.5876 BTC/EH/d
        # = 5.876e-7 BTC/TH/d = 58.76 sats/TH/d (the real market price).
        assert result["price_btc_per_th_day"] == pytest.approx(5.876e-7, rel=1e-4)
        # acceptedSpeed 0.00007158 EH = 7.158e13 H/s = 0.07158 PH/s
        assert result["best_order_speed_ph"] == pytest.approx(0.07158, rel=1e-4)
        # available_orders = all 8 active (ghost filter only removes speed=0)
        assert result["available_orders"] == 8

    def test_legacy_payload_defaults_to_eh_factor(self, monkeypatch):
        """Payload WITHOUT priceFactor (pre-audit mocks) falls back to 1e18
        (EH) — the only factor the real SHA256 API ever returns. Locks the
        path that let the original 1e6× unit bug slip through."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "stats": {
                "BTC": {
                    "orders": [
                        {"alive": True, "price": "0.68", "acceptedSpeed": "0.0005"},
                    ],
                }
            }
        }
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_nicehash_orderbook

        result = get_nicehash_orderbook()
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        # Default 1e18 (EH): 0.68 BTC/EH/d → 6.8e-7 BTC/TH/d = 68 sats/TH/d.
        assert result["price_btc_per_th_day"] == pytest.approx(6.8e-7, rel=1e-6)

    def test_all_ghost_orders_error(self, monkeypatch):
        """If every order has acceptedSpeed=0, return error (nothing sellable)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "stats": {
                "BTC": {
                    **self.REAL_FACTORS,
                    "orders": [
                        {"alive": True, "price": "0.68", "acceptedSpeed": "0.0"},
                    ],
                }
            }
        }
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_nicehash_orderbook

        result = get_nicehash_orderbook()
        assert "error" in result

    def test_empty_orders(self, monkeypatch):
        """No orders should return error."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"stats": {"BTC": {"orders": []}}}
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_nicehash_orderbook

        result = get_nicehash_orderbook()
        assert "error" in result

    def test_only_dead_orders(self, monkeypatch):
        """All orders with alive=false should return error."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "stats": {
                "BTC": {
                    "orders": [
                        {
                            "alive": False,
                            "price": "0.0005",
                            "acceptedSpeed": "10.0",
                            "type": "STANDARD",
                        },
                    ]
                }
            }
        }
        monkeypatch.setattr(
            "agents.solo_mining_advisor.tools.requests.get", lambda url, **kw: mock_resp
        )
        from agents.solo_mining_advisor.tools import get_nicehash_orderbook

        result = get_nicehash_orderbook()
        assert "error" in result

    def test_api_error(self, monkeypatch):
        """Connection failure should return error dict."""

        def _raise(*a, **kw):
            raise Exception("timeout")

        monkeypatch.setattr("agents.solo_mining_advisor.tools.requests.get", _raise)
        from agents.solo_mining_advisor.tools import get_nicehash_orderbook

        result = get_nicehash_orderbook()
        assert "error" in result
        assert "unreachable" in result["error"].lower()


# ══════════════════════════════════════════════════════════════════════════
#  NORMALIZATION LAYER — services/hashrate_market.py
#  fetch_* → NormalizedOffer
# ══════════════════════════════════════════════════════════════════════════


class TestFetchBraiinsOffer:
    """Tests for fetch_braiins_offer() — wraps get_braiins_orderbook."""

    def test_success(self):
        """When get_braiins_orderbook returns valid data, return NormalizedOffer.
        Note: fetch_braiins_offer always uses DEFAULT_RENTAL_HASHRATE_TH as hashrate."""
        with patch("services.hashrate_market.get_braiins_orderbook") as mock_get:
            mock_get.return_value = {
                "price_btc_per_ph_day": 0.00005,
                "available_asks": 3,
                "available_bids": 1,
                "price_unit": "sats/PH/day",
                "price_raw": 5000,
            }
            result = fetch_braiins_offer()
            assert result is not None
            assert result.provider == "braiins"
            # price_per_th_day = price_btc_per_ph_day / 1000 (1 PH = 1000 TH)
            assert result.price_per_th_day == pytest.approx(0.00005 / 1000, rel=1e-9)
            # fetch_braiins_offer always uses DEFAULT_RENTAL_HASHRATE_TH
            assert result.hashrate == DEFAULT_RENTAL_HASHRATE_TH
            assert result.duration_days == 1.0

    def test_api_error_returns_none(self):
        """When get_braiins_orderbook returns error, fetch returns None."""
        with patch("services.hashrate_market.get_braiins_orderbook") as mock_get:
            mock_get.return_value = {"error": "API unreachable"}
            result = fetch_braiins_offer()
            assert result is None

    def test_missing_fields(self):
        """When best_order_hr_ph is missing, use DEFAULT_RENTAL_HASHRATE_TH."""
        with patch("services.hashrate_market.get_braiins_orderbook") as mock_get:
            mock_get.return_value = {
                "price_btc_per_ph_day": 0.00005,
                "source": "braiins",
            }
            result = fetch_braiins_offer()
            assert result is not None
            assert result.hashrate == DEFAULT_RENTAL_HASHRATE_TH


class TestFetchNicehashOffer:
    """Tests for fetch_nicehash_offer() — wraps get_nicehash_orderbook."""

    def test_success(self):
        """When get_nicehash_orderbook returns valid data, return NormalizedOffer."""
        with patch("services.hashrate_market.get_nicehash_orderbook") as mock_get:
            mock_get.return_value = {
                "price_btc_per_ph_day": 0.0005,
                "best_order_speed_ph": 5.0,
                "available_orders": 3,
                "source": "api2.nicehash.com",
            }
            result = fetch_nicehash_offer()
            assert result is not None
            assert result.provider == "nicehash"
            assert result.price_per_th_day == pytest.approx(0.0005 / 1000, rel=1e-9)
            # 5.0 PH = 5000 TH/s
            assert result.hashrate == pytest.approx(5000.0, rel=1e-6)

    def test_api_error_returns_none(self):
        """When get_nicehash_orderbook returns error, fetch returns None."""
        with patch("services.hashrate_market.get_nicehash_orderbook") as mock_get:
            mock_get.return_value = {"error": "no orders"}
            result = fetch_nicehash_offer()
            assert result is None


class TestFetchMrrOffer:
    """Tests for fetch_mrr_offer() — wraps get_mrr_listings."""

    def test_success(self):
        """When get_mrr_listings returns valid data, return NormalizedOffer.
        fetch_mrr_offer uses key 'best_rig_hash_th' for hashrate (raw TH/s)."""
        with patch("services.hashrate_market.get_mrr_listings") as mock_get:
            mock_get.return_value = {
                "price_btc_per_ph_day": 0.0001,
                "best_rig_hash_th": 1000.0,
                "best_rig_name": "Antminer S19",
                "total_listings": 5,
            }
            result = fetch_mrr_offer()
            assert result is not None
            assert result.provider == "mrr"
            assert result.price_per_th_day == pytest.approx(0.0001 / 1000, rel=1e-9)
            # best_rig_hash_th is already in TH/s
            assert result.hashrate == pytest.approx(1000.0, rel=1e-6)

    def test_api_error_returns_none(self):
        """When get_mrr_listings returns error, fetch returns None."""
        with patch("services.hashrate_market.get_mrr_listings") as mock_get:
            mock_get.return_value = {"error": "no listings"}
            result = fetch_mrr_offer()
            assert result is None

    def test_no_auth_returns_none(self):
        """When get_mrr_listings needs auth, fetch returns None."""
        with patch("services.hashrate_market.get_mrr_listings") as mock_get:
            mock_get.return_value = {"needs_auth": True, "error": "no credentials"}
            result = fetch_mrr_offer()
            assert result is None


class TestFetchParasiteOffer:
    """Tests for fetch_parasite_offer() — pool fee-based mining as rental."""

    def test_success_with_pool_data(self):
        """Pool data available, but the fee-only price model is mathematically
        sub-floor (~0.04 sats/TH·h — ~1000× below real rentals), so the
        estimate is REJECTED rather than polluting 'cheapest market'."""
        with patch(
            "agents.solo_mining_advisor.tools.get_parasite_pool_stats"
        ) as mock_pool:
            mock_pool.return_value = {
                "pool_hashrate": "161.6",  # PH/s
                "worker_count": 6,
                "pool_fee_pct": 0.0,
                "pool_name": "parasite.space",
            }
            assert fetch_parasite_offer() is None

    def test_no_pool_data_returns_none(self):
        """When pool stats fetch fails, return None."""
        with patch(
            "agents.solo_mining_advisor.tools.get_parasite_pool_stats"
        ) as mock_pool:
            mock_pool.side_effect = Exception("API error")
            result = fetch_parasite_offer()
            assert result is None

    def test_empty_pool_data(self):
        """When pool stats returns empty dict, return None."""
        with patch(
            "agents.solo_mining_advisor.tools.get_parasite_pool_stats"
        ) as mock_pool:
            mock_pool.return_value = {}
            result = fetch_parasite_offer()
            assert result is None


class TestFetchAllOffers:
    """Tests for fetch_all_offers() — aggregation of all providers."""

    def test_returns_list_of_offers(self):
        """When multiple providers return data, return their NormalizedOffers."""
        with patch("services.hashrate_market.fetch_braiins_offer") as mock_b, patch(
            "services.hashrate_market.fetch_nicehash_offer"
        ) as mock_n, patch("services.hashrate_market.fetch_mrr_offer") as mock_m, patch(
            "services.hashrate_market.fetch_parasite_offer"
        ) as mock_p:

            mock_b.return_value = NormalizedOffer(
                provider="braiins",
                hashrate=10000.0,
                price_per_th_day=5e-11,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )
            mock_n.return_value = NormalizedOffer(
                provider="nicehash",
                hashrate=5000.0,
                price_per_th_day=5e-10,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )
            mock_m.return_value = NormalizedOffer(
                provider="mrr",
                hashrate=1000.0,
                price_per_th_day=2e-8,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )
            mock_p.return_value = NormalizedOffer(
                provider="parasite",
                hashrate=100000.0,
                price_per_th_day=1e-11,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )

            results = fetch_all_offers()
            assert len(results) == 4
            providers = [o.provider for o in results]
            assert "braiins" in providers
            assert "nicehash" in providers
            assert "mrr" in providers
            assert "parasite" in providers

    def test_some_providers_fail(self):
        """When some providers return None, only include successful ones."""
        with patch("services.hashrate_market.fetch_braiins_offer") as mock_b, patch(
            "services.hashrate_market.fetch_nicehash_offer"
        ) as mock_n, patch("services.hashrate_market.fetch_mrr_offer") as mock_m, patch(
            "services.hashrate_market.fetch_parasite_offer"
        ) as mock_p:

            mock_b.return_value = None  # Braiins fails
            mock_n.return_value = NormalizedOffer(
                provider="nicehash",
                hashrate=5000.0,
                price_per_th_day=5e-10,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )
            mock_m.return_value = None  # MRR fails
            mock_p.return_value = NormalizedOffer(
                provider="parasite",
                hashrate=100000.0,
                price_per_th_day=1e-11,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )

            results = fetch_all_offers()
            assert len(results) == 2
            providers = [o.provider for o in results]
            assert "nicehash" in providers
            assert "parasite" in providers

    def test_all_providers_fail(self):
        """When ALL providers return None, return empty list."""
        with patch(
            "services.hashrate_market.fetch_braiins_offer", return_value=None
        ), patch(
            "services.hashrate_market.fetch_nicehash_offer", return_value=None
        ), patch(
            "services.hashrate_market.fetch_mrr_offer", return_value=None
        ), patch(
            "services.hashrate_market.fetch_parasite_offer", return_value=None
        ):
            results = fetch_all_offers()
            assert results == []

    def test_offers_in_deterministic_order(self):
        """Offers should be returned in the order: Braiins, MRR, NiceHash, Parasite.
        fetch_all_offers does NOT sort by price — it appends in provider loop order."""
        with patch("services.hashrate_market.fetch_braiins_offer") as mock_b, patch(
            "services.hashrate_market.fetch_nicehash_offer"
        ) as mock_n, patch("services.hashrate_market.fetch_mrr_offer") as mock_m, patch(
            "services.hashrate_market.fetch_parasite_offer"
        ) as mock_p:

            mock_b.return_value = NormalizedOffer(
                provider="braiins",
                hashrate=10000.0,
                price_per_th_day=1e-10,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )
            mock_m.return_value = NormalizedOffer(
                provider="mrr",
                hashrate=1000.0,
                price_per_th_day=1e-9,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )
            mock_n.return_value = NormalizedOffer(
                provider="nicehash",
                hashrate=5000.0,
                price_per_th_day=5e-10,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )
            mock_p.return_value = NormalizedOffer(
                provider="parasite",
                hashrate=100000.0,
                price_per_th_day=5e-11,
                duration_days=1.0,
                fee_pct=0.0,
                algorithm="sha256",
                meta={},
            )

            results = fetch_all_offers()
            expected_order = ["braiins", "mrr", "nicehash", "parasite"]
            got_order = [o.provider for o in results]
            assert (
                got_order == expected_order
            ), f"Expected {expected_order}, got {got_order}"


# ══════════════════════════════════════════════════════════════════════════
#  NormalizedOffer dataclass tests
# ══════════════════════════════════════════════════════════════════════════


class TestNormalizedOffer:
    """Tests for the NormalizedOffer dataclass."""

    def test_to_dict(self):
        """to_dict() should return a proper dict with all fields."""
        offer = NormalizedOffer(
            provider="braiins",
            hashrate=10500.0,
            price_per_th_day=5e-11,
            duration_days=1.0,
            fee_pct=0.0,
            algorithm="sha256",
            meta={"source": "braiins.com"},
        )
        d = offer.to_dict()
        assert d["provider"] == "braiins"
        assert d["hashrate"] == 10500.0
        assert d["price_per_th_day"] == 5e-11
        assert d["meta"]["source"] == "braiins.com"

    def test_default_meta(self):
        """When no meta given, default to empty dict."""
        offer = NormalizedOffer(
            provider="test",
            hashrate=100.0,
            price_per_th_day=1e-10,
            duration_days=1.0,
            fee_pct=0.0,
            algorithm="sha256",
        )
        assert offer.meta == {}
