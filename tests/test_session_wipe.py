"""
Unit tests for session isolation functions in app.py and services/proximity.py.

Tests:
- _reset_session_state() — wipes ALL in-memory state on address change
- reset_session() — wipes proximity-specific state

The current _reset_session_state() operates on app.py module globals directly
(latest_snapshot, memory_critical_alerts, _next_memory_alert_id,
persist_consec_failures, _last_proximity_sample_ts, btc_price_cache,
timeline_state, _do_poll caches) and on _shared_state (= services.state) for
last_known_prices / test_opportunities.

Each test monkeypatches the REAL globals with controlled objects so the wipe
runs against isolated state and the real app state is restored afterwards
(monkeypatch teardown). This prevents cross-test pollution.
"""

import time
import types
import pytest
import logging

import app as _app_module
import services.proximity as _proximity_module

_reset_session_state = _app_module._reset_session_state
_reset_session = _proximity_module.reset_session


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _install_mock_globals(monkeypatch, with_do_poll=True):
    """Monkeypatch every global that _reset_session_state() touches.

    Returns a tuple (snapshot, alerts, timeline, shared) of the controlled
    objects so tests can assert on them.
    """
    snapshot = {
        "ts": 1000000,
        "btc_address": "bc1old",
        "worker": {"hashrate": 292e12, "bestDifficulty": "170 G"},
        "user_aggregate": None,
        "pool": {"hashrate": 1e15, "workers": 42},
        "account": {"total_diff": 1.5e15},
        "lightning": None,
        "leaderboard_entry": {"rank": 5},
        "leaderboard_total": 10,
        "highest_diffs": [{"diff": 1e12}],
        "network": {"difficulty": 127e12, "hashrate": 6e20, "height": 876543},
        "btc_price": {"usd": 65000.0, "brl": 320000.0},
        "luck_estimate": {"chance_24h": 0.5},
        "alerts_recent": [{"ts": 1, "severity": "WARN", "message": "x"}],
        "timeline_recent": [],
        "event_stats": {"shares": 100},
        "leaderboard_table_top_30": [{"address": "bc1x", "score": 1}],
    }
    alerts = [
        {"id": 1, "ts": 1, "severity": "WARN", "category": "network", "message": "a"},
        {"id": 2, "ts": 2, "severity": "CRIT", "category": "network", "message": "b"},
    ]
    timeline = {
        "_primed": True,
        "last_submit_ts": 100,
        "last_best_diff_str": "170 G",
        "all_time_best_diff_raw": 500e12,
        "share_submit_history": [{"ts": 1}],
        "share_calc_history": [1, 2],
        "session_share_count": 42,
        "session_best_diff_bumps": 3,
    }
    shared = types.SimpleNamespace(
        last_known_prices={
            "braiins": {"price": 0.0001, "ts": 1},
            "mrr": {"price": 0.0002, "ts": 1},
            "nicehash": {"price": 0.0003, "ts": 1},
            "parasite": {"price": 0.0005, "ts": 1},
        },
        test_opportunities={"opportunities": [{"id": "braiins_0.001"}]},
    )

    monkeypatch.setattr(_app_module, "latest_snapshot", snapshot)
    monkeypatch.setattr(_app_module, "memory_critical_alerts", alerts)
    monkeypatch.setattr(_app_module, "_next_memory_alert_id", 5)
    monkeypatch.setattr(_app_module, "persist_consec_failures", 2)
    monkeypatch.setattr(_app_module, "_last_proximity_sample_ts", 99)
    monkeypatch.setattr(_app_module, "btc_price_cache", {"ts": 5, "data": {"usd": 65000}})
    monkeypatch.setattr(_app_module, "timeline_state", timeline)
    monkeypatch.setattr(_app_module, "_shared_state", shared)
    if with_do_poll:
        monkeypatch.setattr(
            _app_module,
            "_do_poll",
            types.SimpleNamespace(_alert_seen={1, 2, 3}, _worker_was_present=True),
        )
    return snapshot, alerts, timeline, shared


