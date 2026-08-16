"""Hermetic tests for Issue #178 — Auto-Pilot Fase 4 (execução autônoma).

Covers:
  1. services.licensing.server_pro_active: open mode True · licensed without
     server key False · licensed with valid AUTO_PILOT_PRO_KEY True.
  2. auto_pilot_autonomous settings: default OFF, save/load roundtrip.
  3. execute_autonomous_actions (fail-closed gates):
       - pro gate / not armed / not enabled → skipped, NOTHING executes
       - full gate open + restart rec → executed via execute_fn + audited
         (note="autonomous") + cooldown (2nd call → cooldown)
       - blacklist rec → NEVER auto-executed (finance stays manual)
       - tenant budget exhausted → rate_limited
       - SafetyEngine blocked → blocked + audited (never executes)
  4. Routes: GET status · POST open mode 200 · POST licensed sem chave 402 ·
     POST licensed com X-License-Key válida 200.
"""

import sys

import pytest

sys.path.insert(0, ".")

# Importing `app` runs init_db() at module scope → creates the `settings`
# table in the conftest scratch DB (same pattern as test_settings_test_alert).
from app import app as _app  # noqa: E402,F401
import services.auto_pilot as ap  # noqa: E402


# ── Fakes ─────────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, allowed=True, reason=""):
        self.allowed = allowed
        self.reason = reason


class _FakeSafety:
    def __init__(self, allowed=True, reason=""):
        self.allowed = allowed
        self.reason = reason

    def validate_command(self, device, command, params):
        return _FakeResult(self.allowed, self.reason)


class _FakeEngine:
    """Interface mínima que o executor autônomo usa (is_armed + budget +
    safety_engine). Hermético — sem DB, sem rede."""

    def __init__(self, armed=True, budget=True, safety_allowed=True, safety_reason=""):
        self.armed = armed
        self.budget = budget
        self.consumed = 0
        self.safety_engine = _FakeSafety(safety_allowed, safety_reason)

    def is_armed(self, tenant_id):
        return self.armed

    def _consume_action_budget(self, tenant_id, now):
        if not self.budget:
            return False
        self.consumed += 1
        return True


def _device(did="dev-1", status="OFFLINE"):
    return {
        "id": did,
        "name": did,
        "status": status,
        "capabilities": {"restart": True, "pause": True},
        "telemetry": {"temperature": 75, "hashrate_hs": 0},
    }


def _rec_restart(did="dev-1"):
    return {
        "id": "ap-offline-" + did,
        "device_id": did,
        "device_name": did,
        "issue_type": "offline",
        "severity": "crit",
        "message": "offline",
        "action": {"type": "restart", "label": "REINICIAR"},
    }


def _rec_pause(did="dev-2"):
    return {
        "id": "ap-temp_high-" + did,
        "device_id": did,
        "device_name": did,
        "issue_type": "temp_high",
        "severity": "warn",
        "message": "hot",
        "action": {"type": "pause", "label": "PAUSAR"},
    }


