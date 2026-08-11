"""
CYPHER65 // Export tenant-isolation regression tests (Fase 4 · B2)
====================================================================
Guards the security fix on /api/export/* and /api/tax/export:

  1. Named tenants may NEVER export the OPERATOR-only tables
     (snapshots / share_timeline / highest_diff_events) — fail-closed 403.
  2. The `alerts` table IS tenant-scoped: a named tenant only sees its OWN
     rows, never another tenant's alerts.
  3. The default (operator) tenant keeps full export access.
"""
import sqlite3
import time

import pytest

from app import app as _flask_app
from services.auth import create_token


@pytest.fixture
def client():
    """Flask test client (lazy import — DB_PATH read at request time)."""
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_alerts(tmp_path, tenant_id: str, n: int = 3) -> None:
    """Create the alerts table + the operator-only tables the route reads."""
    conn = sqlite3.connect(str(tmp_path / "iso.sqlite"))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alerts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
        "severity TEXT, category TEXT, message TEXT, device_id TEXT, "
        "alert_type TEXT, is_acknowledged INTEGER DEFAULT 0, active INTEGER DEFAULT 1, "
        "meta TEXT, tenant_id TEXT DEFAULT 'default')"
    )
    # Operator-only tables (minimal schema the route SELECTs against).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS snapshots ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
        "worker_hashrate REAL, network_difficulty REAL, btc_usd REAL, "
        "btc_brl REAL, btc_eur REAL, btc_gbp REAL, btc_jpy REAL, "
        "btc_krw REAL, btc_cny REAL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS share_timeline ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
        "event_type TEXT, severity TEXT, message TEXT, meta TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS highest_diff_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
        "block_height INTEGER, top_diff_address TEXT, difficulty TEXT, "
        "claimed INTEGER, block_timestamp INTEGER, is_mine INTEGER)"
    )
    now = int(time.time())
    for i in range(n):
        conn.execute(
            "INSERT INTO alerts (ts, severity, category, message, tenant_id) "
            "VALUES (?, 'WARN', 'test', ?, ?)",
            (now - i, f"alert-{tenant_id}-{i}", tenant_id),
        )
    conn.commit()
    conn.close()


class TestOperatorTablesFailClosed:
    """snapshots / share_timeline / highest_diff_events are operator-only."""

    OPERATOR_TABLES = ["snapshots", "share_timeline", "highest_diff_events"]

    @pytest.mark.parametrize("table", OPERATOR_TABLES)
    def test_named_tenant_never_exports_operator_table(self, client, monkeypatch, tmp_path, table):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "iso.sqlite"))
        # Tenant A is a named (non-default) tenant.
        token = create_token(subject="tenant-a", extra_claims={"role": "viewer"})
        res = client.get(f"/api/export/{table}.csv", headers=_auth_headers(token),
                         environ_base={"REMOTE_ADDR": "203.0.113.7"})
        assert res.status_code == 403, f"{table}: expected fail-closed 403, got {res.status_code}"
        body = res.get_json(silent=True) or {}
        assert "forbidden" in body.get("error", "")

    def test_tenant_a_never_sees_tenant_b_alerts(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "iso.sqlite"))
        _seed_alerts(tmp_path, "tenant-a")
        _seed_alerts(tmp_path, "tenant-b")
        token_a = create_token(subject="tenant-a", extra_claims={"role": "viewer"})
        res = client.get("/api/export/alerts.json?range=all",
                         headers=_auth_headers(token_a),
                         environ_base={"REMOTE_ADDR": "203.0.113.7"})
        assert res.status_code == 200
        rows = res.get_json()["rows"]
        msgs = [r["message"] for r in rows]
        assert all("tenant-b" not in m for m in msgs), "tenant A exported tenant B alerts!"
        assert any("tenant-a" in m for m in msgs)

    def test_default_tenant_keeps_full_access(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "iso.sqlite"))
        _seed_alerts(tmp_path, "default")
        token = create_token(subject="default", extra_claims={"role": "viewer"})
        for table in self.OPERATOR_TABLES + ["alerts"]:
            res = client.get(f"/api/export/{table}.json?range=all",
                             headers=_auth_headers(token),
                             environ_base={"REMOTE_ADDR": "203.0.113.7"})
            # Default tenant is allowed through the gate; route must not 403.
            assert res.status_code != 403, f"{table}: default tenant should not be blocked"

    def test_anonymous_remote_still_blocked(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "iso.sqlite"))
        res = client.get("/api/export/snapshots.csv",
                         environ_base={"REMOTE_ADDR": "203.0.113.7"})
        assert res.status_code == 403


class TestTaxExportIsolation:
    """/api/tax/export reads operator-only tables → same fail-closed rule."""

    def test_named_tenant_blocked_from_tax_export(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "iso.sqlite"))
        token = create_token(subject="tenant-a", extra_claims={"role": "viewer"})
        res = client.get("/api/tax/export?currency=JPY", headers=_auth_headers(token),
                         environ_base={"REMOTE_ADDR": "203.0.113.7"})
        assert res.status_code == 403, f"expected 403, got {res.status_code}"
        body = res.get_json(silent=True) or {}
        assert "forbidden" in body.get("error", "")

    def test_default_tenant_tax_export_not_gated(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "iso.sqlite"))
        _seed_alerts(tmp_path, "default")
        token = create_token(subject="default", extra_claims={"role": "viewer"})
        res = client.get("/api/tax/export?currency=JPY", headers=_auth_headers(token),
                         environ_base={"REMOTE_ADDR": "203.0.113.7"})
        # Route must not 403 for the operator — and must actually produce CSV
        # (the seeded tables satisfy its queries).
        assert res.status_code != 403
        assert res.status_code == 200
