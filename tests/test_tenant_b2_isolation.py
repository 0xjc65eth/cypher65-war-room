"""
CYPHER65 // Tenant Isolation — Fase 4 · B2 Test Suite
======================================================
Verifies complete tenant isolation after B2:
  - Core DeviceRegistry: A cannot see/remove B's devices
  - AlertEngine: rules filtered by tenant; alerts persisted with tenant_id
  - AutomationEngine: rules filtered by tenant
  - API routes: alerts / automation-rules scoped by Bearer tenant

Strategy:
  - Real CoreDeviceRegistry on a tmp SQLite (hermetic)
  - AlertEngine/AutomationEngine on tmp SQLite with tenant_id columns
  - Flask test_client with Authorization: Bearer <token(sub=tenant)>
"""
import sqlite3
import time
from unittest.mock import MagicMock

import pytest

from services.auth import create_token

import app as _app_module

app = _app_module.app

from core.registry.device_registry import DeviceRegistry as CoreDeviceRegistry
from core.models.device import Device as CoreDevice
from core.alerts.alert_engine import AlertEngine, Alert, AlertRule
from core.alerts.automation_engine import AutomationEngine, AutomationRule


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "tenant-b2-secret"
    with app.test_client() as c:
        yield c


def _bearer(tenant_id: str) -> dict:
    """Create a Bearer header for the given tenant.

    create_token() reads JWT_SECRET_KEY from current_app.config — it MUST be
    called inside an app context so the token is signed with the same secret
    that verify_token() uses during the request (otherwise it falls back to
    a random per-call secret and verification fails → tenant='default').
    """
    with app.app_context():
        token = create_token(subject=tenant_id)
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════
#  Core DeviceRegistry isolation
# ══════════════════════════════════════════════════════════════════════

class TestCoreRegistryIsolation:
    @pytest.fixture
    def registry(self, tmp_path):
        r = CoreDeviceRegistry(str(tmp_path / "core_isolation.sqlite"))
        yield r

    def _device(self, name: str, tenant: str) -> CoreDevice:
        return CoreDevice(name=name, tenant_id=tenant, metadata={"seed_marker": "test"})

    def test_list_scoped_by_tenant(self, registry):
        registry.add_device(self._device("Alice Miner", "acme"))
        registry.add_device(self._device("Bob Miner", "brave"))

        a = registry.list_devices(tenant_id="acme")
        b = registry.list_devices(tenant_id="brave")
        assert {d.name for d in a} == {"Alice Miner"}
        assert {d.name for d in b} == {"Bob Miner"}

    def test_get_device_scoped_by_tenant(self, registry):
        dev = registry.add_device(self._device("Alice Miner", "acme"))
        assert registry.get_device(dev.id, tenant_id="acme") is not None
        assert registry.get_device(dev.id, tenant_id="brave") is None

    def test_remove_device_scoped_by_tenant(self, registry):
        dev = registry.add_device(self._device("Alice Miner", "acme"))
        # Tenant B cannot remove A's device
        assert registry.remove_device(dev.id, tenant_id="brave") is False
        assert registry.get_device(dev.id, tenant_id="acme") is not None
        # Tenant A can
        assert registry.remove_device(dev.id, tenant_id="acme") is True
        assert registry.get_device(dev.id, tenant_id="acme") is None

    def test_persisted_tenant_id_survives_reload(self, tmp_path):
        db = str(tmp_path / "core_reload.sqlite")
        r1 = CoreDeviceRegistry(db)
        r1.add_device(self._device("Alice Miner", "acme"))
        del r1

        r2 = CoreDeviceRegistry(db)
        r2.load_from_db()
        devices = r2.list_devices(tenant_id="acme")
        assert len(devices) == 1
        assert devices[0].name == "Alice Miner"
        assert r2.list_devices(tenant_id="brave") == []


# ══════════════════════════════════════════════════════════════════════
#  AlertEngine tenant filtering
# ══════════════════════════════════════════════════════════════════════

