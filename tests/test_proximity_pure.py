"""
CYPHER65 // Proximity meter — unit tests
========================================
Covers services/proximity.py (45% → target ≥80%):
  - _compute_rolling_avg_share_diffs: insufficient data, recent/old split,
    fallback half-split, rising/falling/flat/stable labels
  - _compute_quantum_lock: NO_DATA guard, density tiers, proximity tiers,
    power tiers, momentum tiers, STRONG/MODERATE/WEAK/TRACKING status
  - reset_session: clears all_time_best_diff (with/without timeline_state)
  - _update_all_time_best_diff: peak bump, persistence, no-op
  - _restore_all_time_best_diff / _nearest_history_before / _sample_proximity
    with mocked get_db
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock

import services.state as state
from services import proximity as prox
from services.proximity import (
    _compute_rolling_avg_share_diffs, _compute_quantum_lock,
    reset_session, _update_all_time_best_diff,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. _compute_rolling_avg_share_diffs
# ═══════════════════════════════════════════════════════════════════════════

class TestRollingAvg:
    def test_empty_history(self):
        r = _compute_rolling_avg_share_diffs([], 1_000_000)
        assert r["trend_label"] == "insufficient"
        assert r["recent_avg_raw"] is None

    def test_single_entry(self):
        r = _compute_rolling_avg_share_diffs([{"ts": 100, "share_diff_raw": 5}], 200)
        assert r["trend_label"] == "insufficient"

    def test_all_recent_no_old(self):
        # Both shares inside window → recent avg computed, no old → insufficient label
        sch = [{"ts": 480, "share_diff_raw": 10},
               {"ts": 490, "share_diff_raw": 20}]
        r = _compute_rolling_avg_share_diffs(sch, 500, window_seconds=60)
        assert r["recent_count"] == 2
        assert r["recent_avg_raw"] == 15
        assert r["trend_label"] == "insufficient"  # no old window

    def test_recent_vs_old_rising(self):
        now = 1_000_000
        # cutoff = now - 3600 = 996400; old ts must be < 996400
        sch = [
            {"ts": now - 10000, "share_diff_raw": 10},  # old
            {"ts": now - 5000, "share_diff_raw": 10},   # old
            {"ts": now - 2000, "share_diff_raw": 30},   # recent
            {"ts": now - 1000, "share_diff_raw": 30},   # recent
        ]
        r = _compute_rolling_avg_share_diffs(sch, now, window_seconds=3600)
        assert r["recent_avg_raw"] == 30
        assert r["old_avg_raw"] == 10
        assert r["trend_pct"] == pytest.approx(200.0)
        assert r["trend_label"] == "rising"

    def test_falling(self):
        now = 1_000_000
        sch = [
            {"ts": now - 10000, "share_diff_raw": 100},
            {"ts": now - 5000, "share_diff_raw": 100},
            {"ts": now - 2000, "share_diff_raw": 10},
            {"ts": now - 1000, "share_diff_raw": 10},
        ]
        r = _compute_rolling_avg_share_diffs(sch, now, window_seconds=3600)
        assert r["trend_label"] == "falling"

    def test_flat_and_stable_labels(self):
        now = 1_000_000
        # exactly equal → flat (trend_pct == 0, abs < 1)
        sch = [{"ts": now - 10000, "share_diff_raw": 50},
               {"ts": now - 5000, "share_diff_raw": 50},
               {"ts": now - 2000, "share_diff_raw": 50},
               {"ts": now - 1000, "share_diff_raw": 50}]
        r = _compute_rolling_avg_share_diffs(sch, now, window_seconds=3600)
        assert r["trend_label"] == "flat"

        # 3% change → stable
        sch2 = [{"ts": now - 10000, "share_diff_raw": 100},
                {"ts": now - 5000, "share_diff_raw": 100},
                {"ts": now - 2000, "share_diff_raw": 103},
                {"ts": now - 1000, "share_diff_raw": 103}]
        r2 = _compute_rolling_avg_share_diffs(sch2, now, window_seconds=3600)
        assert r2["trend_label"] == "stable"

    def test_fallback_half_split_when_recent_too_short(self):
        now = 1_000_000
        # cutoff = 996400; only ONE share in recent window → fallback half-split
        sch = [
            {"ts": now - 10000, "share_diff_raw": 10},
            {"ts": now - 5000, "share_diff_raw": 20},
            {"ts": now - 1000, "share_diff_raw": 30},
        ]
        r = _compute_rolling_avg_share_diffs(sch, now, window_seconds=3600)
        # mid = 1, recent = last 1, old = first 1 → both avg available
        assert r["old_avg_raw"] is not None
        assert r["recent_avg_raw"] is not None

    def test_zero_old_avg_skips_trend(self):
        now = 1_000_000
        sch = [
            {"ts": now - 10000, "share_diff_raw": 0},
            {"ts": now - 2000, "share_diff_raw": 30},
            {"ts": now - 1000, "share_diff_raw": 30},
        ]
        r = _compute_rolling_avg_share_diffs(sch, now, window_seconds=3600)
        assert r["trend_label"] == "insufficient"  # old_avg=0 → no trend


# ═══════════════════════════════════════════════════════════════════════════
# 2. _compute_quantum_lock
# ═══════════════════════════════════════════════════════════════════════════

class TestQuantumLock:
    def test_no_data_guard(self):
        lock = _compute_quantum_lock(0, None, None, [], 0, 0, 0)
        assert lock["status"] == "NO_DATA"
        assert lock["score"] == 0

    def test_insufficient_session_shares(self):
        lock = _compute_quantum_lock(0.5, 1e12, 100e12, [], 0, 5, 1e12)
        assert lock["status"] == "NO_DATA"

    def test_strong_lock(self):
        # high density, high proximity, high power, rising momentum
        sch = [{"share_diff_raw": 90e12} for _ in range(150)]
        lock = _compute_quantum_lock(
            pct_cur=1.5, best_diff_raw=100e12, net_diff=100e12,
            sch=sch, session_shares=200, trend_pct=20, worker_hps=1e12)
        assert lock["status"] == "STRONG_LOCK"
        assert lock["confidence"] == "HIGH"
        assert lock["score"] >= 75

    def test_moderate_lock(self):
        sch = [{"share_diff_raw": 40e12} for _ in range(120)]
        lock = _compute_quantum_lock(
            pct_cur=0.15, best_diff_raw=100e12, net_diff=100e12,
            sch=sch, session_shares=150, trend_pct=3, worker_hps=1e12)
        assert lock["status"] == "MODERATE_LOCK"
        assert 50 <= lock["score"] < 75

    def test_weak_lock(self):
        sch = [{"share_diff_raw": 5e12} for _ in range(8)]
        # pct >= 0.01 → prox=15; density=10 (>=5 shares); power=5 (ratio 0.05);
        # momentum=1 (falling) → total 31 → WEAK_LOCK (25 <= 31 < 50)
        lock = _compute_quantum_lock(
            pct_cur=0.015, best_diff_raw=100e12, net_diff=100e12,
            sch=sch, session_shares=10, trend_pct=-5, worker_hps=1e12)
        assert lock["status"] == "WEAK_LOCK"
        assert 25 <= lock["score"] < 50

    def test_tracking_status(self):
        sch = [{"share_diff_raw": 0.5e12} for _ in range(6)]
        lock = _compute_quantum_lock(
            pct_cur=0.0005, best_diff_raw=100e12, net_diff=100e12,
            sch=sch, session_shares=6, trend_pct=-5, worker_hps=1e12)
        assert lock["status"] == "TRACKING"
        assert lock["confidence"] == "VERY_LOW"

    def test_power_ratio_tiers(self):
        # power_ratio < 0.01 → 2 points
        sch = [{"share_diff_raw": 1e9}]
        lock = _compute_quantum_lock(
            0.05, best_diff_raw=100e12, net_diff=100e12,
            sch=sch, session_shares=5, trend_pct=0.5, worker_hps=1e12)
        assert lock["components"]["power"] == 2

    def test_momentum_stable(self):
        sch = [{"share_diff_raw": 10e12}]
        # trend_pct == 0 → not > 0, and abs(0) < 1 → stable = 5
        lock = _compute_quantum_lock(
            0.05, best_diff_raw=100e12, net_diff=100e12,
            sch=sch, session_shares=5, trend_pct=0, worker_hps=1e12)
        assert lock["components"]["momentum"] == 5

    def test_momentum_positive_small(self):
        sch = [{"share_diff_raw": 10e12}]
        # 0 < trend < 5 → momentum = 3
        lock = _compute_quantum_lock(
            0.05, best_diff_raw=100e12, net_diff=100e12,
            sch=sch, session_shares=5, trend_pct=2, worker_hps=1e12)
        assert lock["components"]["momentum"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# 3. reset_session + all-time best diff
# ═══════════════════════════════════════════════════════════════════════════

class TestResetAndPeak:
    def test_reset_clears_best_diff(self):
        state.timeline_state["all_time_best_diff_raw"] = 42.0
        reset_session()
        assert state.timeline_state["all_time_best_diff_raw"] == 0.0

    def test_reset_without_timeline_state(self, monkeypatch):
        monkeypatch.setattr(state, "timeline_state", None)
        reset_session()  # must not raise

    def test_update_peak_bumps_and_persists(self, monkeypatch):
        state.timeline_state["all_time_best_diff_raw"] = 10.0
        persisted = []
        monkeypatch.setattr(prox, "_persist_all_time_best_diff",
                            lambda v: persisted.append(v))
        result = _update_all_time_best_diff(25.0)
        assert result == 25.0
        assert persisted == [25.0]
        assert state.timeline_state["all_time_best_diff_raw"] == 25.0

    def test_update_peak_no_bump(self, monkeypatch):
        state.timeline_state["all_time_best_diff_raw"] = 10.0
        monkeypatch.setattr(prox, "_persist_all_time_best_diff", lambda v: None)
        result = _update_all_time_best_diff(5.0)
        assert result == 10.0

    def test_update_peak_invalid_input(self):
        state.timeline_state["all_time_best_diff_raw"] = 7.0
        assert _update_all_time_best_diff(None) == 7.0
        assert _update_all_time_best_diff(-3) == 7.0


# ═══════════════════════════════════════════════════════════════════════════
# 4. DB-backed helpers (mocked get_db)
# ═══════════════════════════════════════════════════════════════════════════

class _Row(dict):
    """sqlite3.Row-like dict for mocks."""

    def __getitem__(self, key):
        return dict.__getitem__(self, key)


class TestDbHelpers:
    def test_restore_all_time_best_diff(self):
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value = _Row({"value": "55.5"})
        prox._get_db = lambda: conn
        state.timeline_state["all_time_best_diff_raw"] = 0.0
        prox._restore_all_time_best_diff()
        assert state.timeline_state["all_time_best_diff_raw"] == 55.5

    def test_restore_empty_value_keeps_zero(self):
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value = _Row({"value": ""})
        prox._get_db = lambda: conn
        state.timeline_state["all_time_best_diff_raw"] = 0.0
        prox._restore_all_time_best_diff()
        assert state.timeline_state["all_time_best_diff_raw"] == 0.0

    def test_restore_db_error_swallowed(self):
        def boom():
            raise RuntimeError("db down")
        prox._get_db = boom
        prox._restore_all_time_best_diff()  # must not raise

    def test_nearest_history_before(self):
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value = \
            _Row({"best_diff": 42.0, "network_difficulty": 100.0})
        prox._get_db = lambda: conn
        result = prox._nearest_history_before(12345)
        assert result == (42.0, 100.0)

    def test_nearest_history_none(self):
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value = None
        prox._get_db = lambda: conn
        assert prox._nearest_history_before(12345) is None

    def test_nearest_history_error(self):
        def boom():
            raise RuntimeError("db down")
        prox._get_db = boom
        assert prox._nearest_history_before(12345) is None

    def test_sample_proximity_throttled(self):
        prox._last_proximity_sample_ts = 1_000_000
        prox._sample_proximity(1_000_010, 5.0, 100.0, 1e12, True)
        # throttle window is 60s — 10s later means no insert
        prox._get_db = None
        # no exception raised and last ts unchanged
        assert prox._last_proximity_sample_ts == 1_000_000

    def test_sample_proximity_inserts(self):
        conn = MagicMock()
        prox._get_db = lambda: conn
        prox._last_proximity_sample_ts = 1_000_000
        prox._sample_proximity(1_001_000, 5.0, 100.0, 1e12, False)
        assert prox._last_proximity_sample_ts == 1_001_000
        # pct = 5/100*100 = 5.0
        args = conn.cursor.return_value.execute.call_args[0][1]
        assert args[7] == 0  # hot_streak=0

    def test_sample_proximity_hot_streak_flag(self):
        conn = MagicMock()
        prox._get_db = lambda: conn
        prox._last_proximity_sample_ts = 1_000_000
        prox._sample_proximity(1_001_000, 5.0, 100.0, 1e12, True)
        args = conn.cursor.return_value.execute.call_args[0][1]
        assert args[7] == 1

    def test_sample_proximity_error_swallowed(self):
        def boom():
            raise RuntimeError("db down")
        prox._get_db = boom
        prox._last_proximity_sample_ts = 1_000_000
        prox._sample_proximity(1_001_000, 5.0, 100.0, 1e12, False)
        # must not raise