# ═══════════════════════════════════════════════════════════════════════════════
#  _reset_session_state() tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestResetSessionState:
    """_reset_session_state() wipes ALL in-memory state for address isolation."""

    # ── Core state attributes ────────────────────────────────────────────────

    def test_resets_latest_snapshot_to_defaults(self, monkeypatch):
        """latest_snapshot keeps the full schema with default/null values."""
        snapshot, *_ = _install_mock_globals(monkeypatch)
        _reset_session_state()

        assert snapshot["ts"] == 0
        assert snapshot["btc_address"] == _app_module.BTC_ADDRESS
        assert snapshot["worker"] is None
        assert snapshot["pool"] is None
        assert snapshot["account"] is None
        assert snapshot["user_aggregate"] is None
        assert snapshot["lightning"] is None
        assert snapshot["leaderboard_entry"] is None
        assert snapshot["leaderboard_total"] == 0
        assert snapshot["highest_diffs"] == []
        assert snapshot["network"] == {"height": None, "difficulty": None, "hashrate": None}
        assert snapshot["btc_price"] == {"usd": None, "brl": None, "eur": None, "gbp": None,
                                        "jpy": None, "krw": None, "cny": None}
        assert snapshot["luck_estimate"] == {}
        assert snapshot["alerts_recent"] == []
        assert snapshot["timeline_recent"] == []
        assert snapshot["event_stats"] == {}
        assert snapshot["leaderboard_table_top_30"] == []

    def test_clears_memory_critical_alerts(self, monkeypatch):
        """memory_critical_alerts cleared and _next_memory_alert_id reset."""
        _, alerts, *_ = _install_mock_globals(monkeypatch)
        _reset_session_state()
        assert alerts == []
        assert _app_module._next_memory_alert_id == 0

    def test_resets_timeline_state_defaults(self, monkeypatch):
        """timeline_state is reset to fresh defaults and histories cleared."""
        *_, timeline, _ = _install_mock_globals(monkeypatch)
        _reset_session_state()

        assert timeline["_primed"] is False
        assert timeline["last_submit_ts"] == 0
        assert timeline["last_best_diff_str"] == ""
        assert timeline["all_time_best_diff_raw"] == 0.0
        assert timeline["share_submit_history"] == []
        assert timeline["share_calc_history"] == []
        assert timeline["session_share_count"] == 0
        assert timeline["session_best_diff_bumps"] == 0

    def test_clears_do_poll_caches(self, monkeypatch):
        """_do_poll._alert_seen cleared and _worker_was_present reset."""
        _install_mock_globals(monkeypatch)
        _reset_session_state()
        assert _app_module._do_poll._alert_seen == set()
        assert _app_module._do_poll._worker_was_present is False

    def test_do_poll_without_caches_no_crash(self, monkeypatch):
        """If _do_poll lacks _alert_seen/_worker_was_present, no crash."""
        _install_mock_globals(monkeypatch, with_do_poll=False)
        _reset_session_state()

    def test_resets_throttle_and_failures(self, monkeypatch):
        """_last_proximity_sample_ts and persist_consec_failures reset to 0."""
        _install_mock_globals(monkeypatch)
        _reset_session_state()
        assert _app_module._last_proximity_sample_ts == 0
        assert _app_module.persist_consec_failures == 0

    def test_resets_btc_price_cache(self, monkeypatch):
        """btc_price_cache reset to empty payload."""
        _install_mock_globals(monkeypatch)
        _reset_session_state()
        assert _app_module.btc_price_cache == {"ts": 0, "data": None}

    def test_last_known_prices_keys_preserved_nulled(self, monkeypatch):
        """last_known_prices keys preserved, values set to None."""
        *_, shared = _install_mock_globals(monkeypatch)
        _reset_session_state()
        for key in ("braiins", "mrr", "nicehash", "parasite"):
            assert shared.last_known_prices[key] is None

    def test_test_opportunities_set_to_none(self, monkeypatch):
        """_shared_state.test_opportunities set to None after wipe."""
        *_, shared = _install_mock_globals(monkeypatch)
        _reset_session_state()
        assert shared.test_opportunities is None

    # ── Defensive: missing optional state should not crash ──────────────────

    def test_no_crash_when_latest_snapshot_missing_keys(self, monkeypatch):
        """latest_snapshot dict missing keys is still wiped via clear/update."""
        snapshot, alerts, timeline, shared = _install_mock_globals(monkeypatch)
        snapshot.clear()  # simulate a partially-populated snapshot
        _reset_session_state()
        assert snapshot["ts"] == 0
        assert snapshot["worker"] is None
        assert alerts == []
        assert timeline["session_share_count"] == 0
        assert shared.test_opportunities is None

    def test_no_crash_when_state_objects_are_empty(self, monkeypatch):
        """Wipe works when snapshot values are empty (required keys present)."""
        snapshot, alerts, timeline, shared = _install_mock_globals(monkeypatch)
        snapshot.clear()
        # timeline_state keys are required by the real wipe — keep them present
        # but with empty values to exercise the empty-state path.
        timeline["share_submit_history"] = []
        timeline["share_calc_history"] = []
        _reset_session_state()
        assert snapshot["ts"] == 0
        assert timeline["_primed"] is False
        assert alerts == []
        assert shared.test_opportunities is None


# ═══════════════════════════════════════════════════════════════════════════════
#  reset_session() (proximity) tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestResetProximitySession:
    """reset_session() wipes proximity-specific state on address change."""

    def test_resets_all_time_best_diff(self, monkeypatch):
        """Should set all_time_best_diff_raw to 0.0."""
        mock_ts = {"all_time_best_diff_raw": 500e12}
        monkeypatch.setattr(_proximity_module, "state", type("obj", (object,), {"timeline_state": mock_ts}))
        _reset_session()
        assert mock_ts["all_time_best_diff_raw"] == 0.0

    def test_resets_throttle(self, monkeypatch):
        """Should set _last_proximity_sample_ts to 0."""
        mock_ts = {"all_time_best_diff_raw": 500e12}
        monkeypatch.setattr(_proximity_module, "state", type("obj", (object,), {"timeline_state": mock_ts}))
        _reset_session()
        assert _proximity_module._last_proximity_sample_ts == 0

    def test_handles_missing_timeline_key(self, monkeypatch):
        """Should create all_time_best_diff_raw key if it doesn't exist."""
        mock_ts = {}  # empty — key doesn't exist yet
        monkeypatch.setattr(_proximity_module, "state", type("obj", (object,), {"timeline_state": mock_ts}))
        _reset_session()
        assert mock_ts.get("all_time_best_diff_raw") == 0.0

    def test_handles_missing_timeline_state(self, monkeypatch):
        """Should NOT crash when timeline_state attribute is missing (defensive guard)."""
        monkeypatch.setattr(_proximity_module, "state", type("obj", (object,), {}))
        # Should not raise — defensive guard added to match _safe_wipe pattern
        _reset_session()

    def test_leaves_other_timeline_keys(self, monkeypatch):
        """Should only reset all_time_best_diff_raw, leave other keys intact."""
        mock_ts = {"all_time_best_diff_raw": 500e12, "session_share_count": 42, "trend": "rising"}
        monkeypatch.setattr(_proximity_module, "state", type("obj", (object,), {"timeline_state": mock_ts}))
        _reset_session()
        assert mock_ts["all_time_best_diff_raw"] == 0.0
        assert mock_ts["session_share_count"] == 42  # untouched
        assert mock_ts["trend"] == "rising"  # untouched