class TestAlertEngineTenant:
    def _db_with_rule(self, tmp_path, tenant_id: str):
        db = str(tmp_path / "alerts.sqlite")
        conn = sqlite3.connect(db)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                metric TEXT NOT NULL, operator TEXT NOT NULL DEFAULT '>',
                threshold REAL NOT NULL, severity TEXT NOT NULL,
                category TEXT NOT NULL, device_id TEXT DEFAULT '',
                model TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
                cooldown_seconds INTEGER DEFAULT 300, tenant_id TEXT DEFAULT 'default'
            )"""
        )
        c.execute(
            "INSERT INTO alert_rules (name, metric, operator, threshold, severity, category, tenant_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("temp_custom", "temperature", ">", 60.0, "WARN", "temperature", tenant_id),
        )
        conn.commit()
        conn.close()
        return db

    def test_rules_filtered_by_tenant(self, tmp_path):
        db = self._db_with_rule(tmp_path, "acme")
        engine = AlertEngine(db)
        rules_acme = engine._load_rules(tenant_id="acme")
        rules_brave = engine._load_rules(tenant_id="brave")
        assert any(r.name == "temp_custom" for r in rules_acme)
        # Brave sees only defaults (custom rule belongs to acme)
        assert all(r.name != "temp_custom" for r in rules_brave)

    def test_alert_persists_tenant_id(self, tmp_path):
        db = str(tmp_path / "alerts_persist.sqlite")
        conn = sqlite3.connect(db)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
                severity TEXT, category TEXT, message TEXT,
                device_id TEXT DEFAULT '', alert_type TEXT DEFAULT 'threshold',
                is_acknowledged INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
                meta TEXT DEFAULT '{}', tenant_id TEXT DEFAULT 'default'
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
                alert_type TEXT NOT NULL, device_id TEXT DEFAULT '',
                severity TEXT NOT NULL, action_taken TEXT DEFAULT '',
                tenant_id TEXT DEFAULT 'default'
            )"""
        )
        conn.commit()
        conn.close()

        engine = AlertEngine(db)
        alert = Alert(
            ts=int(time.time()), severity="WARN", category="temperature",
            message="Alice temp high", device_id="dev-a", tenant_id="acme",
        )
        engine.persist([alert])

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT tenant_id FROM alerts ORDER BY id DESC LIMIT 1").fetchone()
        assert row[0] == "acme"
        hrow = conn.execute("SELECT tenant_id FROM alert_history ORDER BY id DESC LIMIT 1").fetchone()
        assert hrow[0] == "acme"
        conn.close()


# ══════════════════════════════════════════════════════════════════════
#  AutomationEngine tenant filtering
# ══════════════════════════════════════════════════════════════════════

