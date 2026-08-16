"""
CYPHER65 // Tenant Plan + Audit Log — Test Suite (Fase 4 · B3)
================================================================
Tests for the free-plan worker limits and the structured audit log:

- services.tenant.get_tenant_plan(): FREE defaults when row missing + row read
- services.tenant.count_tenant_workers() / can_add_worker(): per-tenant count
- services.tenant.log_audit() / recent_audit_logs(): write + tenant isolation
- GET /api/tenant/status → plan, max_workers, used_workers, remaining
- POST /api/axe-fleet/devices → 403 when the tenant is at its plan limit
- Audit rows are written on add_device success / blocked attempts

Strategy (mirrors test_tenant_auth.py):
  - monkeypatch.setenv("DB_PATH") → hermetic tmp SQLite
  - Flask test_client for endpoint tests
  - Real DeviceRegistry backed by the same tmp DB with AxeOSConnector patched
"""
import json
import sqlite3
from unittest.mock import patch

import pytest
from flask import Flask

from services.auth import create_token
from services.tenant import (
    can_add_worker,
    count_tenant_workers,
    get_tenant_plan,
    log_audit,
    recent_audit_logs,
    DEFAULT_PLAN,
    DEFAULT_MAX_WORKERS,
    SELF_HOST_MAX_WORKERS,
)
from axe_fleet.registry import DeviceRegistry

import app as _app_module

app = _app_module.app


# ══════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def client():
    """Return a Flask test client configured for testing."""
    app.config["TESTING"] = True
    saved = app.config.get("JWT_SECRET_KEY")
    app.config["JWT_SECRET_KEY"] = "tenant-plan-test-secret"
    with app.test_client() as c:
        yield c
    # Restore any pre-existing secret (cross-file config pollution broke
    # test_rbac_register.py, which relies on the env SECRET_KEY fallback).
    if saved is not None:
        app.config["JWT_SECRET_KEY"] = saved
    else:
        app.config.pop("JWT_SECRET_KEY", None)


@pytest.fixture
def tenant_db(tmp_path, monkeypatch):
    """Hermetic SQLite DB with the tenants/audit_logs/axe_devices tables.

    Sets DB_PATH so services.tenant (which reads os.environ DB_PATH) targets
    the scratch file — the real data/war_room.sqlite is never touched.
    """
    db_path = str(tmp_path / "tenant_plan.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            plan TEXT NOT NULL DEFAULT 'free',
            max_workers INTEGER NOT NULL DEFAULT 5,
            created_at INTEGER NOT NULL
        )"""
    )
    c.execute(
        """CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            user_id TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            target TEXT NOT NULL DEFAULT '',
            details TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    # Full axe_devices schema (matches app.py init_db + the registry's
    # removed_at tombstone migration) so the real registry can operate on it
    # hermetically. count_tenant_workers filters COALESCE(removed_at,0)=0, so
    # the column must exist or every count would crash to 0.
    c.execute(
        """CREATE TABLE axe_devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            model TEXT DEFAULT '',
            manufacturer TEXT DEFAULT '',
            firmware TEXT DEFAULT '',
            firmware_version TEXT DEFAULT '',
            api_version TEXT DEFAULT '',
            ip_address TEXT NOT NULL,
            hostname TEXT DEFAULT '',
            mac_address TEXT DEFAULT '',
            last_seen INTEGER DEFAULT 0,
            status TEXT DEFAULT 'OFFLINE',
            group_id TEXT DEFAULT '',
            capabilities TEXT DEFAULT '{}',
            added_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            tenant_id TEXT DEFAULT 'default',
            agent_managed INTEGER DEFAULT 0,
            removed_at INTEGER DEFAULT 0
        )"""
    )
    conn.commit()
    conn.close()
    return db_path


