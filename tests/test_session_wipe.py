"""
Unit tests for session isolation functions in app.py and services/proximity.py.

Tests:
- _reset_session_state() — wipes ALL in-memory state on address change
- reset_session() — wipes proximity-specific state

Each test creates controlled mock state objects and verifies the wipe functions
behave correctly: clearing lists/dicts, resetting counters, handling missing
attributes gracefully, and leaving expected attributes intact.
"""

import time
import pytest
import logging

import app as _app_module
import services.proximity as _proximity_module

_reset_session_state = _app_module._reset_session_state
_reset_session = _proximity_module.reset_session


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

class MockState:
    """Replicates the services.state module interface with controlled data."""
    def __init__(self, with_optional=True):
        self.latest_snapshot = {"ts": 1000000, "worker": {"hashrate": 292e12}, "pool_hashrate": 1e15}
        self.timeline_state = {"all_time_best_diff_raw": 500e12, "session_share_count": 42}
        self.memory_critical_alerts = [
            {"ts": 1, "severity": "WARN", "category": "test", "message": "alert1"},
            {"ts": 2, "severity": "CRIT", "category": "test", "message": "alert2"},
        ]
        self.memory_share_buffer = [{"ts": 1, "diff": 10}, {"ts": 2, "diff": 20}]
        self.memory_live_log = ["line1", "line2", "line3"]
        self.last_known_prices = {"btc_usd": 65000.0, "btc_brl": 320000.0}
        self.event_counter = {"shares": 100, "blocks": 0}
        self.session_share_count = 42
        self.test_opportunities = {"opportunities": [{"id": "test"}]}

        # Optional attributes (may not exist in all environments)
        if with_optional:
            self.profit_cache = {"pool": 0.001, "solo": 0.0001}
            self.profit_cache_hit = 5
            self.consecutive_poll_failures = 2
            self.lm_share_counter = 150


class MockStateMinimal(MockState):
    """State WITHOUT the optional attributes — tests defensive wiping."""
    def __init__(self):
        super().__init__(with_optional=False)
        # Remove optional attrs
        for attr in ["profit_cache", "profit_cache_hit", "consecutive_poll_failures", "lm_share_counter"]:
            if hasattr(self, attr):
                delattr(self, attr)


