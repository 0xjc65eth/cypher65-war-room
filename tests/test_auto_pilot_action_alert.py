"""Hermetic tests for Issue #180 — Auto-Pilot action alert.

When the autonomous pilot (Fase 4, Issue #178) REALLY executes a physical
action (restart/pause/underclock), the tenant opted into
auto_pilot_action_alert gets webhook + push ("restart executado pelo
Auto-Pilot"). Covers:
  1. build_autonomous_action_alerts: opt-in OFF → none; ON → one alert per
     EXECUTED result (WARN / auto_pilot_action / device name in message);
     blocked/cooldown/rate_limited/error/skipped NEVER alert; junk never
     raises.
  2. dispatch_autonomous_action_alerts: reuses the shared tenant family
     dispatcher (webhook+push com as settings DO tenant); empty short-circuits.
  3. Integration: execute_autonomous_actions → executed result carries the
     resolved device name → dispatch builds the alert with the fleet name.
"""

import sys

import pytest

sys.path.insert(0, ".")

# Importing `app` runs init_db() at module scope → creates the `settings`
# table in the conftest scratch DB (same pattern as test_auto_pilot_autonomous).
from app import app as _app  # noqa: E402,F401
import services.auto_pilot as ap  # noqa: E402
import services.user_polling as up  # noqa: E402
from services.settings import (
    invalidate_cache,
    load_settings,
    save_setting,
)  # noqa: E402

_EXECUTED = {
    "rec_id": "r1",
    "device_id": "dev-01",
    "device_name": "MINER-01",
    "action": "restart",
    "status": "executed",
    "reason": "",
    "ts": 1700000000,
}


def _enable_alert():
    save_setting(ap.AUTO_PILOT_ACTION_ALERT_SETTING, "1", tenant_id="default")
    invalidate_cache(tenant_id="default")