class TestAutomationEngineTenant:
    def test_load_rules_filtered_by_tenant(self, tmp_path):
        db = str(tmp_path / "automation.sqlite")
        conn = sqlite3.connect(db)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS automation_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                target_device_id TEXT NOT NULL, condition_metric TEXT NOT NULL,
                condition_operator TEXT NOT NULL, condition_value REAL NOT NULL,
                action_command TEXT NOT NULL, action_parameters TEXT DEFAULT '{}',
                is_enabled INTEGER DEFAULT 1, min_interval_seconds INTEGER DEFAULT 60,
                tenant_id TEXT DEFAULT 'default'
            )"""
        )
        c.execute(
            "INSERT INTO automation_rules (name, target_device_id, condition_metric, condition_operator, "
            "condition_value, action_command, is_enabled, tenant_id) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            ("acme-cool", "dev-a", "temperature", ">", 70.0, "restart", "acme"),
        )
        conn.commit()
        conn.close()

        safety = MagicMock()
        safety.validate_command.return_value = MagicMock(allowed=False, reason="blocked")
        engine = AutomationEngine(db, safety)

        acme = engine.load_rules(tenant_id="acme")
        brave = engine.load_rules(tenant_id="brave")
        assert any(r.name == "acme-cool" for r in acme)
        assert all(r.name != "acme-cool" for r in brave)


# ══════════════════════════════════════════════════════════════════════
#  API routes isolation (Bearer tenant)
# ══════════════════════════════════════════════════════════════════════

class TestApiTenantIsolation:
    def test_alerts_scoped_by_tenant(self, client):
        """GET /api/alerts only returns the current tenant's alerts."""
        from app import get_db
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO alerts (ts, severity, category, message, device_id, alert_type, tenant_id, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (int(time.time()), "WARN", "temperature", "Alice alert", "dev-a", "threshold", "acme"),
        )
        c.execute(
            "INSERT INTO alerts (ts, severity, category, message, device_id, alert_type, tenant_id, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (int(time.time()), "CRIT", "offline", "Bob alert", "dev-b", "threshold", "brave"),
        )
        conn.commit()
        conn.close()

        try:
            # Tenant A sees only A's alert
            res = client.get("/api/alerts", headers=_bearer("acme"))
            assert res.status_code == 200
            alerts = res.get_json()["alerts"]
            assert any(a["message"] == "Alice alert" for a in alerts)
            assert all(a["message"] != "Bob alert" for a in alerts)

            # Tenant B sees only B's alert
            res = client.get("/api/alerts", headers=_bearer("brave"))
            assert res.status_code == 200
            alerts = res.get_json()["alerts"]
            assert any(a["message"] == "Bob alert" for a in alerts)
            assert all(a["message"] != "Alice alert" for a in alerts)
        finally:
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM alerts WHERE message IN ('Alice alert', 'Bob alert')")
            conn.commit()
            conn.close()

    def test_automation_rules_scoped_by_tenant(self, client):
        """POST/GET /api/automation-rules are scoped by the Bearer tenant."""
        from app import get_db

        # Create a rule as tenant acme
        res = client.post(
            "/api/automation-rules",
            headers=_bearer("acme"),
            json={
                "name": "acme-rule",
                "target_device_id": "dev-a",
                "condition_metric": "temperature",
                "condition_operator": ">",
                "condition_value": 70,
                "action_command": "restart",
            },
        )
        assert res.status_code == 200
        rule_id = res.get_json()["id"]

        try:
            # Tenant A sees the rule
            res_a = client.get("/api/automation-rules", headers=_bearer("acme"))
            rules_a = res_a.get_json()["rules"]
            assert any(r["id"] == rule_id and r["name"] == "acme-rule" for r in rules_a)

            # Tenant B does not see it
            res_b = client.get("/api/automation-rules", headers=_bearer("brave"))
            rules_b = res_b.get_json()["rules"]
            assert all(r["id"] != rule_id for r in rules_b)

            # Tenant B cannot DELETE it
            res_del_b = client.delete(
                f"/api/automation-rules/{rule_id}", headers=_bearer("brave")
            )
            assert res_del_b.status_code == 200  # no-op; rule still owned by acme
            res_a2 = client.get("/api/automation-rules", headers=_bearer("acme"))
            assert any(r["id"] == rule_id for r in res_a2.get_json()["rules"])
        finally:
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM automation_rules WHERE id=?", (rule_id,))
            conn.commit()
            conn.close()

    def test_acknowledge_scoped_by_tenant(self, client):
        """Acknowledging another tenant's alert id is a safe no-op."""
        from app import get_db
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO alerts (ts, severity, category, message, device_id, alert_type, tenant_id, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (int(time.time()), "WARN", "temperature", "Alice ack test", "dev-a", "threshold", "acme", ),
        )
        conn.commit()
        alert_id = c.lastrowid
        conn.close()

        try:
            # Tenant B tries to acknowledge A's alert → no row updated
            res = client.post(
                "/api/alerts/acknowledge",
                headers=_bearer("brave"),
                json={"id": alert_id},
            )
            assert res.status_code == 200
            conn = get_db()
            c = conn.cursor()
            row = conn.execute("SELECT is_acknowledged, active FROM alerts WHERE id=?", (alert_id,)).fetchone()
            assert row["is_acknowledged"] == 0  # untouched
            assert row["active"] == 1
            conn.close()
        finally:
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
            conn.commit()
            conn.close()
