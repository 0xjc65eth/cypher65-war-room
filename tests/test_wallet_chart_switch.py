"""
CYPHER65 // Honest Telemetry — wallet switch chart history
===========================================================
Locks the /api/set-address behavior around per-wallet chart history:

- Switching to a DIFFERENT address must purge the DB-backed chart tables
  (proximity_history, snapshots, share_timeline) so the hashrate / best-diff /
  pool / net charts only ever show the CURRENT wallet's real data.
  The in-memory share_calc_history (cum_p / share_dist charts) is already
  cleared by _reset_session_state().
- Updating ONLY the worker name for the SAME address must keep the existing
  history (the wallet didn't change, so its charts stay valid).
"""
import pytest

import app as _app_module

# DIGO GARABELI full-access wallets (bypass strict prefix/checksum, so the
# tests don't depend on real checksum math).
DIGO_BTC = "bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn"
DIGO_LTC = "1473pql42jvtwxaaxcvsocrf6ytb8teted"


@pytest.fixture
def client():
    """Return a Flask test client."""
    _app_module.app.testing = True
    return _app_module.app.test_client()


@pytest.fixture(autouse=True)
def _restore_globals():
    """Snapshot/restore module globals mutated by /api/set-address."""
    saved = {"btc": _app_module.BTC_ADDRESS, "worker": _app_module.WORKER_NAME}
    yield
    _app_module.BTC_ADDRESS = saved["btc"]
    _app_module.WORKER_NAME = saved["worker"]


class _RecordingConn:
    """sqlite3-like stub that records every SQL statement executed."""

    row_factory = None

    def __init__(self):
        self.sql = []

    def cursor(self):
        return self

    def execute(self, sql, *a, **k):
        self.sql.append(sql)
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def commit(self):
        return None

    def close(self):
        return None


def _setup(monkeypatch, conn):
    """Isolate the endpoint: recording get_db, no real polling/history log."""
    monkeypatch.setattr(_app_module, "get_db", lambda: conn)
    monkeypatch.setattr(_app_module, "_log_wallet_change", lambda *a, **k: None)
    monkeypatch.setattr(_app_module, "poll_once", lambda: None)
    monkeypatch.setattr(_app_module, "_make_memory_alert", lambda *a, **k: {})
    monkeypatch.setattr(_app_module, "memory_critical_alerts", [])


def _deletes(conn):
    return [s for s in conn.sql if s.strip().upper().startswith("DELETE FROM")]


class TestWalletSwitchClearsChartHistory:
    def test_address_switch_purges_all_db_chart_tables(self, client, monkeypatch):
        conn = _RecordingConn()
        _setup(monkeypatch, conn)
        _app_module.BTC_ADDRESS = DIGO_BTC

        res = client.post("/api/set-address", json={"address": DIGO_LTC})
        assert res.status_code == 200

        deletes = _deletes(conn)
        assert any("proximity_history" in s for s in deletes), deletes
        assert any("snapshots" in s for s in deletes), deletes
        assert any("share_timeline" in s for s in deletes), deletes

    def test_worker_only_update_keeps_chart_history(self, client, monkeypatch):
        conn = _RecordingConn()
        _setup(monkeypatch, conn)
        _app_module.BTC_ADDRESS = DIGO_BTC

        res = client.post("/api/set-address", json={
            "address": DIGO_BTC, "worker": "new-worker",
        })
        assert res.status_code == 200

        deletes = _deletes(conn)
        assert deletes == [], f"worker-only update must NOT purge history: {deletes}"

    def test_same_address_no_worker_is_rejected(self, client, monkeypatch):
        """No change at all → 400, and no history is touched."""
        conn = _RecordingConn()
        _setup(monkeypatch, conn)
        _app_module.BTC_ADDRESS = DIGO_BTC

        res = client.post("/api/set-address", json={"address": DIGO_BTC})
        assert res.status_code == 400
        assert _deletes(conn) == []
