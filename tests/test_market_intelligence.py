import time
import sqlite3

import pytest

from app import (
    _hashrate_market_health,
    _hashrate_market_warmup_cycle,
    _HASHRATE_MARKET_CACHE_TTL,
    _HASHRATE_MARKET_EMPTY_CACHE_TTL,
)

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
        def fake_fetch_all_offers(network_hashrate=None):
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
        # Reset the in-memory market cache so the mocked fetcher is actually used
        # (a prior test in the suite may have populated it with real offers).
        monkeypatch.setattr("app._HASHRATE_MARKET_CACHE", {"ts": 0, "offers": None})
        res = client.get("/api/hashrate-market")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert len(data["offers"]) == 1
        assert data["offers"][0]["provider"] == "braiins"
        assert "metrics" in data["offers"][0]

    def test_hashrate_market_exposes_warmup_health(self, client, monkeypatch):
        def fake_fetch_all_offers(network_hashrate=None):
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
        # Reset the in-memory market cache so the mocked fetcher is actually used
        # (a prior test in the suite may have populated it with real offers).
        monkeypatch.setattr("app._HASHRATE_MARKET_CACHE", {"ts": 0, "offers": None})
        res = client.get("/api/hashrate-market")
        assert res.status_code == 200
        health = res.get_json()["health"]
        assert health["last_fetch_ts"] > 0   # cache just filled by this request
        assert health["offers_count"] == 1
        assert health["age_s"] >= 0
        assert health["stale"] is False
        assert health["warmup_interval_s"] >= 1

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
        def fake_fetch_all_offers(network_hashrate=None):
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


class TestSnapshotBestPriceEstimatedExclusion:
    """Parasite regression: estimated offers (parasite pool-fee model) must
    NEVER be crowned 'best price' on /api/snapshot.
    Only real marketplace quotes may win — estimated offers still render as
    ESTIMATED cards but never as the 'best deal' highlight. Mirrors the
    frontend _mktBestIndex fix in static/app.js."""

    def _seed(self, monkeypatch, prices):
        # Skip the live provider fetch (would overwrite our injected prices).
        monkeypatch.setattr("app._get_hashrate_market_offers", lambda: None)
        monkeypatch.setattr(
            "app.latest_snapshot",
            {"ts": 1700000000, "network": {"hashrate": 6e20}, "btc_price": {"usd": 100000}},
        )
        monkeypatch.setattr("services.state.last_known_prices", prices)

    def test_estimated_offer_never_wins_best_price(self, client, monkeypatch):
        """A real quote (5k sats/TH/d) beats a cheap estimated parasite quote
        (~1 sat/TH/d): the estimated offer must not win despite the lower
        price — the whole point of the market_hl fix in api_snapshot."""
        now = int(time.time())
        self._seed(monkeypatch, {
            "parasite": {"price": 1e-5, "ts": now, "label": "Parasite", "estimated": True},
            "braiins": {"price": 5e-2, "ts": now, "label": "Braiins"},
        })
        res = client.get("/api/snapshot")
        assert res.status_code == 200
        md = res.get_json()["market_data"]
        # Best price reflects the REAL Braiins quote, not the estimated parasite.
        assert md["best_price"] == "5000.00 sats/TH/d"
        # Both offers still render in the cards; parasite stays flagged.
        offers = md["offers"]
        by_provider = {o["provider"]: o for o in offers}
        assert set(by_provider) == {"parasite", "braiins"}
        assert by_provider["parasite"]["estimated"] is True
        assert by_provider["braiins"]["estimated"] is False
        # Grid order: the REAL quote renders before the estimated card — the
        # synthetic ~1 sat/TH/d never leads the grid (real-first sort).
        assert [o["provider"] for o in offers] == ["braiins", "parasite"]

    def test_all_estimated_falls_back_to_lowest_price(self, client, monkeypatch):
        """When every offer is estimated there is no real quote — the documented
        fallback (market_hl or sorted_hl) picks the lowest price, honest about
        the absence of a real marketplace price."""
        now = int(time.time())
        self._seed(monkeypatch, {
            "parasite": {"price": 1e-5, "ts": now, "label": "Parasite", "estimated": True},
            "derived": {"price": 5e-2, "ts": now, "label": "Derived", "estimated": True},
        })
        res = client.get("/api/snapshot")
        assert res.status_code == 200
        md = res.get_json()["market_data"]
        assert md["best_price"] == "1.00 sats/TH/d"

    def test_mixed_real_and_estimated_keeps_real_winner(self, client, monkeypatch):
        """Real quotes compete among themselves; the estimated offer never
        displaces them even when it has the lowest price of all."""
        now = int(time.time())
        self._seed(monkeypatch, {
            "parasite": {"price": 1e-5, "ts": now, "label": "Parasite", "estimated": True},
            "braiins": {"price": 1e-1, "ts": now, "label": "Braiins"},
            "mrr": {"price": 5e-2, "ts": now, "label": "MRR"},
        })
        res = client.get("/api/snapshot")
        assert res.status_code == 200
        md = res.get_json()["market_data"]
        # MRR (5e-2 → 5000 sats/TH/d) is the cheapest REAL quote → wins.
        assert md["best_price"] == "5000.00 sats/TH/d"
        # Real-first grid order: both real quotes render before the estimated
        # parasite card, which never steals the top slot.
        providers = [o["provider"] for o in md["offers"]]
        assert providers[-1] == "parasite"
        assert providers[0] in ("braiins", "mrr")
        assert providers[1] in ("braiins", "mrr")


