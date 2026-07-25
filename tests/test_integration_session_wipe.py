"""
Integration test for session isolation via /api/set-address.

Tests the COMPLETE wipe chain:
  1. Populate shared state with simulated active session data
  2. Call POST /api/set-address with a NEW address
  3. Verify via /api/snapshot (HTTP) + direct module state inspection
     that every memory attribute was wiped/reset
  4. Verify that BTC_ADDRESS global was updated

Strategy:
  - Uses Flask test_client() like test_opportunity_engine.py
  - Monkeypatches save_setting and _log_wallet_change to skip DB writes
  - Monkeypatches polling.poll_once to skip live fetch
  - Populates state.latest_snapshot + peripherals with rich mock data
    that simulates an active mining session
  - Verifies each attribute individually after the wipe
  - Handles the fact that some wipe targets (memory_share_buffer,
    memory_live_log, event_counter, profit_cache) don't exist in the
    real state.py module — the production code's _safe_wipe uses
    try/except so missing attrs are silently skipped
"""

import json
import time
import pytest

import app as _app_module
import services.state as _state_module
import services.polling as _polling_module


@pytest.fixture
def client():
    """Return a Flask test client."""
    _app_module.app.testing = True
    return _app_module.app.test_client()


# ══════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════

def _populate_rich_session_state():
    """Fill shared memory state with data that simulates an active
    mining session — all of which must be wiped on address change.

    Only sets attributes that actually exist in services/state.py.
    Attributes that DON'T exist in state.py (memory_share_buffer,
    memory_live_log, event_counter, profit_cache, etc.) are created
    so the test can verify their removal — the production _safe_wipe
    gracefully handles missing attrs via try/except.
    """
    snap = _state_module.latest_snapshot
    snap.clear()
    snap.update({
        "ts": int(time.time()) - 300,  # 5 min ago
        "worker": {
            "hashrate": 292e12,
            "bestDifficulty": "170 G",
            "status": "hashing",
            "lastSubmission": int(time.time()) - 10,
        },
        "network": {
            "difficulty": 127e12,
            "hashrate": 600e18,
            "height": 876543,
        },
        "pool_hashrate": 350e12,
        "pool_workers": 42,
        "btc_usd": 65000.0,
        "btc_brl": 320000.0,
        "address": "bc1qoldsessionxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "all_workers": [
            {"name": "worker1", "hashrate": 150e12, "status": "hashing"},
            {"name": "worker2", "hashrate": 142e12, "status": "hashing"},
        ],
        "proximity": {
            "chance_per_share": 1.8e-20,
            "distance_factor": 0.003,
            "expected_time_days": 4500,
            "trend_1h": "stable",
        },
        "profitability": {
            "pool": {"daily_btc": 0.00005, "weekly_btc": 0.00035},
            "solo": {"daily_btc": 0.000001, "weekly_btc": 0.000007},
            "rental": {"daily_btc": -0.0001, "weekly_btc": -0.0007},
        },
        "milestones": [
            {"label": "First Share", "ts": int(time.time()) - 86400},
            {"label": "Best Diff > 100G", "ts": int(time.time()) - 43200},
        ],
        "leaderboard_table_top_30": [
            {"address": "bc1qother1", "score": 100},
            {"address": "bc1qother2", "score": 50},
        ],
        "event_stats": {"shares": 150, "blocks": 0, "best_diff_bumps": 3},
    })

    # memory_critical_alerts — exists in state.py
    _state_module.memory_critical_alerts.clear()
    _state_module.memory_critical_alerts.extend([
        {"ts": 1, "severity": "WARN", "category": "network", "message": "diff spike"},
        {"ts": 2, "severity": "CRIT", "category": "share", "message": "stale share"},
    ])

    # last_known_prices — exists in state.py
    _state_module.last_known_prices.clear()
    _state_module.last_known_prices.update({
        "braiins": {"price": 0.000123, "ts": int(time.time()) - 60, "label": "123 sats/PH/day"},
        "mrr": {"price": 0.000100, "ts": int(time.time()) - 120, "label": "100 sats/PH/day"},
    })

    # timeline_state — exists in state.py
    _state_module.timeline_state.clear()
    _state_module.timeline_state.update({
        "_primed": True,
        "last_submit_ts": int(time.time()) - 10,
        "last_best_diff_str": "170 G",
        "all_time_best_diff_raw": 170e9,
        "session_share_count": 150,
        "session_best_diff_bumps": 3,
    })

    # test_opportunities — exists in state.py
    _state_module.test_opportunities = {
        "opportunities": [{"id": "braiins_0.001", "platform": "braiins"}],
    }

    # Cache — exists in state.py
    _state_module.btc_price_cache = {"ts": int(time.time()) - 60, "data": {"usd": 65000.0}}

    # ── Attributes that DON'T exist in state.py but are wipe targets ──
    # The production _safe_wipe handles missing attrs via try/except,
    # so these won't crash the wipe. But the test creates them so we
    # can verify the wipe runs through without issues *and* removes
    # them if they happen to be present.

    # memory_share_buffer — not in state.py, but _safe_wipe handles it
    _state_module.memory_share_buffer = [
        {"ts": int(time.time()) - 60, "diff": 150e9, "worker": "worker1"},
        {"ts": int(time.time()) - 120, "diff": 120e9, "worker": "worker2"},
        {"ts": int(time.time()) - 180, "diff": 100e9, "worker": "worker1"},
    ]
    # memory_live_log — not in state.py
    _state_module.memory_live_log = [
        "[10:00:00] Share found — diff 150G",
        "[09:59:45] Share found — diff 120G",
        "[09:59:30] Best diff bumped to 170G",
    ]
    # event_counter — not in state.py
    _state_module.event_counter = {"shares": 150, "blocks": 0}
    # profit_cache — not in state.py
    _state_module.profit_cache = {"pool": {"daily_btc": 0.00005}, "solo": {"daily_btc": 0.000001}}
    # profit_cache_hit — not in state.py
    _state_module.profit_cache_hit = 12
    # consecutive_poll_failures — not in state.py (but persist_consec_failures is!)
    _state_module.consecutive_poll_failures = 2
    # lm_share_counter — not in state.py
    _state_module.lm_share_counter = 150