def _seed_tenant(db_path, tid, plan=DEFAULT_PLAN, max_workers=DEFAULT_MAX_WORKERS):
    """Insert a tenant row into the scratch DB."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO tenants (id, name, plan, max_workers, created_at) VALUES (?, ?, ?, ?, 0)",
        (tid, tid, plan, max_workers),
    )
    conn.commit()
    conn.close()


def _seed_axe_device(db_path, device_id, name, ip, tenant_id):
    """Insert an axe_devices row directly (count test helper)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO axe_devices
        (id, name, ip_address, tenant_id, added_at, updated_at)
        VALUES (?, ?, ?, ?, 0, 0)""",
        (device_id, name, ip, tenant_id),
    )
    conn.commit()
    conn.close()


def _make_hermetic_registry(db_path):
    """Real DeviceRegistry on the scratch DB with a patched connector."""
    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    from axe_fleet.connector import AxeOSConnectorError

    class _FakeConn:
        def fetch_info(self):
            raise AxeOSConnectorError("hermetic")

        def detect_capabilities(self):
            return {}

    with patch("axe_fleet.registry.AxeOSConnector", return_value=_FakeConn()):
        r = DeviceRegistry(get_db)
        r.ensure_tables()
    return r


# ══════════════════════════════════════════════════════════════════════
#  get_tenant_plan / can_add_worker — service layer
# ══════════════════════════════════════════════════════════════════════

class TestTenantPlan:
    def test_defaults_when_row_missing(self, tenant_db):
        """A tenant with no row is bounded by the FREE-plan defaults."""
        assert get_tenant_plan("ghost") == {"plan": DEFAULT_PLAN, "max_workers": DEFAULT_MAX_WORKERS}

    def test_reads_custom_row(self, tenant_db):
        _seed_tenant(tenant_db, "acme", plan="free", max_workers=2)
        assert get_tenant_plan("acme") == {"plan": "free", "max_workers": 2}

    def test_selfhost_default_tenant_never_capped_at_free_limit(self, tenant_db):
        """The operator's own 'default' tenant gets the generous self-host cap,
        not the strict free-tier limit — a regression guard for the silent-403
        bug the reviewer flagged (no UI to raise max_workers)."""
        assert get_tenant_plan("default") == {"plan": DEFAULT_PLAN, "max_workers": SELF_HOST_MAX_WORKERS}
        assert get_tenant_plan("") == {"plan": DEFAULT_PLAN, "max_workers": SELF_HOST_MAX_WORKERS}
        # A seeded row for 'default' is honored over the fallback.
        _seed_tenant(tenant_db, "default", max_workers=10)
        assert get_tenant_plan("default") == {"plan": DEFAULT_PLAN, "max_workers": 10}

    def test_count_workers_per_tenant(self, tenant_db):
        _seed_axe_device(tenant_db, "d1", "A", "10.0.0.1", "acme")
        _seed_axe_device(tenant_db, "d2", "B", "10.0.0.2", "acme")
        _seed_axe_device(tenant_db, "d3", "C", "10.0.0.3", "brave")
        assert count_tenant_workers("acme") == 2
        assert count_tenant_workers("brave") == 1
        assert count_tenant_workers("ghost") == 0

    def test_can_add_worker_honors_limit(self, tenant_db):
        _seed_tenant(tenant_db, "acme", max_workers=1)
        _seed_axe_device(tenant_db, "d1", "A", "10.0.0.1", "acme")
        assert can_add_worker("acme") is False  # 1 of 1 used
        _seed_tenant(tenant_db, "brave", max_workers=5)
        assert can_add_worker("brave") is True  # 0 of 5 used

    def test_can_add_worker_with_defaults(self, tenant_db):
        _seed_tenant(tenant_db, "acme", max_workers=5)
        for i in range(4):
            _seed_axe_device(tenant_db, f"d{i}", f"A{i}", f"10.0.0.{i}", "acme")
        assert can_add_worker("acme") is True
        _seed_axe_device(tenant_db, "d9", "A9", "10.0.0.9", "acme")
        assert can_add_worker("acme") is False


# ══════════════════════════════════════════════════════════════════════
#  log_audit / recent_audit_logs — service layer
# ══════════════════════════════════════════════════════════════════════

class TestAuditLog:
    def test_log_audit_writes_row(self, tenant_db):
        row_id = log_audit("acme", "auth.login", details={"ip": "1.2.3.4"})
        assert row_id is not None
        rows = recent_audit_logs("acme")
        assert len(rows) == 1
        assert rows[0]["action"] == "auth.login"
        assert rows[0]["tenant_id"] == "acme"
        # details is parsed to a dict by recent_audit_logs (no json.loads needed).
        assert rows[0]["details"] == {"ip": "1.2.3.4"}

    def test_audit_isolation_between_tenants(self, tenant_db):
        log_audit("acme", "device.command", target="d1")
        log_audit("brave", "device.command", target="d2")
        acme_rows = recent_audit_logs("acme")
        brave_rows = recent_audit_logs("brave")
        assert len(acme_rows) == 1 and acme_rows[0]["target"] == "d1"
        assert len(brave_rows) == 1 and brave_rows[0]["target"] == "d2"

    def test_log_audit_empty_action_returns_none(self, tenant_db):
        assert log_audit("acme", "") is None

    def test_log_audit_never_raises_on_missing_table(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "no_audit.sqlite"))
        assert log_audit("acme", "auth.login") is None

    def test_recent_audit_logs_empty_ok(self, tenant_db):
        assert recent_audit_logs("acme") == []


# ══════════════════════════════════════════════════════════════════════
#  GET /api/tenant/status — endpoint
# ══════════════════════════════════════════════════════════════════════

class TestTenantStatusEndpoint:
    def test_returns_plan_usage(self, client, tenant_db, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "tenant-plan-test-secret")
        _seed_tenant(tenant_db, "acme", max_workers=2)
        _seed_axe_device(tenant_db, "d1", "A", "10.0.0.1", "acme")
        token = create_token(subject="acme")

        res = client.get("/api/tenant/status", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["tenant_id"] == "acme"
        assert data["plan"] == "free"
        assert data["max_workers"] == 2
        assert data["used_workers"] == 1
        assert data["remaining_workers"] == 1

    def test_defaults_when_no_tenant_row(self, client, tenant_db, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "tenant-plan-test-secret")
        token = create_token(subject="ghost")

        res = client.get("/api/tenant/status", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["plan"] == DEFAULT_PLAN
        assert data["max_workers"] == DEFAULT_MAX_WORKERS
        assert data["used_workers"] == 0


# ══════════════════════════════════════════════════════════════════════
#  POST /api/axe-fleet/devices — plan enforcement
# ══════════════════════════════════════════════════════════════════════

class TestAddDeviceEnforcement:
    def test_add_blocked_at_limit(self, client, tenant_db, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "tenant-plan-test-secret")
        _seed_tenant(tenant_db, "acme", max_workers=1)
        _seed_axe_device(tenant_db, "d1", "Existing", "10.0.0.1", "acme")
        registry = _make_hermetic_registry(tenant_db)
        token = create_token(subject="acme")

        with patch("axe_fleet.routes._registry", registry):
            res = client.post(
                "/api/axe-fleet/devices",
                json={"ip_address": "10.0.0.9", "name": "Overflow"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert res.status_code == 403
        data = res.get_json()
        assert data["success"] is False
        assert data["plan"] == "free"
        assert data["max_workers"] == 1
        # The overflow device must NOT have been persisted.
        assert len(registry.list_devices(tenant_id="acme")) == 1

    def test_add_allowed_under_limit(self, client, tenant_db, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "tenant-plan-test-secret")
        _seed_tenant(tenant_db, "brave", max_workers=3)
        registry = _make_hermetic_registry(tenant_db)
        token = create_token(subject="brave")

        with patch("axe_fleet.routes._registry", registry):
            res = client.post(
                "/api/axe-fleet/devices",
                json={"ip_address": "10.0.0.5", "name": "New Miner"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert res.status_code == 201
        assert res.get_json()["success"] is True
        assert len(registry.list_devices(tenant_id="brave")) == 1

    def test_audit_written_on_blocked_attempt(self, client, tenant_db, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "tenant-plan-test-secret")
        _seed_tenant(tenant_db, "acme", max_workers=1)
        _seed_axe_device(tenant_db, "d1", "Existing", "10.0.0.1", "acme")
        registry = _make_hermetic_registry(tenant_db)
        token = create_token(subject="acme")

        with patch("axe_fleet.routes._registry", registry):
            client.post(
                "/api/axe-fleet/devices",
                json={"ip_address": "10.0.0.9", "name": "Overflow"},
                headers={"Authorization": f"Bearer {token}"},
            )

        rows = recent_audit_logs("acme")
        assert any(r["action"] == "fleet.device_add_blocked" for r in rows)
        blocked = [r for r in rows if r["action"] == "fleet.device_add_blocked"][0]
        assert blocked["target"] == "10.0.0.9"
        assert blocked["details"]["reason"] == "plan_worker_limit"
