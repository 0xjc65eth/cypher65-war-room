"""Tests for core alert and automation engines."""
import sqlite3
import pytest
from core.alerts.alert_engine import AlertEngine, AlertRule
from core.alerts.automation_engine import AutomationEngine
from core.safety.safety_engine import SafetyEngine
from core.models.device import Device, DeviceStatus, device_status_is_online


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
            meta TEXT DEFAULT '{}',
            tenant_id TEXT DEFAULT 'default'
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            device_id TEXT DEFAULT '',
            severity TEXT NOT NULL,
            action_taken TEXT DEFAULT '',
            tenant_id TEXT DEFAULT 'default'
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
            min_interval_seconds INTEGER DEFAULT 60,
            tenant_id TEXT DEFAULT 'default'
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            device_id TEXT DEFAULT '',
            severity TEXT NOT NULL,
            action_taken TEXT DEFAULT '',
            tenant_id TEXT DEFAULT 'default'
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


def _make_device(temperature=70.0, hashrate_hs=1e12, status="ONLINE"):
    d = Device(
        id="test-dev",
        name="Test",
        model="bitaxe",
        ip="192.168.1.1",
        status=DeviceStatus[status],
    )
    d.current_telemetry = {"temperature": temperature, "hashrate_hs": hashrate_hs}
    return d


def _ensure_alert_rules_table(db_path):
    """Create the alert_rules table if it does not exist."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS alert_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        metric TEXT NOT NULL,
        operator TEXT NOT NULL,
        threshold REAL NOT NULL,
        severity TEXT NOT NULL,
        category TEXT NOT NULL,
        device_id TEXT DEFAULT NULL,
        model TEXT DEFAULT NULL,
        enabled INTEGER DEFAULT 1,
        cooldown_seconds INTEGER DEFAULT 300,
        tenant_id TEXT DEFAULT 'default'
    )""")
    conn.commit()
    conn.close()


def test_alert_engine_temperature_rule(alert_engine):
    device = _make_device(temperature=90.0)
    alerts = alert_engine.evaluate([device])
    assert any(a.category == "temperature" and a.severity == "CRIT" for a in alerts)


def test_alert_engine_no_crit_when_temperature_moderate(alert_engine):
    """50°C should not trigger any temperature alert — all temperature
    DEFAULT_RULES thresholds are > 55.0."""
    device = _make_device(temperature=50.0)
    alerts = alert_engine.evaluate([device])
    # No temperature alert expected at 50°C (below 55 threshold)
    temp_alerts = [a for a in alerts if a.category == "temperature"]
    assert len(temp_alerts) == 0, f"expected no temp alerts at 50°C, got {len(temp_alerts)}"


def test_alert_engine_pool_disconnect(alert_engine):
    alerts = alert_engine.evaluate([], pool={})
    assert any(a.category == "pool_disconnect" for a in alerts)


# ── Fase 5 · P1 fix: DeviceStatus is a str-Enum with LOWERCASE values ──
# Regression: _get_metric previously compared device.status == "ONLINE" (uppercase
# literal) which is ALWAYS False for core Device objects → every online device
# evaluated status as 0 and fired a false CRIT "status=0 == 0" offline alert.


def test_alert_engine_online_enum_device_does_not_fire_offline(alert_engine):
    """An ONLINE core device (DeviceStatus.ONLINE, value 'online') must NOT
    trigger the device_offline rule — the old uppercase literal comparison
    made this fire a false CRIT for every online device.
    temperature=50 isolates the status path (no temp alerts fire at 50°C)."""
    device = _make_device(status="ONLINE", temperature=50.0)
    alerts = alert_engine.evaluate([device])
    offline_alerts = [a for a in alerts if a.category == "device_offline"]
    assert len(offline_alerts) == 0, (
        f"online device fired false offline alert: {[a.message for a in offline_alerts]}"
    )


def test_alert_engine_offline_enum_device_fires_offline(alert_engine):
    """An OFFLINE core device (DeviceStatus.OFFLINE) must still fire the
    device_offline CRIT rule after the fix."""
    device = _make_device(status="OFFLINE", temperature=50.0)
    alerts = alert_engine.evaluate([device])
    offline_alerts = [a for a in alerts if a.category == "device_offline"]
    assert len(offline_alerts) == 1
    assert offline_alerts[0].severity == "CRIT"


