"""
CYPHER65 // Anti-Mock Regression Tests
=======================================
Locks the audit premise "no mock data, no placeholders" against regressions:

1. The fabricated BTC price fallback (_BTC_PRICE_FALLBACK_USD = $60k) that was
   injected when CoinGecko failed is GONE — if it ever returns, this fails.
2. /api/v1/status reports integration health (blockchain_api, exchange_api,
   pool_stratum) with online/stale/offline states.
3. The snapshot payload carries `stale` flags for network + btc_price so the
   frontend can show the honest "dados em cache" chip instead of pretending
   data is live.
"""

import app as _app_module

app = _app_module.app


def test_btc_price_mock_fallback_removed():
    """The $60k fabricated price fallback must never come back.

    The old code injected {'usd': 60000.0, ...} when CoinGecko failed — a
    MOCK price that violated the honesty premise. Stale-while-revalidate
    serves the last REAL cached value (flagged stale) or None instead.
    """
    assert not hasattr(_app_module, "_BTC_PRICE_FALLBACK_USD"), (
        "Fabricated BTC price fallback must not exist — use stale-while-revalidate"
    )


def test_last_valid_network_cache_exists():
    """The stale-while-revalidate network cache is present and reset-safe."""
    assert hasattr(_app_module, "_last_valid_network")
    assert set(_app_module._last_valid_network.keys()) >= {"difficulty", "hashrate"}


def test_api_v1_status_endpoint():
    """GET /api/v1/status returns integration health with 3 sources."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/v1/status")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        for src in ("blockchain_api", "exchange_api", "pool_stratum"):
            assert src in data["integrations"], f"missing {src} in status payload"
        # Each source reports a valid status enum
        for src, info in data["integrations"].items():
            assert info["status"] in ("online", "stale", "offline"), f"bad status for {src}"


def test_snapshot_carries_stale_flags():
    """Every snapshot (initial + built) carries network.stale and
    btc_price.stale so the frontend chip logic is always well-defined.

    The poll-built snapshot (services.user_polling._build_snapshot) must also
    carry the keys — if the poll path ever drops them, the frontend would
    silently stop showing the "dados em cache" chip.
    """
    snap = _app_module.latest_snapshot
    net = snap.get("network") or {}
    btc = snap.get("btc_price") or {}
    assert "stale" in net, "network.stale key missing from initial snapshot"
    assert "stale" in btc, "btc_price.stale key missing from initial snapshot"
    # Fresh initial state: stale flags are False (nothing to cache yet).
    assert net["stale"] is False
    assert btc["stale"] is False

    # The poll-built snapshot must carry the same keys (and default to False
    # when no external source has provided real data yet). All global fetches
    # are MOCKED so the unit suite never touches the network (deterministic).
    from unittest.mock import patch
    import services.user_polling as up
    with patch("services.user_polling._fetch_user_data", return_value={"workerData": []}), \
         patch("services.user_polling._fetch_account", return_value=None), \
         patch("services.user_polling._fetch_global_pool", return_value={"hashrate": 1e15}), \
         patch("services.user_polling._fetch_global_leaderboard", return_value=[]), \
         patch("services.user_polling._fetch_global_highest_diffs", return_value=[]), \
         patch("services.user_polling._fetch_global_network", return_value=(857200, 126231507121868.0, 6e20)), \
         patch("services.user_polling._fetch_global_btc_price", return_value={"bitcoin": {"usd": 61234, "brl": 350000}}), \
         patch("services.user_polling._fetch_global_mempool_fees", return_value={"fastestFee": 12}):
        built = up._build_snapshot("bc1qtest", "testminer")
    assert isinstance(built, dict) and built.get("network"), "_build_snapshot should build a snapshot"
    assert "stale" in built["network"], "poll-built snapshot lost network.stale"
    assert "stale" in built.get("btc_price", {}), "poll-built snapshot lost btc_price.stale"
    assert built["network"]["stale"] is False
    assert built["btc_price"]["stale"] is False
