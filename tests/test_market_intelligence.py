import time
import sqlite3

import pytest

from services.hashrate_market import (
    NormalizedOffer,
    compute_metrics,
    score_offer,
    build_highlights,
    persist_market_history,
    fetch_market_history,
    fetch_mrr_offer,
)
from app import app as _app, get_db


@pytest.fixture
def client():
    _app.config["TESTING"] = True
    return _app.test_client()


class TestHashrateMarketMetrics:
    def test_compute_metrics_positive_roi(self):
        offer = NormalizedOffer(
            provider="braiins",
            hashrate=1000.0,
            price_per_th_day=1e-6,
            duration_days=1.0,
            fee_pct=0.0,
            algorithm="sha256",
        )
        metrics = compute_metrics(offer, network_hashrate=6e20)
        assert metrics["estimated_cost_btc"] > 0
        assert metrics["estimated_revenue_btc"] >= 0
        assert "risk_level" in metrics
        assert metrics["network_hashrate"] == 6e20

    def test_score_offer_contains_id_and_metrics(self):
        offer = NormalizedOffer(
            provider="mrr",
            hashrate=500.0,
            price_per_th_day=2e-6,
            duration_days=1.0,
            fee_pct=0.0,
            algorithm="sha256",
        )
        scored = score_offer(offer, network_hashrate=6e20)
        assert "id" in scored
        assert scored["provider"] == "mrr"
        assert "metrics" in scored
        assert "score" in scored["metrics"]

    def test_build_highlights_from_cached_prices(self):
        last_known = {
            "braiins": {"price": 0.000100, "ts": int(time.time()), "label": "100 sats/PH/day"},
            "mrr": {"price": 0.000080, "ts": int(time.time()), "label": "80 sats/PH/day"},
        }
        snapshot = {"network": {"hashrate": 6e20}}
        highlights = build_highlights(snapshot, last_known, max_items=2)
        assert len(highlights) == 2
        # Higher score first (better ROI)
        assert highlights[0]["metrics"]["score"] >= highlights[1]["metrics"]["score"]


