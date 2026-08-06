"""Tests for the deadlock-prevention layer in the automation engine.

Two conflicting rules firing on the SAME device in one cycle must never both
execute: higher priority wins, ties cancel both, non-conflicting rules survive,
and cancelled rules record their cooldown (no audit spam).
"""
from core.alerts.automation_engine import AutomationEngine, AutomationRule
from core.models.device import Device
from core.safety.safety_engine import SafetyEngine


def _mk_rule(rid, name, action, priority=0):
    return AutomationRule(
        id=rid, name=name, target_device_id="dev-1",
        condition_metric="temperature", condition_operator=">",
        condition_value=80, action_command=action,
        action_parameters={}, priority=priority,
    )


def _mk_engine():
    safety = SafetyEngine()
    engine = AutomationEngine(db_path=":memory:", safety_engine=safety)
    # Bypass DB loading: feed rules directly to the resolver.
    return engine


def _device():
    return Device(id="dev-1", name="miner")


def test_higher_priority_wins_conflict():
    engine = _mk_engine()
    high = _mk_rule(1, "cool-down", "underclock", priority=10)
    low = _mk_rule(2, "boost", "overclock", priority=1)
    survivors = engine._resolve_conflicts([(high, _device()), (low, _device())])
    assert [(r.id) for r, _ in survivors] == [1]


def test_tie_cancels_both():
    engine = _mk_engine()
    a = _mk_rule(1, "rule-a", "overclock", priority=5)
    b = _mk_rule(2, "rule-b", "underclock", priority=5)
    survivors = engine._resolve_conflicts([(a, _device()), (b, _device())])
    assert survivors == []


def test_same_action_twice_is_not_conflict():
    engine = _mk_engine()
    a = _mk_rule(1, "a", "overclock", priority=5)
    b = _mk_rule(2, "b", "overclock", priority=1)
    survivors = engine._resolve_conflicts([(a, _device()), (b, _device())])
    assert len(survivors) == 2


def test_non_conflicting_rules_both_survive():
    engine = _mk_engine()
    a = _mk_rule(1, "a", "restart", priority=5)
    b = _mk_rule(2, "b", "identify", priority=5)
    survivors = engine._resolve_conflicts([(a, _device()), (b, _device())])
    assert len(survivors) == 2


def test_cancelled_rule_records_cooldown():
    engine = _mk_engine()
    now = 1_700_000_000
    high = _mk_rule(1, "cool", "underclock", priority=10)
    low = _mk_rule(2, "boost", "overclock", priority=1)
    dev = _device()
    engine._resolve_conflicts([(high, dev), (low, dev)], now=now)
    assert engine._last_fired.get("2:dev-1") == now  # loser got cooldown
    assert "1:dev-1" not in engine._last_fired  # winner fires via _execute


# ═══════════════════════════════════════════════════════════════════════════
#  P1 Auto-Pilot — preview_rules() (read-only advisory, never executes)
# ═══════════════════════════════════════════════════════════════════════════

def _mk_preview_rule(rid, name, metric, op, value, action="underclock",
                     target="dev-1", enabled=True, min_interval=60, tenant="default"):
    return AutomationRule(
        id=rid, name=name, target_device_id=target,
        condition_metric=metric, condition_operator=op,
        condition_value=value, action_command=action,
        action_parameters={}, is_enabled=enabled,
        min_interval_seconds=min_interval, tenant_id=tenant,
    )


def _preview_device(dev_id="dev-1", telemetry=None, status=None):
    from core.models.device import DeviceStatus
    dev = Device(id=dev_id, name=dev_id)
    dev.current_telemetry = dict(telemetry or {})
    if status is not None:
        dev.status = status
    else:
        dev.status = DeviceStatus.ONLINE
    return dev


