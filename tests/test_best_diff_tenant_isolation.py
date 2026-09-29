"""Security regressions for Issue #642 best-diff tenant isolation."""

import sqlite3
import time

import pytest

from app import app, _persist_best_diff_history
from services.auth import create_token
from services.bootstrap import init_db


@pytest.fixture
def client(monkeypatch):
    secret = "best-diff-tenant-test-secret-0123456789abcdef"
    saved = app.config.get("JWT_SECRET_KEY")
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = secret
    monkeypatch.setenv("SECRET_KEY", secret)
    with app.test_client() as flask_client:
        yield flask_client
    if saved is None:
        app.config.pop("JWT_SECRET_KEY", None)
    else:
        app.config["JWT_SECRET_KEY"] = saved


def _headers(tenant):
    token = create_token(subject=tenant, extra_claims={"role": "viewer"})
    return {"Authorization": f"Bearer {token}"}


def _seed(tenant, device, best_diff):
    _persist_best_diff_history(
        int(time.time()),
        best_diff,
        str(best_diff),
        device,
        "test-pool",
        tenant_id=tenant,
    )


def test_global_history_never_mixes_tenants(client):
    _seed("history-a", "device-a", 101.0)
    _seed("history-b", "device-b", 202.0)

    response_a = client.get("/api/best-diff-history", headers=_headers("history-a"))
    response_b = client.get("/api/best-diff-history", headers=_headers("history-b"))

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert {row["device_id"] for row in response_a.get_json()["records"]} == {
        "device-a"
    }
    assert {row["device_id"] for row in response_b.get_json()["records"]} == {
        "device-b"
    }


def test_device_history_is_indistinguishable_from_missing_cross_tenant(client):
    _seed("owner-a", "private-device", 303.0)

    owner = client.get(
        "/api/devices/private-device/best-diff-history",
        headers=_headers("owner-a"),
    )
    foreign = client.get(
        "/api/devices/private-device/best-diff-history",
        headers=_headers("viewer-b"),
    )
    missing = client.get(
        "/api/devices/does-not-exist/best-diff-history",
        headers=_headers("viewer-b"),
    )

    assert owner.status_code == 200
    assert [row["device_id"] for row in owner.get_json()["records"]] == [
        "private-device"
    ]
    assert foreign.status_code == missing.status_code == 200
    assert foreign.get_json()["records"] == missing.get_json()["records"] == []


def test_legacy_history_rows_migrate_to_default_tenant(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE best_diff_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
        "device_id TEXT, best_diff REAL NOT NULL, best_diff_str TEXT, pool TEXT)"
    )
    conn.execute(
        "INSERT INTO best_diff_history "
        "(ts, device_id, best_diff, best_diff_str, pool) VALUES (1, 'legacy', 1, '1', '')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DB_PATH", str(db_path))

    init_db()

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(best_diff_history)")}
    tenant = conn.execute(
        "SELECT tenant_id FROM best_diff_history WHERE device_id='legacy'"
    ).fetchone()[0]
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(best_diff_history)")}
    conn.close()
    assert "tenant_id" in columns
    assert tenant == "default"
    assert "idx_best_diff_history_tenant_ts" in indexes
    assert "idx_best_diff_history_tenant_device_ts" in indexes
