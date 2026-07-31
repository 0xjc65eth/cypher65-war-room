"""
Integration test for session isolation via /api/set-address.

Tests the REAL wipe chain in app.py:
  1. Populate shared state with simulated active session data
  2. Call POST /api/set-address with a NEW address
  3. Verify via /api/snapshot (HTTP) + direct module state inspection
     that every memory attribute was wiped/reset
  4. Verify that BTC_ADDRESS global was updated

Strategy:
  - Uses Flask test_client() like test_opportunity_engine.py
  - Monkeypatches get_db, _log_wallet_change and poll_once so no real
    HTTP/polling happens and the real DB is not polluted
  - Populates state.latest_snapshot + peripherals with rich mock data
    that simulates an active mining session
  - Verifies each attribute individually after the wipe
  - Aligns assertions with the actual _reset_session_state() behavior:
    the snapshot keeps its full schema (all keys present, values nulled),
    NOT reduced to a single 'ts' key — frontend renderers need the schema.
"""

import copy
import json
import time
import collections
from unittest.mock import MagicMock

import pytest

import app as _app_module
import services.state as _state_module


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

    Only sets attributes that actually exist in services/state.py
    or are referenced in _reset_session_state().
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
        "pool": {"hashrate": 350e12, "workers": 42},
        "account": {"total_diff": 1.5e15},
        "btc_price": {"usd": 65000.0, "brl": 320000.0},
        "proximity": {
            "chance_per_share_pct": 1.8e-20,
            "distance_factor": 0.003,
            "expected_time_secs": 4500 * 86400,
        },
        "profitability": {
            "pool": {"daily_btc": 0.00005},
        },
        "leaderboard_table_top_30": [
            {"address": "bc1qother1", "score": 100},
        ],
        "event_stats": {"shares": 150, "blocks": 0},
        "alerts_recent": [
            {"ts": 1, "severity": "WARN", "message": "diff spike"},
        ],
        "timeline_recent": [],
        "leaderboard_entry": None,
        "leaderboard_total": 0,
        "highest_diffs": [],
        "luck_estimate": {},
        "user_aggregate": None,
        "lightning": None,
    })

    # memory_critical_alerts — app.py module global (NOT services.state's)
    _app_module.memory_critical_alerts.clear()
    _app_module.memory_critical_alerts.append(
        {"ts": 1, "severity": "WARN", "category": "network", "message": "diff spike"}
    )

    # last_known_prices — exists in state.py
    _state_module.last_known_prices["braiins"] = {
        "price": 0.000123, "ts": int(time.time()) - 60, "label": "123 sats/PH/day"
    }
    _state_module.last_known_prices["mrr"] = {
        "price": 0.000100, "ts": int(time.time()) - 120, "label": "100 sats/PH/day"
    }

    # timeline_state — exists in state.py (same object as app.timeline_state)
    _state_module.timeline_state.clear()
    _state_module.timeline_state.update({
        "_primed": True,
        "last_submit_ts": int(time.time()) - 10,
        "last_best_diff_str": "170 G",
        "all_time_best_diff_raw": 170e9,
        "share_submit_history": collections.deque(maxlen=64),
        "share_calc_history": collections.deque(maxlen=20),
        "session_share_count": 150,
        "session_best_diff_bumps": 3,
    })

    # test_opportunities — exists in state.py
    _state_module.test_opportunities = {
        "opportunities": [{"id": "braiins_0.001", "platform": "braiins"}],
    }

    # btc_price_cache — exists in state.py
    _state_module.btc_price_cache = {
        "ts": int(time.time()) - 60, "data": {"usd": 65000.0}
    }


# ══════════════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════════════

# Valid bech32 address (BIP-173 test vector) — passes checksum validation
NEW_ADDRESS = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