# ═══════════════════════════════════════════════════════════════════════════════
#  _reset_session_state() tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestResetSessionState:
    """_reset_session_state() wipes ALL in-memory state for address isolation."""

    # ── Core state attributes ────────────────────────────────────────────────

    def test_clears_latest_snapshot(self, monkeypatch):
        """Should clear latest_snapshot and set a fresh timestamp."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)

        before = int(time.time())
        _reset_session_state()
        after = int(time.time())

        assert len(mock_state.latest_snapshot) == 1  # only "ts" key remains
        assert "ts" in mock_state.latest_snapshot
        assert before <= mock_state.latest_snapshot["ts"] <= after + 1, (
            f"ts={mock_state.latest_snapshot['ts']} not in [{before}, {after + 1}]"
        )

    def test_clears_memory_critical_alerts(self, monkeypatch):
        """Should clear the memory_critical_alerts list."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.memory_critical_alerts == []

    def test_clears_memory_share_buffer(self, monkeypatch):
        """Should clear the memory_share_buffer list."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.memory_share_buffer == []

    def test_clears_memory_live_log(self, monkeypatch):
        """Should clear the memory_live_log list."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.memory_live_log == []

    def test_clears_last_known_prices(self, monkeypatch):
        """Should clear the last_known_prices dict."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.last_known_prices == {}

    def test_clears_event_counter(self, monkeypatch):
        """Should clear the event_counter dict."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.event_counter == {}

    def test_clears_timeline_state(self, monkeypatch):
        """Should re-initialize timeline_state with full defaults."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        # timeline_state is re-initialized with all default keys
        expected_keys = {"_primed", "last_submit_ts", "last_best_diff_str",
                         "all_time_best_diff_raw", "share_submit_history",
                         "share_calc_history", "session_share_count",
                         "session_best_diff_bumps"}
        assert set(mock_state.timeline_state.keys()) == expected_keys
        assert mock_state.timeline_state["_primed"] is False
        assert mock_state.timeline_state["session_share_count"] == 0
        assert mock_state.timeline_state["all_time_best_diff_raw"] == 0.0

    def test_resets_session_share_count(self, monkeypatch):
        """Should reset session_share_count to 0."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.session_share_count == 0

    def test_clears_test_opportunities(self, monkeypatch):
        """Should set test_opportunities to None."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.test_opportunities is None

    # ── Optional attributes ──────────────────────────────────────────────────

    def test_clears_optional_profit_cache(self, monkeypatch):
        """Should clear profit_cache if it exists."""
        mock_state = MockState(with_optional=True)
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.profit_cache == {}

    def test_resets_optional_profit_cache_hit(self, monkeypatch):
        """Should reset profit_cache_hit to 0 if it exists."""
        mock_state = MockState(with_optional=True)
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.profit_cache_hit == 0

    def test_resets_optional_consecutive_failures(self, monkeypatch):
        """Should reset consecutive_poll_failures to 0 if it exists."""
        mock_state = MockState(with_optional=True)
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.consecutive_poll_failures == 0

    def test_resets_optional_lm_share_counter(self, monkeypatch):
        """Should reset lm_share_counter to 0 if it exists."""
        mock_state = MockState(with_optional=True)
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        _reset_session_state()
        assert mock_state.lm_share_counter == 0

    # ── Defensive: missing optional attributes should not crash ──────────────

    def test_no_crash_when_optional_missing(self, monkeypatch):
        """Should NOT crash when optional state attributes don't exist."""
        mock_state = MockStateMinimal()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        # Should not raise any exception
        _reset_session_state()
        # Core state should still be wiped
        assert mock_state.session_share_count == 0
        assert mock_state.latest_snapshot.get("ts") is not None

    def test_no_crash_when_latest_snapshot_is_none(self, monkeypatch):
        """Should handle latest_snapshot being None instead of dict."""
        mock_state = MockState()
        mock_state.latest_snapshot = None
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)
        # Should not crash
        _reset_session_state()
        assert mock_state.session_share_count == 0

    def test_no_crash_when_state_is_missing_attrs(self, monkeypatch):
        """Should handle state objects missing ALL expected attributes."""
        class AlmostEmptyState:
            pass

        empty_state = AlmostEmptyState()
        monkeypatch.setattr(_app_module, "state", empty_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", empty_state)
        # Should not crash — all wipe operations are defensive
        _reset_session_state()

    # ── Verify proximity.reset_session() was called ─────────────────────────

    def test_calls_proximity_reset(self, monkeypatch):
        """Should call proximity.reset_session() as part of the wipe."""
        mock_state = MockState()
        called = []

        class ProximityMock:
            @staticmethod
            def reset_session():
                called.append(True)

        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", ProximityMock)
        monkeypatch.setattr(_proximity_module, "state", mock_state)

        _reset_session_state()
        assert len(called) == 1, "proximity.reset_session() should be called once"

    def test_proximity_reset_error_does_not_propagate(self, monkeypatch):
        """Should NOT crash if proximity.reset_session() raises."""
        mock_state = MockState()

        class ProximityCrash:
            @staticmethod
            def reset_session():
                raise RuntimeError("proximity crashed")

        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", ProximityCrash)
        monkeypatch.setattr(_proximity_module, "state", mock_state)

        # Should not propagate the error
        _reset_session_state()
        # Core wipe should have completed
        assert mock_state.session_share_count == 0

    # ── _settings_cache is reset ────────────────────────────────────────────

    def test_resets_settings_cache(self, monkeypatch):
        """Should set _settings_cache to None."""
        mock_state = MockState()
        monkeypatch.setattr(_app_module, "state", mock_state)
        monkeypatch.setattr(_app_module, "proximity", _proximity_module)
        monkeypatch.setattr(_proximity_module, "state", mock_state)

        # Set a non-None value first
        _app_module._settings_cache = {"some": "cache"}
        _reset_session_state()
        assert _app_module._settings_cache is None


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