def test_alert_engine_status_metric_normalizes_enum_and_string():
    """_get_metric must normalize BOTH the core str-Enum (lowercase value)
    and plain-string statuses ('ONLINE'/'online') to the same result."""
    online_enum = _make_device(status="ONLINE")
    assert AlertEngine._get_metric(online_enum, "status") == 1

    offline_enum = _make_device(status="OFFLINE")
    assert AlertEngine._get_metric(offline_enum, "status") == 0

    # Plain-string statuses (axe-fleet style: 'ONLINE' or 'online')
    str_device = _make_device(status="ONLINE")
    str_device.status = "ONLINE"
    assert AlertEngine._get_metric(str_device, "status") == 1

    str_device.status = "online"
    assert AlertEngine._get_metric(str_device, "status") == 1


def test_automation_engine_online_enum_device_status_metric():
    """AutomationEngine._get_metric has the same enum/string normalization —
    an online device must evaluate as 1 (no false offline trigger)."""
    online_enum = _make_device(status="ONLINE")
    assert AutomationEngine._get_metric(online_enum, "status") == 1

    offline_enum = _make_device(status="OFFLINE")
    assert AutomationEngine._get_metric(offline_enum, "status") == 0


def test_alert_engine_warning_device_does_not_fire_offline(alert_engine):
    """A WARNING device is degraded but REACHABLE — it must not fire the
    device_offline CRIT rule. Only truly offline statuses (OFFLINE,
    CRITICAL, MAINTENANCE, None) evaluate status=0."""
    device = _make_device(status="WARNING", temperature=50.0)
    alerts = alert_engine.evaluate([device])
    offline_alerts = [a for a in alerts if a.category == "device_offline"]
    assert len(offline_alerts) == 0, (
        f"warning device fired false offline alert: {[a.message for a in offline_alerts]}"
    )


def test_alert_engine_critical_and_maintenance_fire_offline(alert_engine):
    """CRITICAL and MAINTENANCE are NOT reachable — both must still fire the
    device_offline CRIT rule after the WARNING-as-online change.
    NOTE: _make_device() hardcodes id='test-dev', so each iteration must use
    a distinct device id — otherwise the engine's per-signature cooldown
    (device_offline:<id>, 300s) suppresses the second alert."""
    for status in ("CRITICAL", "MAINTENANCE"):
        device = _make_device(status=status, temperature=50.0)
        device.id = f"test-{status.lower()}"  # distinct sig → cooldown can't suppress
        alerts = alert_engine.evaluate([device])
        offline_alerts = [a for a in alerts if a.category == "device_offline"]
        assert len(offline_alerts) == 1, (
            f"{status} device should fire offline alert, got {len(offline_alerts)}"
        )


def test_device_status_is_online_shared_helper():
    """The shared helper is the single source of truth: enum + plain strings,
    WARNING counts as online, offline statuses (incl. None) do not."""
    assert device_status_is_online(DeviceStatus.ONLINE) is True
    assert device_status_is_online(DeviceStatus.WARNING) is True
    assert device_status_is_online("ONLINE") is True
    assert device_status_is_online("online") is True
    assert device_status_is_online("WARNING") is True
    assert device_status_is_online("HASHING") is True  # axe_fleet STATUS_HASHING
    assert device_status_is_online("hashing") is True
    assert device_status_is_online(DeviceStatus.OFFLINE) is False
    assert device_status_is_online(DeviceStatus.CRITICAL) is False
    assert device_status_is_online(DeviceStatus.MAINTENANCE) is False
    assert device_status_is_online("OFFLINE") is False
    assert device_status_is_online(None) is False


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


def test_automation_engine_evaluates_condition(automation_engine, monkeypatch):
    conn = sqlite3.connect(automation_engine.db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO automation_rules (name, target_device_id, condition_metric, condition_operator, condition_value, action_command) VALUES (?, ?, ?, ?, ?, ?)",
        ("hot", "test-dev", "temperature", ">", 85.0, "restart"),
    )
    conn.commit()
    conn.close()
    # P1 Auto-Pilot is FAIL-CLOSED: rules only execute when the pilot is
    # armed. Arm it (as the operator would via POST /api/automation/arm).
    monkeypatch.setattr(
        "core.alerts.automation_engine.AutomationEngine.is_armed",
        lambda self, tid="": True,
    )
    device = _make_device(temperature=90.0)
    results = automation_engine.evaluate_rules([device])
    assert len(results) == 1
    assert results[0]["status"] in ("blocked", "executed")