def _rec_blacklist():
    return {
        "id": "ap-rig_poor-r1",
        "device_id": "r1",
        "device_name": "r1",
        "issue_type": "rig_poor",
        "severity": "warn",
        "message": "poor",
        "action": {"type": "blacklist", "label": "BLACKLIST RIG"},
    }


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Limpa o cooldown compartilhado + garante autonomous OFF por teste.

    O DB scratch é compartilhado entre testes do mesmo arquivo, então o
    toggle precisa voltar a OFF antes de cada teste (especialmente antes
    do teste 402 que verifica "never persisted").
    """
    from services.settings import invalidate_cache

    with ap._autonomous_lock:
        ap._autonomous_cooldown.clear()
    # Audit trail é persistido no DB scratch compartilhado → limpar antes
    # de cada teste (senão get_rec_audit vaza entradas de testes anteriores).
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
    ap.set_autonomous_enabled("default", False)
    invalidate_cache()
    yield
    with ap._autonomous_lock:
        ap._autonomous_cooldown.clear()
    ap.set_autonomous_enabled("default", False)
    invalidate_cache()


@pytest.fixture()
def isolated_client():
    import app as _app_module

    _app_module.app.config["TESTING"] = True
    return _app_module.app.test_client()


def _enable_autonomous():
    assert ap.set_autonomous_enabled("default", True) is True
    assert ap.is_autonomous_enabled("default") is True


# ── server_pro_active ─────────────────────────────────────────────────────


def test_server_pro_active_open_mode():
    from services.licensing import server_pro_active

    assert server_pro_active() is True  # no licensing env → operator owns it


def test_server_pro_active_licensed_without_server_key(monkeypatch):
    from services.licensing import server_pro_active

    monkeypatch.setenv("PRO_LICENSE_KEYS", "k1,k2")
    assert server_pro_active() is False  # no AUTO_PILOT_PRO_KEY


def test_server_pro_active_licensed_with_valid_server_key(monkeypatch):
    from services.licensing import server_pro_active

    monkeypatch.setenv("PRO_LICENSE_KEYS", "k1,k2")
    monkeypatch.setenv("AUTO_PILOT_PRO_KEY", "k2")
    assert server_pro_active() is True


def test_server_pro_active_licensed_with_invalid_server_key(monkeypatch):
    from services.licensing import server_pro_active

    monkeypatch.setenv("PRO_LICENSE_KEYS", "k1,k2")
    monkeypatch.setenv("AUTO_PILOT_PRO_KEY", "k9")
    assert server_pro_active() is False


# ── settings toggle ───────────────────────────────────────────────────────


def test_autonomous_setting_defaults_off():
    assert ap.is_autonomous_enabled("default") is False
    assert ap.is_autonomous_enabled("acme") is False


def test_autonomous_setting_roundtrip():
    assert ap.set_autonomous_enabled("default", True) is True
    assert ap.is_autonomous_enabled("default") is True
    assert ap.set_autonomous_enabled("default", False) is True
    assert ap.is_autonomous_enabled("default") is False
    # Tenant-scoped: another tenant stays off.
    assert ap.set_autonomous_enabled("acme", True) is True
    assert ap.is_autonomous_enabled("default") is False
    assert ap.is_autonomous_enabled("acme") is True


def test_autonomous_status_shape():
    st = ap.autonomous_status("default")
    assert set(st) >= {"pro", "armed", "autonomous", "safe_actions", "cooldowns"}
    assert "restart" in st["safe_actions"]
    assert st["cooldowns"]["restart"] > 0


# ── execute_autonomous_actions — gates fail-closed ────────────────────────


def test_execute_pro_gate_closed_skips(monkeypatch):
    monkeypatch.setenv("PRO_LICENSE_KEYS", "k1")  # licensed, no server key
    out = ap.execute_autonomous_actions(
        "default", engine=_FakeEngine(armed=True), execute_fn=lambda d, c: {"ok": True}
    )
    assert out[0]["status"] == "skipped" and out[0]["reason"] == "pro_gate"


def test_execute_not_armed_skips():
    out = ap.execute_autonomous_actions(
        "default", engine=_FakeEngine(armed=False), execute_fn=lambda d, c: {"ok": True}
    )
    assert out[0]["status"] == "skipped" and out[0]["reason"] == "not_armed"


def test_execute_not_enabled_skips():
    # autonomous toggle OFF (default) — even armed + pro open mode.
    out = ap.execute_autonomous_actions(
        "default", engine=_FakeEngine(armed=True), execute_fn=lambda d, c: {"ok": True}
    )
    assert out[0]["status"] == "skipped" and out[0]["reason"] == "not_enabled"


# ── execute_autonomous_actions — happy path + guards ──────────────────────


def test_execute_runs_restart_and_audits():
    _enable_autonomous()
    calls = []
    out = ap.execute_autonomous_actions(
        "default",
        engine=_FakeEngine(armed=True),
        execute_fn=lambda d, c: calls.append((d, c)) or {"ok": True},
        recs=[_rec_restart()],
        fleet=[_device()],
    )
    assert calls == [("dev-1", "restart")]
    assert out[0]["status"] == "executed"
    # Audited with note="autonomous" (decision=accept).
    audit = ap.get_rec_audit("default")
    assert any(r["note"] == "autonomous" and r["device_id"] == "dev-1" for r in audit)


def test_execute_cooldown_blocks_repeat():
    _enable_autonomous()
    calls = []
    fn = lambda d, c: calls.append((d, c)) or {"ok": True}  # noqa: E731
    ap.execute_autonomous_actions(
        "default",
        engine=_FakeEngine(armed=True),
        execute_fn=fn,
        recs=[_rec_restart()],
        fleet=[_device()],
    )
    # Second call in the same window → cooldown (restart 15min), no execution.
    out = ap.execute_autonomous_actions(
        "default",
        engine=_FakeEngine(armed=True),
        execute_fn=fn,
        recs=[_rec_restart()],
        fleet=[_device()],
    )
    assert out[0]["status"] == "cooldown"
    assert len(calls) == 1  # only the first run executed


def test_execute_never_auto_blacklists():
    """Ações financeiras (blacklist) NUNCA auto-executam."""
    _enable_autonomous()
    calls = []
    out = ap.execute_autonomous_actions(
        "default",
        engine=_FakeEngine(armed=True),
        execute_fn=lambda d, c: calls.append((d, c)) or {"ok": True},
        recs=[_rec_blacklist()],
        fleet=[],
    )
    assert out == []  # rec skipped silently (finance stays manual)
    assert calls == []
    assert ap.get_rec_audit("default") == []  # nothing audited


def test_execute_budget_exhausted_rate_limited():
    _enable_autonomous()
    out = ap.execute_autonomous_actions(
        "default",
        engine=_FakeEngine(armed=True, budget=False),
        execute_fn=lambda d, c: {"ok": True},
        recs=[_rec_restart()],
        fleet=[_device()],
    )
    assert out[0]["status"] == "rate_limited"


def test_execute_safety_blocked_audits():
    _enable_autonomous()
    out = ap.execute_autonomous_actions(
        "default",
        engine=_FakeEngine(
            armed=True, safety_allowed=False, safety_reason="temp too high"
        ),
        execute_fn=lambda d, c: {"ok": True},
        recs=[_rec_restart()],
        fleet=[_device()],
    )
    assert out[0]["status"] == "blocked"
    audit = ap.get_rec_audit("default")
    assert any(r["note"] == "autonomous:blocked" for r in audit)


def test_execute_error_propagates_audit():
    _enable_autonomous()

    def _boom(d, c):
        raise RuntimeError("conn refused")

    out = ap.execute_autonomous_actions(
        "default",
        engine=_FakeEngine(armed=True),
        execute_fn=_boom,
        recs=[_rec_restart()],
        fleet=[_device()],
    )
    assert out[0]["status"] == "error"
    assert "conn refused" in out[0]["reason"]
    audit = ap.get_rec_audit("default")
    assert any(r["note"] == "autonomous:error" for r in audit)


# ── Routes ────────────────────────────────────────────────────────────────


def test_autonomous_status_route(isolated_client):
    resp = isolated_client.get("/api/auto-pilot/autonomous")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "autonomous" in data and "pro" in data and "armed" in data


def test_autonomous_enable_open_mode(isolated_client, _reset_state):
    resp = isolated_client.post("/api/auto-pilot/autonomous", json={"autonomous": True})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert ap.is_autonomous_enabled("default") is True


def test_autonomous_enable_licensed_without_key_402(
    isolated_client, monkeypatch, _reset_state
):
    monkeypatch.setenv("PRO_LICENSE_KEYS", "k1")
    resp = isolated_client.post("/api/auto-pilot/autonomous", json={"autonomous": True})
    assert resp.status_code == 402
    assert resp.get_json()["code"] == "LICENSE_REQUIRED"
    assert ap.is_autonomous_enabled("default") is False  # never persisted


def test_autonomous_enable_licensed_with_key(
    isolated_client, monkeypatch, _reset_state
):
    monkeypatch.setenv("PRO_LICENSE_KEYS", "k1")
    resp = isolated_client.post(
        "/api/auto-pilot/autonomous",
        json={"autonomous": True},
        headers={"X-License-Key": "k1"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_autonomous_disable_always_allowed(isolated_client, monkeypatch, _reset_state):
    monkeypatch.setenv("PRO_LICENSE_KEYS", "k1")
    # Disabling (kill switch) must work even without a key.
    resp = isolated_client.post(
        "/api/auto-pilot/autonomous", json={"autonomous": False}
    )
    assert resp.status_code == 200
