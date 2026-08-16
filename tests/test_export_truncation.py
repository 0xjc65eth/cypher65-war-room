"""
CYPHER65 // Generic-export truncation metadata regression tests (Issue #201)
============================================================================
Guards routes/export_routes.api_export:

  1. ``total`` reflects the FULL row count in the requested range (before the
     per-export cap EXPORT_ROW_LIMIT) — never the truncated length.
  2. ``truncated`` is True exactly when EXPORT_ROW_LIMIT dropped rows.
  3. JSON always carries total/truncated (additive, backward compatible).
  4. CSV adds a ``#``-prefixed metadata row ONLY when truncated — non-truncated
     CSVs remain byte-identical to the legacy format (header + data only).
  5. The alerts COUNT honors the same tenant WHERE as the SELECT (isolation
     never leaks into the completeness figure).
"""
import sqlite3
import time

import pytest

from app import app as _flask_app
from routes import export_routes as _export_routes
from services.auth import create_token


@pytest.fixture
def client():
    """Flask test client (lazy import — DB_PATH read at request time)."""
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _default_headers() -> dict:
    token = create_token(subject="default", extra_claims={"role": "viewer"})
    return _auth_headers(token)


def _seed_snapshots(tmp_path, rows) -> None:
    """Create the snapshots table and insert [(ts, worker_hashrate), ...]."""
    conn = sqlite3.connect(str(tmp_path / "trunc.sqlite"))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS snapshots ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
        "worker_hashrate REAL, network_difficulty REAL, btc_usd REAL)"
    )
    conn.executemany(
        "INSERT INTO snapshots (ts, worker_hashrate) VALUES (?, ?)", rows
    )
    conn.commit()
    conn.close()


def _seed_alerts(tmp_path, tenant_id: str, n: int = 3) -> None:
    """Create the alerts table and insert ``n`` rows for ``tenant_id``."""
    conn = sqlite3.connect(str(tmp_path / "trunc.sqlite"))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alerts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
        "severity TEXT, category TEXT, message TEXT, device_id TEXT, "
        "alert_type TEXT, is_acknowledged INTEGER DEFAULT 0, active INTEGER DEFAULT 1, "
        "meta TEXT, tenant_id TEXT DEFAULT 'default')"
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


class TestExportTruncationMetadata:
    """total/truncated ride every export; CSV metadata only when truncated."""

    def test_json_always_carries_total_and_not_truncated(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "trunc.sqlite"))
        now = int(time.time())
        _seed_snapshots(tmp_path, [(now - i * 60, 100.0 + i) for i in range(3)])
        res = client.get(
            "/api/export/snapshots.json?range=all",
            headers=_default_headers(),
            environ_base={"REMOTE_ADDR": "203.0.113.7"},
        )
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["total"] == 3
        assert payload["truncated"] is False
        assert len(payload["rows"]) == 3

    def test_json_truncated_flag_and_partial_rows(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "trunc.sqlite"))
        monkeypatch.setattr(_export_routes, "EXPORT_ROW_LIMIT", 5)
        now = int(time.time())
        _seed_snapshots(tmp_path, [(now - i * 60, 100.0 + i) for i in range(10)])
        res = client.get(
            "/api/export/snapshots.json?range=all",
            headers=_default_headers(),
            environ_base={"REMOTE_ADDR": "203.0.113.7"},
        )
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["total"] == 10
        assert payload["truncated"] is True
        assert len(payload["rows"]) == 5  # EXPORT_ROW_LIMIT honored

    def test_csv_not_truncated_is_legacy_format(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "trunc.sqlite"))
        now = int(time.time())
        _seed_snapshots(tmp_path, [(now - i * 60, 100.0 + i) for i in range(3)])
        res = client.get(
            "/api/export/snapshots.csv?range=all",
            headers=_default_headers(),
            environ_base={"REMOTE_ADDR": "203.0.113.7"},
        )
        assert res.status_code == 200
        lines = res.data.decode().splitlines()
        # header + 3 data rows, NO metadata line — legacy format preserved
        assert len(lines) == 4
        assert not lines[0].startswith("#")
        assert "id" in lines[0]

    def test_csv_truncated_metadata_row_first(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "trunc.sqlite"))
        monkeypatch.setattr(_export_routes, "EXPORT_ROW_LIMIT", 5)
        now = int(time.time())
        _seed_snapshots(tmp_path, [(now - i * 60, 100.0 + i) for i in range(10)])
        res = client.get(
            "/api/export/snapshots.csv?range=all",
            headers=_default_headers(),
            environ_base={"REMOTE_ADDR": "203.0.113.7"},
        )
        assert res.status_code == 200
        lines = res.data.decode().splitlines()
        meta = lines[0]
        assert meta.startswith("# CYPHER65 export")
        assert "total=10" in meta
        assert "truncated=true" in meta
        # metadata + header + exactly EXPORT_ROW_LIMIT data rows
        assert len(lines) == 1 + 1 + 5

    def test_count_respects_range_window(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "trunc.sqlite"))
        now = int(time.time())
        _seed_snapshots(tmp_path, [(now, 100.0), (now - 2 * 86400, 200.0)])
        res = client.get(
            "/api/export/snapshots.json?range=24h",
            headers=_default_headers(),
            environ_base={"REMOTE_ADDR": "203.0.113.7"},
        )
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["total"] == 1  # only the in-window row counts
        assert payload["truncated"] is False


class TestAlertsCountTenantFiltered:
    """The truncation COUNT honors the same tenant WHERE as the SELECT."""

    def test_alerts_total_is_tenant_scoped(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("API_KEY", "master-key")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "trunc.sqlite"))
        _seed_alerts(tmp_path, "tenant-a", n=3)
        _seed_alerts(tmp_path, "tenant-b", n=3)
        token_a = create_token(subject="tenant-a", extra_claims={"role": "viewer"})
        res = client.get(
            "/api/export/alerts.json?range=all",
            headers=_auth_headers(token_a),
            environ_base={"REMOTE_ADDR": "203.0.113.7"},
        )
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["total"] == 3  # NOT 6 — tenant isolation preserved
        assert payload["truncated"] is False
        msgs = [r["message"] for r in payload["rows"]]
        assert all("tenant-b" not in m for m in msgs)