@pytest.fixture(autouse=True)
def _reset_state():
    """Isola o DB scratch compartilhado: alerta OFF + autonomous OFF por teste."""
    with ap._autonomous_lock:
        ap._autonomous_cooldown.clear()
    try:
        from services.db import get_db

        conn = get_db()
        ap._ensure_audit_table(conn)
        conn.execute(
            "DELETE FROM %s WHERE tenant_id IN ('default','acme')" % ap.AP_AUDIT_TABLE
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    try:
        save_setting(ap.AUTO_PILOT_ACTION_ALERT_SETTING, "0", tenant_id="default")
        ap.set_autonomous_enabled("default", False)
    except Exception:
        pass
    invalidate_cache(tenant_id="default")
    yield
    try:
        save_setting(ap.AUTO_PILOT_ACTION_ALERT_SETTING, "0", tenant_id="default")
    except Exception:
        pass
    invalidate_cache(tenant_id="default")


# ── build_autonomous_action_alerts ───────────────────────────────────────


def test_opt_in_off_returns_no_alerts():
    assert ap.build_autonomous_action_alerts([_EXECUTED], tenant_id="default") == []


def test_opt_in_on_builds_executed_alert():
    _enable_alert()
    alerts = ap.build_autonomous_action_alerts([_EXECUTED], tenant_id="default")
    assert len(alerts) == 1
    a = alerts[0]
    assert a["severity"] == "WARN"
    assert a["category"] == "auto_pilot_action"
    assert "restart" in a["message"] and "MINER-01" in a["message"]
    assert a["ts"] == _EXECUTED["ts"]


def test_alert_uses_device_name_when_present():
    _enable_alert()
    alerts = ap.build_autonomous_action_alerts([_EXECUTED], tenant_id="default")
    assert "MINER-01" in alerts[0]["message"]
    # Sem device_name → cai para o id (nunca quebra).
    no_name = {k: v for k, v in _EXECUTED.items() if k != "device_name"}
    alerts = ap.build_autonomous_action_alerts([no_name], tenant_id="default")
    assert "dev-01" in alerts[0]["message"]


def test_only_executed_status_alerts():
    _enable_alert()
    others = [
        {**_EXECUTED, "status": "blocked", "reason": "safety"},
        {**_EXECUTED, "status": "cooldown"},
        {**_EXECUTED, "status": "rate_limited", "reason": "budget"},
        {**_EXECUTED, "status": "error", "reason": "boom"},
        {**_EXECUTED, "status": "skipped"},
    ]
    assert ap.build_autonomous_action_alerts(others, tenant_id="default") == []
    combined = ap.build_autonomous_action_alerts(
        [_EXECUTED] + others, tenant_id="default"
    )
    assert len(combined) == 1


def test_never_raises_on_junk():
    _enable_alert()
    assert ap.build_autonomous_action_alerts(None, tenant_id="default") == []
    assert ap.build_autonomous_action_alerts([], tenant_id="default") == []
    assert (
        ap.build_autonomous_action_alerts(
            [None, {}, {"status": "executed"}, "junk"], tenant_id="default"
        )
        == []
    )


# ── dispatch_autonomous_action_alerts ────────────────────────────────────


def test_dispatch_uses_shared_tenant_family(monkeypatch):
    _enable_alert()
    calls = []

    def fake_family(tid, alerts):
        calls.append((tid, alerts))

    monkeypatch.setattr(up, "_dispatch_tenant_alert_family", fake_family)
    up.dispatch_autonomous_action_alerts("default", [_EXECUTED])
    assert len(calls) == 1
    tid, alerts = calls[0]
    assert tid == "default"
    assert len(alerts) == 1
    assert alerts[0]["category"] == "auto_pilot_action"


def test_dispatch_short_circuits_on_empty(monkeypatch):
    _enable_alert()
    called = []

    def fake_family(tid, alerts):
        called.append(1)

    monkeypatch.setattr(up, "_dispatch_tenant_alert_family", fake_family)
    up.dispatch_autonomous_action_alerts("default", [])
    up.dispatch_autonomous_action_alerts("default", None)
    assert called == []


def test_dispatch_respects_opt_in(monkeypatch):
    # Opt-in OFF → dispatcher receives NO alerts (build returns []).
    calls = []

    def fake_family(tid, alerts):
        calls.append((tid, alerts))

    monkeypatch.setattr(up, "_dispatch_tenant_alert_family", fake_family)
    up.dispatch_autonomous_action_alerts("default", [_EXECUTED])
    assert calls == []


# ── Integração: executor → resultado com nome do device → alerta ─────────


class _FakeResult:
    def __init__(self, allowed=True, reason=""):
        self.allowed = allowed
        self.reason = reason


class _FakeSafety:
    def validate_command(self, device, command, params):
        return _FakeResult(True, "")


class _FakeEngine:
    def __init__(self, budget=999):
        self._budget = budget
        self.safety_engine = _FakeSafety()

    def is_armed(self, tenant_id):
        return True

    def _consume_action_budget(self, tenant_id, now):
        if self._budget <= 0:
            return False
        self._budget -= 1
        return True


def _rec_restart(did="dev-01"):
    return {
        "id": "ap-offline-" + did,
        "device_id": did,
        "device_name": "MINER-01",
        "issue_type": "offline",
        "severity": "crit",
        "message": "offline",
        "action": {"type": "restart", "label": "REINICIAR"},
    }


def test_executor_execution_feeds_alert_with_fleet_name(monkeypatch):
    """End-to-end: o executor executa restart (gates abertos), o resultado
    carrega o NOME real do device do fleet, e o dispatch gera o alerta
    'Auto-Pilot: restart executado em MINER-01' via family compartilhado."""
    _enable_alert()
    ap.set_autonomous_enabled("default", True)
    invalidate_cache(tenant_id="default")

    executed = []
    dispatch_calls = []

    def fake_execute(did, atype):
        executed.append((did, atype))
        return {"ok": True}

    def fake_family(tid, alerts):
        dispatch_calls.append((tid, alerts))

    monkeypatch.setattr(up, "_dispatch_tenant_alert_family", fake_family)

    results = ap.execute_autonomous_actions(
        tenant_id="default",
        engine=_FakeEngine(),
        execute_fn=fake_execute,
        recs=[_rec_restart()],
        fleet=[{"id": "dev-01", "name": "MINER-01"}],
        now=1700000000,
    )
    assert executed == [("dev-01", "restart")]
    assert results[0]["status"] == "executed"
    assert results[0]["device_name"] == "MINER-01"

    up.dispatch_autonomous_action_alerts("default", results)
    assert len(dispatch_calls) == 1
    alerts = dispatch_calls[0][1]
    assert len(alerts) == 1
    assert "restart" in alerts[0]["message"]
    assert "MINER-01" in alerts[0]["message"]


def test_executor_error_result_does_not_alert(monkeypatch):
    """Execução que FALHA (outcome ok=False) vira status error — nunca alerta."""
    _enable_alert()
    ap.set_autonomous_enabled("default", True)
    invalidate_cache(tenant_id="default")
    dispatch_calls = []

    def fake_execute(did, atype):
        return {"ok": False, "error": "boom"}

    def fake_family(tid, alerts):
        dispatch_calls.append((tid, alerts))

    monkeypatch.setattr(up, "_dispatch_tenant_alert_family", fake_family)

    results = ap.execute_autonomous_actions(
        tenant_id="default",
        engine=_FakeEngine(),
        execute_fn=fake_execute,
        recs=[_rec_restart()],
        fleet=[{"id": "dev-01", "name": "MINER-01"}],
        now=1700000000,
    )
    assert results[0]["status"] == "error"

    up.dispatch_autonomous_action_alerts("default", results)
    assert dispatch_calls == []


def test_settings_default_is_off():
    assert load_settings(tenant_id="default").get(
        ap.AUTO_PILOT_ACTION_ALERT_SETTING
    ) in (
        "0",
        "",
        None,
    )