# ══════════════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════════════

NEW_ADDRESS = "bc1qnewaddressafterwipe123456789abcdefghijk"


class TestIntegrationSessionWipe:
    """Integration test: POST /api/set-address → complete session wipe."""

    # ── Per-test setup ────────────────────────────────────────────────

    def _setup(self, monkeypatch):
        """Common setup: populate state + mock DB/network calls."""
        _populate_rich_session_state()

        # Mock save_setting to skip DB writes
        monkeypatch.setattr(_app_module, "save_setting", lambda k, v: True)
        # Mock _log_wallet_change to skip DB writes
        monkeypatch.setattr(_app_module, "_log_wallet_change", lambda *a, **kw: None)
        # Mock polling.poll_once to skip live network fetch
        monkeypatch.setattr(_polling_module, "poll_once", lambda: None)
        # Mock polling.config to prevent AttributeError on BTC_ADDRESS
        class MockPollConfig:
            BTC_ADDRESS = ""
        monkeypatch.setattr(_app_module.polling, "config", MockPollConfig())

        self._orig_addr = _app_module.BTC_ADDRESS

    def _teardown(self):
        """Restore original BTC_ADDRESS."""
        _app_module.BTC_ADDRESS = getattr(self, "_orig_addr", "")

    # ── Test 1: /api/snapshot returns only ts after wipe ──────────────

    def test_snapshot_returns_only_ts_after_wipe(self, monkeypatch, client):
        """After set-address, GET /api/snapshot should return only timestamp."""
        self._setup(monkeypatch)
        try:
            resp = client.post("/api/set-address", json={"address": NEW_ADDRESS})
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

            snap_resp = client.get("/api/snapshot")
            assert snap_resp.status_code == 200
            snap_data = json.loads(snap_resp.data)

            assert "ts" in snap_data, "Snapshot must contain 'ts' key after wipe"
            assert isinstance(snap_data["ts"], int)
            assert len(snap_data) == 1, (
                f"Snapshot should have exactly 1 key ('ts'), got {len(snap_data)} keys: "
                f"{list(snap_data.keys())}"
            )
        finally:
            self._teardown()

    # ── Test 2: memory_critical_alerts cleared ────────────────────────

    def test_memory_critical_alerts_cleared(self, monkeypatch, client):
        """memory_critical_alerts should be wiped, then a single SUCCESS
        alert is added by the set-address handler itself."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            alerts = _state_module.memory_critical_alerts
            # The wipe clears all alerts, then the endpoint adds 1 SUCCESS
            assert len(alerts) == 1, (
                f"Expected 1 alert (wipe-clear + post-add), got {len(alerts)}: {alerts}"
            )
            assert alerts[0]["severity"] == "SUCCESS", (
                f"Alert should be SUCCESS, got {alerts[0].get('severity')}"
            )
            assert alerts[0]["category"] == "wallet_changed", (
                f"Alert should be wallet_changed, got {alerts[0].get('category')}"
            )
        finally:
            self._teardown()

    # ── Test 3: last_known_prices cleared ────────────────────────────

    def test_last_known_prices_cleared(self, monkeypatch, client):
        """last_known_prices should be empty dict after wipe."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            assert _state_module.last_known_prices == {}, (
                "last_known_prices should be cleared after wipe"
            )
        finally:
            self._teardown()

    # ── Test 4: timeline_state cleared and reinit key set ────────────

    def test_timeline_state_cleared_except_reinit(self, monkeypatch, client):
        """timeline_state should be re-initialized with all default keys."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})

            ts = _state_module.timeline_state
            # timeline_state is now re-initialized with full defaults
            expected_keys = {"_primed", "last_submit_ts", "last_best_diff_str",
                             "all_time_best_diff_raw", "share_submit_history",
                             "share_calc_history", "session_share_count",
                             "session_best_diff_bumps"}
            assert set(ts.keys()) == expected_keys, (
                f"expected {expected_keys}, got {set(ts.keys())}"
            )
            assert ts["_primed"] is False
            assert ts["session_share_count"] == 0
            assert ts["all_time_best_diff_raw"] == 0.0
        finally:
            self._teardown()

    # ── Test 5: test_opportunities set to None ───────────────────────

    def test_test_opportunities_set_to_none(self, monkeypatch, client):
        """test_opportunities should be None after wipe."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            assert _state_module.test_opportunities is None, (
                "test_opportunities should be None after wipe"
            )
        finally:
            self._teardown()

    # ── Test 6: response body confirms address change ────────────────

    def test_response_confirms_new_address(self, monkeypatch, client):
        """Response JSON should contain ok=True and the new address."""
        self._setup(monkeypatch)
        try:
            resp = client.post("/api/set-address", json={"address": NEW_ADDRESS})
            data = json.loads(resp.data)
            assert data.get("ok") is True, "Response should have ok: true"
            assert data.get("address") == NEW_ADDRESS, (
                f"Response address should be {NEW_ADDRESS}, got {data.get('address')}"
            )
        finally:
            self._teardown()

    # ── Test 7: BTC_ADDRESS global updated ───────────────────────────

    def test_btc_address_global_updated(self, monkeypatch, client):
        """BTC_ADDRESS global should reflect the new address."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            assert _app_module.BTC_ADDRESS == NEW_ADDRESS, (
                f"BTC_ADDRESS should be {NEW_ADDRESS}, got {_app_module.BTC_ADDRESS}"
            )
        finally:
            self._teardown()

    # ── Test 8: WALLET_ADDRESS_SOURCE set to 'ui' ────────────────────

    def test_source_set_to_ui(self, monkeypatch, client):
        """WALLET_ADDRESS_SOURCE should be 'ui' after manual address change."""
        self._setup(monkeypatch)
        try:
            _app_module.WALLET_ADDRESS_SOURCE = "db"
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            assert _app_module.WALLET_ADDRESS_SOURCE == "ui", (
                f"Source should be 'ui', got {_app_module.WALLET_ADDRESS_SOURCE}"
            )
        finally:
            self._teardown()

    # ── Test 9: ts is updated to fresh value ─────────────────────────

    def test_ts_is_fresh_on_wipe(self, monkeypatch, client):
        """The ts in latest_snapshot should be a fresh timestamp (not the old one)."""
        self._setup(monkeypatch)
        try:
            before = int(time.time())
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            after = int(time.time())

            ts = _state_module.latest_snapshot.get("ts", 0)
            assert before <= ts <= after + 1, (
                f"Snapshot ts ({ts}) should be current time [{before}, {after}]"
            )
        finally:
            self._teardown()

    # ── Test 10: invalid address is rejected (no wipe) ───────────────

    def test_invalid_address_rejected_no_wipe(self, monkeypatch, client):
        """Address < 10 chars should return 400 and NOT wipe state."""
        self._setup(monkeypatch)
        try:
            # Set a marker BEFORE the attempted wipe
            _state_module.test_opportunities = {"keep": "this"}
            resp = client.post("/api/set-address", json={"address": "short"})
            assert resp.status_code == 400, (
                f"Expected 400 for short address, got {resp.status_code}"
            )
            # State should NOT have been wiped
            assert _state_module.test_opportunities == {"keep": "this"}, (
                "State should NOT be wiped on invalid address"
            )
        finally:
            self._teardown()

    # ── Test 11: empty address rejected ──────────────────────────────

    def test_empty_address_rejected(self, monkeypatch, client):
        """Empty or missing address should return 400."""
        self._setup(monkeypatch)
        try:
            resp = client.post("/api/set-address", json={"address": ""})
            assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
            resp2 = client.post("/api/set-address", json={})
            assert resp2.status_code == 400, f"Expected 400, got {resp2.status_code}"
        finally:
            self._teardown()

    # ── Test 12: old worker data removed from snapshot ───────────────

    def test_old_worker_data_gone(self, monkeypatch, client):
        """Worker/network/milestone data from previous session should be gone."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            snap = _state_module.latest_snapshot
            assert "worker" not in snap, "Worker should not be in snapshot after wipe"
            assert "network" not in snap, "Network should not be in snapshot after wipe"
            assert "all_workers" not in snap, (
                "All workers should not be in snapshot after wipe"
            )
            assert "profitability" not in snap, (
                "Profitability should not be in snapshot after wipe"
            )
            assert "milestones" not in snap, (
                "Milestones should not be in snapshot after wipe"
            )
            assert "proximity" not in snap, (
                "Proximity should not be in snapshot after wipe"
            )
        finally:
            self._teardown()

    # ── Test 13: optional wipe targets don't crash if missing ────────

    def test_optional_wipable_attrs_dont_crash(self, monkeypatch, client):
        """Attributes that _reset_session_state tries to wipe but
        DON'T exist in state.py (memory_share_buffer, memory_live_log,
        event_counter, profit_cache, etc.) should not cause crashes.

        Run the wipe and verify the state is still correctly wiped on
        the attributes that DO matter.
        """
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})

            # Core wipe should have completed despite missing attrs
            assert len(_state_module.latest_snapshot) == 1, (
                "Snapshot should only have 'ts' after wipe"
            )
            assert "ts" in _state_module.latest_snapshot
            # Alerts: wiped then 1 success alert added by endpoint
            assert len(_state_module.memory_critical_alerts) == 1, (
                "Wipe clears alerts, then endpoint adds 1 SUCCESS"
            )
            assert _state_module.memory_critical_alerts[0]["severity"] == "SUCCESS"
            assert _state_module.last_known_prices == {}, (
                "last_known_prices should be cleared after wipe"
            )
            assert _state_module.test_opportunities is None, (
                "test_opportunities should be None after wipe"
            )

            # Optional attrs that were set should be cleared (not crash on _safe_wipe)
            assert _state_module.memory_share_buffer == [], (
                "memory_share_buffer should be cleared after wipe"
            )
            assert _state_module.event_counter == {}, (
                "event_counter should be cleared after wipe"
            )
        finally:
            self._teardown()
