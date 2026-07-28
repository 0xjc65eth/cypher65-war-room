"""Tests for core alert and automation engines."""
import sqlite3
import pytest
from core.alerts.alert_engine import AlertEngine, AlertRule
from core.alerts.automation_engine import AutomationEngine
from core.safety.safety_engine import SafetyEngine
from core.models.device import Device, DeviceStatus


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.sqlite")


@pytest.fixture
def alert_engine(db_path):
    # Ensure the tables AlertEngine depends on exist for in-memory tests.
    import sqlite3
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            severity TEXT,
            category TEXT,
            message TEXT,
            device_id TEXT DEFAULT '',
            alert_type TEXT DEFAULT 'threshold',
            is_acknowledged INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            meta TEXT DEFAULT '{}'
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            device_id TEXT DEFAULT '',
            severity TEXT NOT NULL,
            action_taken TEXT DEFAULT ''
        )"""
    )
    conn.commit()
    conn.close()
    engine = AlertEngine(db_path)
    return engine


@pytest.fixture
def automation_engine(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS automation_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            target_device_id TEXT NOT NULL,
            condition_metric TEXT NOT NULL,
            condition_operator TEXT NOT NULL,
            condition_value REAL NOT NULL,
            action_command TEXT NOT NULL,
            action_parameters TEXT DEFAULT '{}',
            is_enabled INTEGER DEFAULT 1,
            min_interval_seconds INTEGER DEFAULT 60
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            device_id TEXT DEFAULT '',
            severity TEXT NOT NULL,
            action_taken TEXT DEFAULT ''
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS automation_execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            rule_id INTEGER,
            rule_name TEXT DEFAULT '',
            device_id TEXT DEFAULT '',
            action_command TEXT DEFAULT '',
            status TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            result TEXT DEFAULT '{}'
        )"""
    )
    conn.commit()
    conn.close()

    def _audit(**kwargs):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute(
            """INSERT INTO automation_execution_log
            (ts, rule_id, rule_name, device_id, action_command, status, reason, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                kwargs.get("ts"),
                kwargs.get("rule_id"),
                kwargs.get("rule_name", ""),
                kwargs.get("device_id", ""),
                kwargs.get("action_command", ""),
                kwargs.get("status", ""),
                kwargs.get("reason", ""),
                "",
            ),
        )
        conn.commit()
        conn.close()

    return AutomationEngine(db_path, SafetyEngine(), audit_callback=_audit)


def _make_device(temperature=70.0, status="ONLINE"):
    d = Device(
        id="test-dev",
        name="Test",
        model="bitaxe",
        ip="192.168.1.1",
        status=DeviceStatus[status],
    )
    d.current_telemetry = {"temperature": temperature}
    return d


def test_alert_engine_temperature_rule(alert_engine):
    device = _make_device(temperature=90.0)
    alerts = alert_engine.evaluate([device])
    assert any(a.category == "temperature" and a.severity == "CRIT" for a in alerts)


def test_alert_engine_no_alert_when_ok(alert_engine):
    device = _make_device(temperature=60.0)
    alerts = alert_engine.evaluate([device])
    assert all(a.category != "temperature" for a in alerts)


def test_alert_engine_pool_disconnect(alert_engine):
    alerts = alert_engine.evaluate([], pool={})
    assert any(a.category == "pool_disconnect" for a in alerts)


def test_automation_engine_loads_rules(automation_engine):
    conn = sqlite3.connect(automation_engine.db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO automation_rules (name, target_device_id, condition_metric, condition_operator, condition_value, action_command) VALUES (?, ?, ?, ?, ?, ?)",
        ("hot", "test-dev", "temperature", ">", 85.0, "restart"),
    )
    conn.commit()
    conn.close()
    rules = automation_engine.load_rules()
    assert len(rules) == 1
    assert rules[0].name == "hot"


def test_automation_engine_evaluates_condition(automation_engine):
    conn = sqlite3.connect(automation_engine.db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO automation_rules (name, target_device_id, condition_metric, condition_operator, condition_value, action_command) VALUES (?, ?, ?, ?, ?, ?)",
        ("hot", "test-dev", "temperature", ">", 85.0, "restart"),
    )
    conn.commit()
    conn.close()
    device = _make_device(temperature=90.0)
    results = automation_engine.evaluate_rules([device])
    assert len(results) == 1
    assert results[0]["status"] in ("blocked", "executed")


def test_automation_engine_cooldown_prevents_spam(automation_engine):
    conn = sqlite3.connect(automation_engine.db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO automation_rules (name, target_device_id, condition_metric, condition_operator, condition_value, action_command, min_interval_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("hot", "test-dev", "temperature", ">", 85.0, "restart", 300),
    )
    conn.commit()
    conn.close()
    device = _make_device(temperature=90.0)
    # First evaluation should trigger the rule
    assert len(automation_engine.evaluate_rules([device])) == 1
    # Immediate re-evaluation should be suppressed by the 5-minute cooldown
    assert len(automation_engine.evaluate_rules([device])) == 0


def test_alert_engine_persists_to_history(alert_engine):
    device = _make_device(temperature=90.0)
    alerts = alert_engine.evaluate([device])
    assert alerts
    alert_engine.persist(alerts)
    conn = sqlite3.connect(alert_engine.db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM alert_history WHERE device_id=? ORDER BY ts DESC", (device.id,))
    rows = c.fetchall()
    conn.close()
    assert len(rows) >= 1


def test_automation_engine_logs_execution(automation_engine):
    conn = sqlite3.connect(automation_engine.db_path)
    c = conn.cursor()
    c.execute(
        """INSERT INTO automation_rules
        (name, target_device_id, condition_metric, condition_operator, condition_value, action_command, min_interval_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("hot", "test-dev", "temperature", ">", 85.0, "restart", 0),
    )
    conn.commit()
    conn.close()
    device = _make_device(temperature=90.0)
    automation_engine.evaluate_rules([device])
    conn = sqlite3.connect(automation_engine.db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM automation_execution_log WHERE device_id=? ORDER BY ts DESC", (device.id,))
    rows = c.fetchall()
    conn.close()
    assert len(rows) >= 1
