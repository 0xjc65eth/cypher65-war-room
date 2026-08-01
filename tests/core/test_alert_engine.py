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