def _mk_preview_engine(tmp_path, *rules):
    """P1 — engine whose DB is seeded with the given rules.

    preview_rules() (like load_rules/evaluate_rules) reads rules from the
    sqlite DB — that's how app.py drives it (`_automation_engine.preview_rules`
    against the persisted automation_rules table). These tests therefore seed
    the rules into a scratch DB instead of feeding them in memory, mirroring
    the established pattern in tests/core/test_alert_engine.py.
    """
    import json
    import sqlite3
    db = str(tmp_path / "preview.sqlite")
    conn = sqlite3.connect(db)
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
            tenant_id TEXT DEFAULT 'default',
            priority INTEGER DEFAULT 0
        )"""
    )
    for r in rules:
        c.execute(
            "INSERT INTO automation_rules (id, name, target_device_id, condition_metric, "
            "condition_operator, condition_value, action_command, action_parameters, "
            "is_enabled, min_interval_seconds, tenant_id, priority) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r.id, r.name, r.target_device_id, r.condition_metric,
                r.condition_operator, float(r.condition_value), r.action_command,
                json.dumps(r.action_parameters or {}),
                1 if r.is_enabled else 0, r.min_interval_seconds,
                r.tenant_id, r.priority,
            ),
        )
    conn.commit()
    conn.close()
    return AutomationEngine(db_path=db, safety_engine=SafetyEngine())


class TestPreviewRules:
    """P1 — preview_rules() must say what WOULD fire without executing:
    no execute_command_callback invocation, no safety validation side
    effects, respects cooldown + tenant scoping."""

    def test_matching_rule_appears_in_preview(self, tmp_path):
        engine = _mk_preview_engine(
            tmp_path, _mk_preview_rule(1, "cool-down", "temperature", ">", 80))
        dev = _preview_device(telemetry={"temperature": 90})
        preview = engine.preview_rules([dev], tenant_id="default")
        assert len(preview) == 1
        assert preview[0]["rule_name"] == "cool-down"
        assert preview[0]["action_command"] == "underclock"
        assert preview[0]["device_id"] == "dev-1"

    def test_non_matching_condition_not_previewed(self, tmp_path):
        engine = _mk_preview_engine(
            tmp_path, _mk_preview_rule(1, "cool-down", "temperature", ">", 80))
        dev = _preview_device(telemetry={"temperature": 60})
        assert engine.preview_rules([dev], tenant_id="default") == []

    def test_missing_telemetry_not_previewed(self, tmp_path):
        engine = _mk_preview_engine(
            tmp_path, _mk_preview_rule(1, "cool-down", "temperature", ">", 80))
        dev = _preview_device(telemetry={})
        assert engine.preview_rules([dev], tenant_id="default") == []

    def test_device_not_registered_skipped(self, tmp_path):
        engine = _mk_preview_engine(
            tmp_path, _mk_preview_rule(1, "cool-down", "temperature", ">", 80, target="ghost"))
        dev = _preview_device(telemetry={"temperature": 90})
        assert engine.preview_rules([dev], tenant_id="default") == []

    def test_preview_never_executes(self, tmp_path):
        """THE advisory guard: preview must NOT call the execute callback."""
        calls = []
        engine = _mk_preview_engine(
            tmp_path, _mk_preview_rule(1, "cool-down", "temperature", ">", 80))
        engine.execute_command_callback = lambda *a, **k: calls.append(a)
        dev = _preview_device(telemetry={"temperature": 95})
        engine.preview_rules([dev], tenant_id="default")
        assert calls == []

    def test_preview_never_audits(self, tmp_path):
        """Read-only: no audit rows, no _last_fired mutation."""
        engine = _mk_preview_engine(
            tmp_path, _mk_preview_rule(1, "cool-down", "temperature", ">", 80))
        audited = []
        engine.audit_callback = lambda **k: audited.append(k)
        dev = _preview_device(telemetry={"temperature": 95})
        engine.preview_rules([dev], tenant_id="default")
        assert audited == []
        assert engine._last_fired == {}

    def test_cooldown_blocks_preview(self, tmp_path):
        """A rule that fired recently (within min_interval_seconds) must not
        appear in the preview — same cooldown semantics as real execution."""
        engine = _mk_preview_engine(
            tmp_path, _mk_preview_rule(1, "cool-down", "temperature", ">", 80, min_interval=60))
        dev = _preview_device(telemetry={"temperature": 95})
        now = int(__import__("time").time())
        engine._last_fired["1:dev-1"] = now - 10  # fired 10s ago (< 60s cooldown)
        assert engine.preview_rules([dev], tenant_id="default") == []
        # After the cooldown window it would fire again.
        engine._last_fired["1:dev-1"] = now - 120
        assert len(engine.preview_rules([dev], tenant_id="default")) == 1

    def test_tenant_scoping(self, tmp_path):
        """preview_rules(tenant_id) must only evaluate that tenant's rules."""
        engine = _mk_preview_engine(
            tmp_path,
            _mk_preview_rule(1, "acme-rule", "temperature", ">", 80, tenant="acme"),
            _mk_preview_rule(2, "brave-rule", "temperature", ">", 80, tenant="brave"),
        )
        dev = _preview_device(telemetry={"temperature": 95})
        acme = engine.preview_rules([dev], tenant_id="acme")
        brave = engine.preview_rules([dev], tenant_id="brave")
        assert [p["rule_name"] for p in acme] == ["acme-rule"]
        assert [p["rule_name"] for p in brave] == ["brave-rule"]

    def test_status_metric_supported(self, tmp_path):
        engine = _mk_preview_engine(
            tmp_path, _mk_preview_rule(1, "offline-check", "status", "==", 0, action="restart"))
        dev = _preview_device(status="offline")
        preview = engine.preview_rules([dev], tenant_id="default")
        assert len(preview) == 1
        assert preview[0]["action_command"] == "restart"
