"""
CYPHER65 // Sentinel policy (Issue #203) — missing data stays missing
=====================================================================
Guards the centralized ``helpers.coerce_ts`` guard and the API/state
surfaces that must expose a ``null``/None sentinel instead of epoch-0
(1970-01-01 / ``updated_at: 0``):

  1. coerce_ts(): None for missing/invalid/epoch values, int for real ts.
  2. snapshot market_data empty branch → ``updated_at: null`` (never 0).
  3. hashrate-market health (app.py + snapshot_enrichment) → cold cache
     reports ``last_fetch_ts: null``, not 0.
"""
import pytest

from helpers import coerce_ts

from app import _hashrate_market_health as _app_health
from services.snapshot_enrichment import (
    _hashrate_market_health as _snap_health,
    enrich_snapshot,
)


class TestCoerceTs:
    """The centralized sentinel guard: real unix ts or None, never 0."""

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            " ",
            "N/A",
            "null",
            "—",
            0,
            -5,
            "0",
            "-1",
            0.0,
            True,
            False,
            "abc",
            "1970-01-01",  # date string — not a numeric ts
            float("nan"),
        ],
    )
    def test_missing_or_invalid_returns_none(self, value):
        assert coerce_ts(value) is None

    @pytest.mark.parametrize("value", [1, "1", 1700000000, "1700000000", 1700000000.9, 1e9])
    def test_real_timestamp_returns_int(self, value):
        out = coerce_ts(value)
        assert isinstance(out, int)
        assert out > 0
        assert out == int(value)


class TestMarketDataEmptyBranch:
    """The empty market_data payload must say null, not 1970/epoch 0."""

    def test_empty_market_data_updated_at_is_none(self, monkeypatch):
        import services.state as state

        monkeypatch.setattr(
            "services.snapshot_enrichment._get_hashrate_market_offers",
            lambda s: [],
            raising=False,
        )
        # NOTE: patch the module-local names (import-time aliases) — patching
        # services.hashrate_market.* does NOT affect the already-imported refs.
        monkeypatch.setattr(
            "services.snapshot_enrichment._fetch_all_offers",
            lambda *a, **k: [],
            raising=False,
        )
        monkeypatch.setattr(
            "services.snapshot_enrichment._build_market_highlights",
            lambda *a, **k: [],
            raising=False,
        )
        monkeypatch.setattr(
            "services.snapshot_enrichment.build_auto_pilot_context",
            lambda: {
                "peak_hashrate_7d": 0.0,
                "automation_preview": [],
                "armed": False,
                "temp_high_c": 75.0,
            },
        )
        monkeypatch.setattr(
            "services.snapshot_enrichment.build_command_center",
            lambda snap: [],
        )
        # Cold cache: no offers ever fetched (monkeypatch restores the global).
        monkeypatch.setattr(
            state,
            "market_data_cache",
            {"offers": [], "best_price": None, "updated_at": 0, "loading": True, "error": None},
        )
        monkeypatch.setattr(
            "services.snapshot_enrichment._HASHRATE_MARKET_CACHE",
            {"ts": 0, "offers": None},
        )
        snap = {
            "ts": 1,
            "worker": {},
            "network": {"hashrate": 6e20},
            "btc_price": {"usd": 60000.0},
        }
        out = enrich_snapshot(dict(snap))
        md = out.get("market_data") or {}
        # Sentinel policy: never fetched → null, not 0 (would render 1970-01-01).
        # The empty branch carries NO health block — null fields only (the
        # cold-cache health is covered by TestHashrateMarketHealthSentinel).
        assert md.get("updated_at") is None
        assert md.get("offers") == []
        assert md.get("health") is None


class TestHashrateMarketHealthSentinel:
    """Cold (never-filled) caches report null last_fetch_ts — both copies."""

    def test_snapshot_enrichment_health_cold_cache_none(self, monkeypatch):
        monkeypatch.setattr(
            "services.snapshot_enrichment._HASHRATE_MARKET_CACHE",
            {"ts": 0, "offers": None},
        )
        h = _snap_health()
        assert h["last_fetch_ts"] is None
        assert h["age_s"] is None
        assert h["stale"] is True

    def test_app_health_cold_cache_none(self, monkeypatch):
        monkeypatch.setattr("app._HASHRATE_MARKET_CACHE", {"ts": 0, "offers": None})
        h = _app_health()
        assert h["last_fetch_ts"] is None
        assert h["age_s"] is None
        assert h["stale"] is False  # never fetched ≠ stale
