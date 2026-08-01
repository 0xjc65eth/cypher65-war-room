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