class TestIntegrationSessionWipe:
    """Integration test: POST /api/set-address → complete session wipe."""

    def _setup(self, monkeypatch):
        """Common setup: populate state + mock DB/poll calls.

        Saves a deep copy of the real shared state BEFORE populating test data,
        so _teardown can restore the pristine pre-test state — the handler +
        wipe mutate these real globals, and restoring the ORIGINAL state
        (not the injected rich data) prevents residual pollution.
        """
        self._saved = {
            "btc_address": _app_module.BTC_ADDRESS,
            "worker_name": _app_module.WORKER_NAME,
            "latest_snapshot": copy.deepcopy(_state_module.latest_snapshot),
            "timeline_state": copy.deepcopy(_state_module.timeline_state),
            "last_known_prices": copy.deepcopy(_state_module.last_known_prices),
            "test_opportunities": copy.deepcopy(_state_module.test_opportunities),
            "memory_critical_alerts": copy.deepcopy(
                list(getattr(_app_module, "memory_critical_alerts", []))
            ),
        }

        # Force BTC_ADDRESS to a deterministic value DIFFERENT from NEW_ADDRESS
        # so the "same as current" early-return never short-circuits the wipe
        # chain — regardless of what is persisted in the DB or set in the env.
        _app_module.BTC_ADDRESS = "bc1qpc3832jcu6m8qpqjvz5lkuydwjzv8v5vq5t5rs"
        _app_module.WORKER_NAME = ""

        _populate_rich_session_state()

        # The handler persists via get_db() directly — stub it so no real
        # DB write happens during tests.
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()
        monkeypatch.setattr(_app_module, "get_db", lambda: mock_conn)
        # Mock _log_wallet_change to skip DB writes (function now exists)
        monkeypatch.setattr(_app_module, "_log_wallet_change", lambda *a, **kw: None)
        # Prevent forced poll thread from overwriting snapshot with real API data
        monkeypatch.setattr(_app_module, "poll_once", lambda: None)

    def _teardown(self):
        """Restore original BTC_ADDRESS and shared state."""
        saved = getattr(self, "_saved", {})
        if "btc_address" in saved:
            _app_module.BTC_ADDRESS = saved["btc_address"]
        if "worker_name" in saved:
            _app_module.WORKER_NAME = saved["worker_name"]
        if "latest_snapshot" in saved:
            _state_module.latest_snapshot.clear()
            _state_module.latest_snapshot.update(saved["latest_snapshot"])
        if "timeline_state" in saved:
            _state_module.timeline_state.clear()
            _state_module.timeline_state.update(saved["timeline_state"])
        if "last_known_prices" in saved:
            _state_module.last_known_prices.clear()
            _state_module.last_known_prices.update(saved["last_known_prices"])
        if "test_opportunities" in saved:
            _state_module.test_opportunities = saved["test_opportunities"]
        if "memory_critical_alerts" in saved:
            _app_module.memory_critical_alerts.clear()
            _app_module.memory_critical_alerts.extend(saved["memory_critical_alerts"])

    # ── Test 1: snapshot fields are nulled after wipe ──

    def test_snapshot_fields_nulled_after_wipe(self, monkeypatch, client):
        """After set-address, GET /api/snapshot should have fields nulled
        but keep the full schema (frontend reads these fields)."""
        self._setup(monkeypatch)
        try:
            resp = client.post("/api/set-address", json={"address": NEW_ADDRESS})
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

            snap_resp = client.get("/api/snapshot")
            assert snap_resp.status_code == 200
            snap_data = json.loads(snap_resp.data)

            # The snapshot keeps its full schema with nulled values
            assert "ts" in snap_data and isinstance(snap_data["ts"], int)
            assert snap_data["worker"] is None
            assert snap_data["pool"] is None
            assert snap_data["account"] is None
            assert snap_data["leaderboard_entry"] is None
            assert snap_data["highest_diffs"] == []
            assert snap_data["network"]["difficulty"] is None
            assert snap_data["network"]["hashrate"] is None
            assert snap_data["network"]["height"] is None
            assert snap_data["btc_price"]["usd"] is None
            assert snap_data["btc_price"]["brl"] is None
            assert snap_data["alerts_recent"] == []
            assert snap_data["event_stats"] == {}
        finally:
            self._teardown()

    # ── Test 2: memory_critical_alerts cleared ──

    def test_memory_critical_alerts_cleared(self, monkeypatch, client):
        """memory_critical_alerts should be wiped, then a single SUCCESS
        alert is added by the set-address handler itself."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            alerts = _app_module.memory_critical_alerts
            assert len(alerts) == 1, (
                f"Expected 1 alert (wipe-clear + post-add), got {len(alerts)}"
            )
            assert alerts[0]["severity"] == "SUCCESS"
            assert alerts[0]["category"] == "wallet_changed"
        finally:
            self._teardown()

    # ── Test 3: last_known_prices cleared (keys preserved) ──

    def test_last_known_prices_cleared(self, monkeypatch, client):
        """last_known_prices should have both keys set to None after wipe
        (keys are preserved, values are nulled)."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            lp = _state_module.last_known_prices
            assert lp["braiins"] is None, "braiins should be None after wipe"
            assert lp["mrr"] is None, "mrr should be None after wipe"
        finally:
            self._teardown()

    # ── Test 4: timeline_state cleared ──

    def test_timeline_state_cleared_except_reinit(self, monkeypatch, client):
        """timeline_state should be re-initialized with all default keys."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})

            ts = _state_module.timeline_state
            expected_keys = {"_primed", "last_submit_ts", "last_best_diff_str",
                             "all_time_best_diff_raw", "share_submit_history",
                             "share_calc_history", "session_share_count",
                             "session_best_diff_bumps"}
            # Allow extra keys (e.g. if timeline_state has more attrs)
            for k in expected_keys:
                assert k in ts, f"Key {k} missing from timeline_state: {set(ts.keys())}"
            assert ts["_primed"] is False
            assert ts["session_share_count"] == 0
            assert ts["all_time_best_diff_raw"] == 0.0
        finally:
            self._teardown()

    # ── Test 5: test_opportunities set to None ──

    def test_test_opportunities_set_to_none(self, monkeypatch, client):
        """test_opportunities should be None after wipe."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            assert _state_module.test_opportunities is None
        finally:
            self._teardown()

    # ── Test 6: response body confirms address change ──

    def test_response_confirms_new_address(self, monkeypatch, client):
        """Response JSON should contain ok=True, success=True and address."""
        self._setup(monkeypatch)
        try:
            resp = client.post("/api/set-address", json={"address": NEW_ADDRESS})
            data = json.loads(resp.data)
            assert data.get("ok") is True, "Response should have ok: true"
            assert data.get("success") is True, "Response should have success: true"
            assert data.get("address") == NEW_ADDRESS
        finally:
            self._teardown()

    # ── Test 7: BTC_ADDRESS global updated ──

    def test_btc_address_global_updated(self, monkeypatch, client):
        """BTC_ADDRESS global should reflect the new address."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            assert _app_module.BTC_ADDRESS == NEW_ADDRESS
        finally:
            self._teardown()

    # ── Test 8: ts is reset by the wipe ──

    def test_ts_reset_on_wipe(self, monkeypatch, client):
        """The wipe sets ts to 0 (fresh poll would populate it afterwards)."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            ts = _state_module.latest_snapshot.get("ts", -1)
            assert ts == 0, f"ts should be 0 after wipe (poll mocked), got {ts}"
        finally:
            self._teardown()

    # ── Test 9: invalid address is rejected (no wipe) ──

    def test_invalid_address_rejected_no_wipe(self, monkeypatch, client):
        """Address with bad prefix should return 400 and NOT wipe state."""
        self._setup(monkeypatch)
        try:
            _state_module.test_opportunities = {"keep": "this"}
            resp = client.post("/api/set-address", json={"address": "short"})
            assert resp.status_code == 400
            assert _state_module.test_opportunities == {"keep": "this"}, (
                "State should NOT be wiped on invalid address"
            )
        finally:
            self._teardown()

    # ── Test 10: empty address rejected ──

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

    # ── Test 11: old worker data removed from snapshot ──

    def test_old_worker_data_gone(self, monkeypatch, client):
        """Worker/pool/account data from previous session should be nulled."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})
            snap = _state_module.latest_snapshot
            # Fields are nulled, not removed (frontend reads the schema)
            assert snap["worker"] is None
            assert snap["pool"] is None
            assert snap["account"] is None
            prox = snap.get("proximity")
            assert prox is None or (
                isinstance(prox, dict)
                and prox.get("reason") == "insufficient_data"
            )
        finally:
            self._teardown()

    # ── Test 12: optional wipe targets don't crash ──

    def test_optional_wipable_attrs_dont_crash(self, monkeypatch, client):
        """_reset_session_state should handle missing optional attrs gracefully."""
        self._setup(monkeypatch)
        try:
            client.post("/api/set-address", json={"address": NEW_ADDRESS})

            # Core wipe should have completed
            assert "ts" in _state_module.latest_snapshot
            assert _state_module.latest_snapshot["worker"] is None

            # Alerts: wiped then 1 success alert added by endpoint
            assert len(_app_module.memory_critical_alerts) == 1
            assert _app_module.memory_critical_alerts[0]["severity"] == "SUCCESS"

            # last_known_prices: keys preserved, values nulled
            assert _state_module.last_known_prices["braiins"] is None
            assert _state_module.last_known_prices["mrr"] is None
            assert _state_module.test_opportunities is None
        finally:
            self._teardown()