def test_automation_engine_cooldown_prevents_spam(automation_engine, monkeypatch):
    conn = sqlite3.connect(automation_engine.db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO automation_rules (name, target_device_id, condition_metric, condition_operator, condition_value, action_command, min_interval_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("hot", "test-dev", "temperature", ">", 85.0, "restart", 300),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "core.alerts.automation_engine.AutomationEngine.is_armed",
        lambda self, tid="": True,
    )
    device = _make_device(temperature=90.0)
    # First evaluation should trigger the rule
    assert len(automation_engine.evaluate_rules([device])) == 1
    # Immediate re-evaluation should be suppressed by the 5-minute cooldown
    assert len(automation_engine.evaluate_rules([device])) == 0


def test_automation_engine_unarmed_is_disarmed(automation_engine):
    """P1 fail-closed: WITHOUT arming, evaluation must NOT execute — it
    returns the disarmed marker instead of firing rules."""
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
    assert results == [{"status": "disarmed", "tenant_id": "default"}]


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


def test_alert_engine_default_rules_when_table_missing(alert_engine):
    """When alert_rules table does not exist, _load_rules() should fall back to
    copy.deepcopy(self._rules) i.e. DEFAULT_RULES."""
    rules = alert_engine.rules
    # Should return a list (the defaults, not empty)
    assert isinstance(rules, list)
    assert len(rules) > 0
    # Verify it's a deep copy (mutating the returned list should NOT affect the engine)
    rules_copy = alert_engine.rules
    original_len = len(rules_copy)
    rules_copy.clear()
    second_copy = alert_engine.rules
    assert len(second_copy) == original_len, "deep copy failed — mutating returned rules affected internal state"


def test_alert_engine_default_rules_when_table_empty(db_path):
    """When alert_rules table exists but has 0 rows, _load_rules() should
    return DEFAULT_RULES (the fallback code path)."""
    _ensure_alert_rules_table(db_path)

    engine = AlertEngine(db_path)
    rules = engine.rules
    assert isinstance(rules, list)
    # Table is empty, so should return DEFAULT_RULES
    assert len(rules) == len(AlertEngine.DEFAULT_RULES), \
        f"expected {len(AlertEngine.DEFAULT_RULES)} default rules, got {len(rules)}"

    # Verify the fallback path works: default rules have expected names
    rule_names = {r.name for r in rules}
    assert "temp_critical" in rule_names
    assert "hashrate_zero" in rule_names
    assert "device_offline" in rule_names
    assert "pool_disconnect" in rule_names


def test_alert_engine_custom_rules_loaded(db_path):
    """When alert_rules table has rows, _load_rules() should return
    the custom rules instead of DEFAULT_RULES."""
    _ensure_alert_rules_table(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO alert_rules (name, metric, operator, threshold, severity, category) VALUES (?, ?, ?, ?, ?, ?)",
        ("custom_temp", "temperature", ">", 80.0, "CRIT", "temperature"),
    )
    c.execute(
        "INSERT INTO alert_rules (name, metric, operator, threshold, severity, category) VALUES (?, ?, ?, ?, ?, ?)",
        ("custom_hr", "hashrate_hs", "==", 0, "CRIT", "hashrate_drop"),
    )
    conn.commit()
    conn.close()

    engine = AlertEngine(db_path)
    rules = engine.rules
    assert isinstance(rules, list)
    assert len(rules) == 2, f"expected 2 custom rules, got {len(rules)}"
    assert rules[0].name == "custom_temp"
    assert rules[0].threshold == 80.0
    assert rules[1].name == "custom_hr"
    assert rules[1].metric == "hashrate_hs"


def test_alert_engine_evaluate_uses_custom_rules(db_path):
    """Custom rules should be used by evaluate() instead of DEFAULT_RULES.
    Verify that a device with temperature=85 triggers a custom rule threshold of 80.0."""
    _ensure_alert_rules_table(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO alert_rules (name, metric, operator, threshold, severity, category) VALUES (?, ?, ?, ?, ?, ?)",
        ("custom_crit", "temperature", ">", 80.0, "CRIT", "temperature"),
    )
    conn.commit()
    conn.close()

    engine = AlertEngine(db_path)
    device = _make_device(temperature=85.0)
    alerts = engine.evaluate([device])

    # Should generate alert from the custom rule (temp 85 > 80)
    temp_alerts = [a for a in alerts if a.category == "temperature"]
    assert len(temp_alerts) == 1, f"expected 1 temp alert from custom rule, got {len(temp_alerts)}"
    assert temp_alerts[0].severity == "CRIT"
    assert "85.0" in temp_alerts[0].message


def test_automation_engine_logs_execution(automation_engine, monkeypatch):
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
    monkeypatch.setattr(
        "core.alerts.automation_engine.AutomationEngine.is_armed",
        lambda self, tid="": True,
    )
    device = _make_device(temperature=90.0)
    automation_engine.evaluate_rules([device])
    conn = sqlite3.connect(automation_engine.db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM automation_execution_log WHERE device_id=? ORDER BY ts DESC", (device.id,))
    rows = c.fetchall()
    conn.close()
    assert len(rows) >= 1