class TestMarketHistoryPersistence:
    def test_persist_and_fetch_history(self, tmp_path):
        # Point to a temp DB so we don't interfere with real data.
        offer = NormalizedOffer(
            provider="braiins",
            hashrate=1000.0,
            price_per_th_day=1e-6,
            duration_days=1.0,
            fee_pct=0.0,
            algorithm="sha256",
        )
        conn = sqlite3.connect(str(tmp_path / "market.sqlite"))
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE IF NOT EXISTS hashrate_market_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                provider TEXT NOT NULL,
                hashrate REAL,
                price_per_th_day REAL,
                duration_days REAL,
                fee_pct REAL,
                algorithm TEXT,
                score REAL,
                raw_data TEXT
            )"""
        )
        persist_market_history(conn, [offer])
        rows = fetch_market_history(conn, limit=10)
        assert len(rows) == 1
        assert rows[0]["provider"] == "braiins"
        assert rows[0]["algorithm"] == "sha256"
        conn.close()


class TestMrrZeroHashrateGuard:
    def test_mrr_zero_hashrate_uses_default(self, monkeypatch):
        def fake_get_mrr_listings():
            return {
                "price_btc_per_ph_day": 0.0001,
                "best_rig_hash_th": 0,
                "best_rig_name": "test-rig",
                "total_listings": 1,
                "algo": "sha256",
            }

        monkeypatch.setattr("services.hashrate_market.get_mrr_listings", fake_get_mrr_listings)
        offer = fetch_mrr_offer()
        assert offer is not None
        assert offer.hashrate == 1000.0


class TestStalePriceFiltering:
    def test_build_highlights_skips_stale_prices(self):
        old_ts = int(time.time()) - 1000  # older than default 300s threshold
        last_known = {
            "braiins": {"price": 0.0001, "ts": old_ts, "label": "stale"},
        }
        highlights = build_highlights({}, last_known)
        assert highlights == []


class TestApiHashrateMarket:
    def test_hashrate_market_returns_success(self, client, monkeypatch):
        def fake_fetch_all_offers():
            return [
                NormalizedOffer(
                    provider="braiins",
                    hashrate=1000.0,
                    price_per_th_day=1e-6,
                    duration_days=1.0,
                    fee_pct=0.0,
                    algorithm="sha256",
                )
            ]

        monkeypatch.setattr("app._fetch_all_offers", fake_fetch_all_offers)
        res = client.get("/api/hashrate-market")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert len(data["offers"]) == 1
        assert data["offers"][0]["provider"] == "braiins"
        assert "metrics" in data["offers"][0]

    def test_hashrate_market_history_returns_records(self, client, monkeypatch):
        def fake_fetch_history(conn, limit=100):
            return [
                {
                    "ts": 1700000000,
                    "provider": "braiins",
                    "hashrate": 1000.0,
                    "price_per_th_day": 1e-6,
                    "duration_days": 1.0,
                    "fee_pct": 0.0,
                    "algorithm": "sha256",
                    "score": 1.23,
                    "raw_data": "{}",
                }
            ]

        monkeypatch.setattr("app._fetch_market_history", fake_fetch_history)
        res = client.get("/api/hashrate-market/history")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert len(data["records"]) == 1

    def test_hashrate_market_caches_offers(self, client, monkeypatch):
        import unittest.mock as mock

        # Reset cache so the first request fetches live.
        from app import _HASHRATE_MARKET_CACHE
        _HASHRATE_MARKET_CACHE["ts"] = 0
        _HASHRATE_MARKET_CACHE["offers"] = None

        fake_offer = NormalizedOffer(
            provider="braiins",
            hashrate=1000.0,
            price_per_th_day=1e-6,
            duration_days=1.0,
            fee_pct=0.0,
            algorithm="sha256",
        )
        mock_fetch = mock.Mock(return_value=[fake_offer])
        monkeypatch.setattr("app._fetch_all_offers", mock_fetch)

        res1 = client.get("/api/hashrate-market")
        assert res1.status_code == 200
        res2 = client.get("/api/hashrate-market")
        assert res2.status_code == 200

        # Live fetch should only happen once within the cache TTL.
        assert mock_fetch.call_count == 1

    def test_opportunities_compare_filters_providers(self, client, monkeypatch):
        def fake_fetch_all_offers():
            return [
                NormalizedOffer(
                    provider="braiins",
                    hashrate=1000.0,
                    price_per_th_day=1e-6,
                    duration_days=1.0,
                    fee_pct=0.0,
                    algorithm="sha256",
                ),
                NormalizedOffer(
                    provider="mrr",
                    hashrate=500.0,
                    price_per_th_day=2e-6,
                    duration_days=1.0,
                    fee_pct=0.0,
                    algorithm="sha256",
                ),
            ]

        monkeypatch.setattr("app._fetch_all_offers", fake_fetch_all_offers)
        res = client.get("/api/opportunities/compare?providers=braiins")
        assert res.status_code == 200
        data = res.get_json()
        assert len(data["offers"]) == 1
        assert data["offers"][0]["provider"] == "braiins"


class TestOpportunitiesEnrichment:
    def test_opportunities_endpoint_enriches_and_sorts(self, client, monkeypatch):
        # Patch the opportunity engine scan to return synthetic opportunities
        def fake_scan(execute_tool, snapshot, last_known_prices=None):
            return (
                [
                    {
                        "id": "braiins_0.001",
                        "platform": "braiins",
                        "title": "Braiins offer",
                        "price": 0.0001,
                        "status": "REAL",
                    },
                    {
                        "id": "mrr_0.001",
                        "platform": "mrr",
                        "title": "MRR offer",
                        "price": 0.00005,
                        "status": "ESTIMATED",
                    },
                ],
                {"braiins_ok": 1, "braiins_errors": 0, "mrr_ok": 1, "mrr_errors": 0},
            )

        monkeypatch.setattr("app._opp_scan", fake_scan)
        res = client.get("/api/opportunities")
        assert res.status_code == 200
        data = res.get_json()
        opps = data["opportunities"]
        assert len(opps) == 2
        for o in opps:
            assert "metrics" in o
            assert "score" in o["metrics"]
        # Should be sorted descending by score.
        assert opps[0]["metrics"]["score"] >= opps[1]["metrics"]["score"]


class TestSnapshotMarketHighlights:
    def test_snapshot_includes_market_highlights(self, client, monkeypatch):
        # Ensure latest_snapshot is populated enough to avoid KeyErrors.
        monkeypatch.setattr(
            "app.latest_snapshot",
            {
                "ts": 1700000000,
                "network": {"hashrate": 6e20},
                "btc_price": {"usd": 100000, "brl": 500000},
            },
        )
        monkeypatch.setattr(
            "services.state.last_known_prices",
            {
                "braiins": {"price": 0.0001, "ts": 1700000000, "label": "100 sats"},
            },
        )
        res = client.get("/api/snapshot")
        assert res.status_code == 200
        data = res.get_json()
        assert "market_highlights" in data