class TestApiMarketTrendAndHistory:
    """The 7d price-trend chart endpoints (/api/market/trend per-provider and
    /api/market/history flat series) — the dashboard Hash Market trend chart
    and the mobile price history both read from these. Locks the aggregation,
    the 7d/168h lookback cutoffs and the TH→PH conversion."""

    _PROV = "utrend"  # distinctive provider prefix — never collides with real data

    def _seed(self, conn, ts, provider, price):
        conn.execute(
            """INSERT INTO hashrate_market_history
            (ts, provider, hashrate, price_per_th_day, duration_days, fee_pct,
             algorithm, score, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, provider, 1000.0, price, 1.0, 0.0, "sha256", 1.0, "{}"),
        )
        conn.commit()

    def _seed_multi(self):
        """Seed a deterministic 7d window: two providers at three timestamps."""
        now = int(time.time())
        conn = get_db()
        for off in (0, 3600, 7200):
            self._seed(conn, now - off, f"{self._PROV}-a", 1e-6)
            self._seed(conn, now - off, f"{self._PROV}-b", 2e-6)
        conn.close()

    def _clean(self):
        conn = get_db()
        conn.execute(f"DELETE FROM hashrate_market_history WHERE provider LIKE '{self._PROV}%'")
        conn.commit()
        conn.close()

    @pytest.fixture(autouse=True)
    def _cleanup(self):
        yield
        self._clean()

    # ── /api/market/trend (per-provider, 7d window) ────────────────────────
    # NOTE: these endpoints read the session-wide scratch DB, and earlier
    # tests in this file persist REAL providers (braiins/mrr/…) through
    # /api/hashrate-market with mocked offers. All asserts are therefore
    # scoped to the distinctive utrend-* providers (subset semantics) so the
    # suite stays hermetic regardless of what earlier tests persisted.

    def test_trend_aggregates_by_provider(self, client):
        self._seed_multi()
        r = client.get("/api/market/trend")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        provs = data["providers"]
        assert f"{self._PROV}-a" in provs and f"{self._PROV}-b" in provs
        # Each provider keeps all its points, ordered by ts ascending.
        pts = provs[f"{self._PROV}-a"]
        assert len(pts) == 3
        assert pts[0]["ts"] <= pts[1]["ts"] <= pts[2]["ts"]
        assert pts[0]["price_btc_per_th_day"] == 1e-6
        assert pts[0]["price_btc_per_ph_day"] == 1e-3  # TH→PH = ×1000
        assert "score" in pts[0]

    def test_trend_respects_7d_cutoff(self, client):
        now = int(time.time())
        conn = get_db()
        self._seed(conn, now - 3600, f"{self._PROV}-a", 1e-6)          # fresh
        self._seed(conn, now - 8 * 86400, f"{self._PROV}-a", 9e-6)     # stale
        conn.close()
        r = client.get("/api/market/trend")
        pts = r.get_json()["providers"][f"{self._PROV}-a"]
        assert [p["price_btc_per_th_day"] for p in pts] == [1e-6]

    def test_trend_never_exposes_foreign_provider(self, client):
        """Unseeded utrend-* providers must never appear (hermetic check)."""
        r = client.get("/api/market/trend")
        provs = r.get_json()["providers"]
        assert not any(k.startswith(self._PROV) for k in provs)

    def test_trend_drops_provider_inactive_48h(self, client):
        """A provider inside the 7d window but without a quote for >48h (e.g.
        the removed kissmyhash) must NOT be served — its stale line would
        inflate the 'N providers' badge in the dashboard."""
        now = int(time.time())
        conn = get_db()
        self._seed(conn, now - 3600, f"{self._PROV}-a", 1e-6)          # active
        self._seed(conn, now - 100 * 3600, f"{self._PROV}-b", 9e-6)    # stale 100h
        conn.close()
        r = client.get("/api/market/trend")
        provs = r.get_json()["providers"]
        assert f"{self._PROV}-a" in provs
        assert f"{self._PROV}-b" not in provs

    # ── /api/market/history (flat series, hours window) ───────────────────

    def test_history_flat_series_with_ph_conversion(self, client):
        self._seed_multi()
        r = client.get("/api/market/history?limit=200&hours=168")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        mine = [x for x in data["records"] if x["provider"].startswith(self._PROV)]
        assert len(mine) == 6
        rec = mine[0]
        assert rec["price_btc_per_ph_day"] == rec["price_btc_per_th_day"] * 1000
        assert "ts" in rec and "hashrate" in rec

    def test_history_respects_hours_window(self, client):
        now = int(time.time())
        conn = get_db()
        self._seed(conn, now - 1800, f"{self._PROV}-a", 1e-6)        # inside 1h
        self._seed(conn, now - 7200, f"{self._PROV}-a", 9e-6)        # outside 1h
        conn.close()
        r = client.get("/api/market/history?hours=1")
        data = r.get_json()
        mine = [x for x in data["records"] if x["provider"].startswith(self._PROV)]
        assert len(mine) == 1
        assert mine[0]["price_btc_per_th_day"] == 1e-6

    def test_history_never_exposes_foreign_provider(self, client):
        """Unseeded utrend-* providers must never appear (hermetic check)."""
        r = client.get("/api/market/history")
        records = r.get_json()["records"]
        assert not any(x["provider"].startswith(self._PROV) for x in records)


class TestHashrateMarketHealth:
    """Warmup/cache health exposed via _hashrate_market_health() — the field
    surfaced on /api/hashrate-market and the snapshot's market_data. Lets
    operators confirm the 5-min background warm-up is running."""

    def test_health_cold_cache(self, monkeypatch):
        monkeypatch.setattr("app._HASHRATE_MARKET_CACHE", {"ts": 0, "offers": None})
        h = _hashrate_market_health()
        assert h["last_fetch_ts"] == 0
        assert h["offers_count"] == 0
        assert h["age_s"] is None          # never fetched → no age
        assert h["stale"] is False
        assert h["ttl_s"] == _HASHRATE_MARKET_EMPTY_CACHE_TTL
        assert h["warmup_interval_s"] >= 1

    def test_health_warm_cache(self, monkeypatch):
        monkeypatch.setattr(
            "app._HASHRATE_MARKET_CACHE",
            {"ts": int(time.time()) - 5, "offers": ["a", "b"]},
        )
        h = _hashrate_market_health()
        assert h["offers_count"] == 2
        # ts was set 5s ago but a wall-clock second boundary between the two
        # time.time() calls can make this 5 or 6 — accept both (no flake).
        assert h["age_s"] in (5, 6)
        assert h["stale"] is False
        assert h["ttl_s"] == _HASHRATE_MARKET_CACHE_TTL

    def test_health_stale_cache(self, monkeypatch):
        monkeypatch.setattr(
            "app._HASHRATE_MARKET_CACHE",
            {"ts": int(time.time()) - 600, "offers": ["a"]},
        )
        h = _hashrate_market_health()
        assert h["stale"] is True


# ══════════════════════════════════════════════════════════════════════
# Background warm-up (keeps the LEASE mode cache hot)
# ══════════════════════════════════════════════════════════════════════

class TestHashrateMarketWarmup:
    """The 5-min background warm-up must reuse the shared getter (so the
    cache write + history persistence + _shared_state sync all stay in one
    place) and never raise — a provider outage must not kill the thread."""

    def test_warmup_cycle_calls_shared_getter(self, monkeypatch):
        calls = []

        def fake_getter():
            calls.append(1)
            return ["offer"]

        monkeypatch.setattr("app._get_hashrate_market_offers", fake_getter)
        _hashrate_market_warmup_cycle()
        assert calls == [1]

    def test_warmup_cycle_swallows_errors(self, monkeypatch):
        def broken_getter():
            raise RuntimeError("provider down")

        monkeypatch.setattr("app._get_hashrate_market_offers", broken_getter)
        # Must not raise — the background thread stays alive on outage.
        _hashrate_market_warmup_cycle()
