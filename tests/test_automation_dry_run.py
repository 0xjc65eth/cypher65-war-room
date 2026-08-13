"""Tests for Issue #76 — Auto-Pilot Fase 3 dry-run (execução simulada).

Covers:
  1. dry_run_rules() — simulates the armed pilot on CURRENT telemetry with
     ZERO side effects (no execute, no audit, no cooldown/budget consumed),
     predicted outcomes, SafetyEngine verdicts, conflict cancellation and
     budget status.
  2. simulate_replay_window() — pure 24h replay over telemetry history
     (cooldown + conflicts + budget).
  3. Routes GET /api/automation/dry-run + /dry-run/replay (tenant-scoped).
  4. axe_fleet_to_device() bridge (axe dict → core Device with aliases).
"""
import time

from unittest.mock import MagicMock, patch

import pytest

from core.alerts.automation_engine import AutomationEngine, AutomationRule
from core.models.device import Device, DeviceStatus
from core.safety.safety_engine import SafetyEngine
from services.auto_pilot import axe_fleet_to_device


def _rule(rid, name="temp-rule", action="restart", metric="temperature",
          op=">", value=60, target="dev-1", priority=0, min_interval=60,
          tenant="default"):
    return AutomationRule(
        id=rid, name=name, target_device_id=target,
        condition_metric=metric, condition_operator=op,
        condition_value=value, action_command=action,
        action_parameters={}, priority=priority,
        min_interval_seconds=min_interval, tenant_id=tenant,
    )


def _device(dev_id="dev-1", temp=70.0):
    """ONLINE device, temp 70°C — fires a >60 rule AND passes Safety
    (max_temperature=85), so the restart verdict is 'approved'."""
    dev = Device(id=dev_id, name="miner-" + dev_id, status=DeviceStatus.ONLINE)
    dev.current_telemetry = {"temperature": temp, "hashrate": 1e12}
    return dev


def _engine(armed=False, load_rules_return=None):
    safety = SafetyEngine()
    engine = AutomationEngine(db_path=":memory:", safety_engine=safety)
    engine.is_armed = lambda tenant_id="": armed
    engine.load_rules = lambda tenant_id="": (load_rules_return or [])
    engine.execute_command_callback = MagicMock()
    engine.audit_callback = MagicMock()
    return engine


# ══════════════════════════════════════════════════════════════════════════
# 1. dry_run_rules — zero side effects
# ══════════════════════════════════════════════════════════════════════════
class TestDryRunRules:
    def test_simulates_action_with_outcome_and_safety(self):
        engine = _engine(load_rules_return=[_rule(1)])
        out = engine.dry_run_rules([_device()], tenant_id="t1")
        assert out["simulated"] is True
        assert out["count"] == 1
        assert out["would_execute"] == 1
        a = out["actions"][0]
        assert a["rule_id"] == 1
        assert a["device_id"] == "dev-1"
        assert a["condition_metric"] == "temperature"
        assert a["actual_value"] == 70.0
        assert "reinicia" in a["predicted_outcome"]  # restart outcome
        assert a["safety_verdict"] == "approved"
        assert a["budget"] == "would_consume"
        assert a["conflict"] is None

    def test_runs_even_when_disarmed(self):
        """The whole point: rehearse BEFORE arming."""
        engine = _engine(armed=False, load_rules_return=[_rule(1)])
        out = engine.dry_run_rules([_device()], tenant_id="t1")
        assert out["armed"] is False
        assert out["count"] == 1

    def test_never_executes_nor_audits(self):
        engine = _engine(load_rules_return=[_rule(1)])
        engine.dry_run_rules([_device()], tenant_id="t1")
        engine.execute_command_callback.assert_not_called()
        engine.audit_callback.assert_not_called()

    def test_does_not_consume_cooldown_or_budget(self):
        """Two consecutive dry-runs must both fire (simulation mutates nothing)."""
        engine = _engine(load_rules_return=[_rule(1, min_interval=600)])
        out1 = engine.dry_run_rules([_device()], tenant_id="t1")
        out2 = engine.dry_run_rules([_device()], tenant_id="t1")
        assert out1["count"] == 1 and out2["count"] == 1
        assert engine._last_fired == {}
        assert engine._action_history.get("t1", []) == []

    def test_condition_not_met_yields_zero(self):
        engine = _engine(load_rules_return=[_rule(1)])
        assert engine.dry_run_rules([_device(temp=50.0)], tenant_id="t1")["count"] == 0

    def test_blocked_by_safety_reports_verdict(self):
        engine = _engine(load_rules_return=[_rule(1)])
        dev = _device()
        dev.status = DeviceStatus.OFFLINE  # SafetyEngine blocks offline devices
        out = engine.dry_run_rules([dev], tenant_id="t1")
        assert out["count"] == 1
        assert out["actions"][0]["safety_verdict"] == "blocked"

    def test_conflict_cancels_loser(self):
        high = _rule(1, name="cool", action="underclock", priority=10)
        low = _rule(2, name="boost", action="overclock", priority=1)
        engine = _engine(load_rules_return=[high, low])
        out = engine.dry_run_rules([_device()], tenant_id="t1")
        assert out["would_execute"] == 1
        by_id = {a["rule_id"]: a for a in out["actions"]}
        assert by_id[1]["conflict"] is None
        assert by_id[2]["conflict"] == "cancelled_by_conflict"
        assert by_id[2]["safety_verdict"] == "n/a"

    def test_budget_exhausted_reports_rate_limited(self):
        engine = _engine(load_rules_return=[_rule(1)])
        now = int(time.time())
        engine._action_history["t1"] = [now] * engine.AUTOMATION_MAX_ACTIONS_PER_WINDOW
        out = engine.dry_run_rules([_device()], tenant_id="t1")
        assert out["actions"][0]["budget"] == "rate_limited"
        assert out["budget_remaining"] is False

    def test_budget_sequential_consumption(self):
        """Mirrors the live engine: 2 slots left + 3 rules → 2 consume + 1 rate-limited."""
        engine = _engine(load_rules_return=[_rule(1), _rule(2), _rule(3)])
        now = int(time.time())
        cap = engine.AUTOMATION_MAX_ACTIONS_PER_WINDOW
        engine._action_history["t1"] = [now] * (cap - 2)  # leave 2 slots
        out = engine.dry_run_rules([_device()], tenant_id="t1")
        budgets = [a["budget"] for a in out["actions"]]
        assert budgets.count("would_consume") == 2
        assert budgets.count("rate_limited") == 1
        assert out["budget_slots_left"] == 0

    def test_missing_device_ignored(self):
        engine = _engine(load_rules_return=[_rule(1)])
        assert engine.dry_run_rules([_device("other")], tenant_id="t1")["count"] == 0


# ══════════════════════════════════════════════════════════════════════════
# 2. simulate_replay_window — pure 24h replay
# ══════════════════════════════════════════════════════════════════════════
class TestSimulateReplay:
    def _history(self, temps, step_s=60, start=0):
        return {"dev-1": [{"ts": start + i * step_s, "temperature": t,
                           "hashrate": 1e12, "device_name": "miner-dev-1"}
                          for i, t in enumerate(temps)]}

    def test_counts_fires_with_cooldown(self):
        engine = _engine()
        # 4 samples at 60s spacing, rule cooldown 60s, all hot → 4 fires
        hist = self._history([90, 90, 90, 90], step_s=60)
        out = engine.simulate_replay_window([_rule(1, min_interval=60)],
                                            hist, now=300)
        assert out["total_fires"] == 4
        assert out["per_rule"][0]["fires"] == 4
        assert out["total_rate_limited"] == 0

    def test_cooldown_suppresses_closer_samples(self):
        engine = _engine()
        hist = self._history([90, 90, 90, 90], step_s=10)  # ts 0,10,20,30
        out = engine.simulate_replay_window([_rule(1, min_interval=60)],
                                            hist, now=50)
        # only ts=0 fires — the next eligible sample would be ts=60 (absent)
        assert out["total_fires"] == 1

    def test_budget_caps_fires(self):
        engine = _engine()
        # ts 0..540 (10 samples); window = [100, 1000] → 8 in-window samples
        hist = self._history([90] * 10, step_s=60)
        out = engine.simulate_replay_window([_rule(1, min_interval=1)],
                                            hist, now=1000,
                                            max_actions_per_window=3)
        assert out["total_fires"] == 3
        assert out["total_rate_limited"] == 5  # 8 fires − 3 budget

    def test_conflict_suppressed_in_replay(self):
        engine = _engine()
        high = _rule(1, name="cool", action="underclock", priority=10,
                     min_interval=1)
        low = _rule(2, name="boost", action="overclock", priority=1,
                    min_interval=1)
        hist = self._history([90, 90, 90], step_s=60)
        out = engine.simulate_replay_window([high, low], hist, now=300,
                                            max_actions_per_window=100)
        assert out["total_fires"] == 3  # only the priority winner per cycle
        assert len(out["per_rule"]) == 1

    def test_empty_history_zeros(self):
        engine = _engine()
        out = engine.simulate_replay_window([_rule(1)], {}, now=300)
        assert out["total_fires"] == 0
        assert out["per_rule"] == []

    def test_pure_no_state_mutation(self):
        engine = _engine()
        hist = self._history([90, 90], step_s=60)
        engine.simulate_replay_window([_rule(1)], hist, now=300)
        assert engine._last_fired == {}
        assert engine._action_history == {}


# ══════════════════════════════════════════════════════════════════════════
# 3. Routes
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def client():
    import app as _app_module
    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as c:
        yield c


class TestDryRunRoutes:
    def test_dry_run_route_returns_simulation(self, client):
        from core.alerts import automation_engine as ae_mod
        mock_reg = MagicMock()
        mock_reg.list_devices.return_value = [
            {"id": "dev-1", "name": "M", "status": "ONLINE",
             "telemetry": {"temperature": 90, "hashrate_hs": 1e12}}]
        canned = {"simulated": True, "armed": False, "count": 1,
                  "would_execute": 1, "budget_remaining": True,
                  "max_actions_per_window": 10, "action_window_seconds": 900,
                  "actions": [{"rule_id": 1, "device_id": "dev-1"}]}
        with patch("axe_fleet.routes._registry", mock_reg), \
             patch.object(ae_mod.AutomationEngine, "dry_run_rules",
                          return_value=canned):
            resp = client.get("/api/automation/dry-run")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["simulated"] is True
        assert data["count"] == 1
        assert mock_reg.list_devices.called

    def test_dry_run_route_fails_closed(self, client):
        from core.alerts import automation_engine as ae_mod
        with patch("axe_fleet.routes._registry", None), \
             patch.object(ae_mod.AutomationEngine, "dry_run_rules",
                          side_effect=RuntimeError("boom")):
            resp = client.get("/api/automation/dry-run")
        assert resp.status_code == 500
        assert resp.get_json()["actions"] == []

    def test_replay_route_returns_simulation(self, client):
        from core.alerts import automation_engine as ae_mod
        mock_reg = MagicMock()
        mock_reg.list_devices.return_value = [{"id": "dev-1", "name": "M"}]
        mock_reg.get_recent_telemetry.return_value = [
            {"ts": 1700000000,
             "payload": {"ts": 1700000000, "temperature": 90,
                         "hashrate_hs": 1e12}}]
        canned = {"simulated": True, "window_hours": 24.0, "samples": 1,
                  "total_fires": 0, "total_rate_limited": 0, "per_rule": []}
        with patch("axe_fleet.routes._registry", mock_reg), \
             patch.object(ae_mod.AutomationEngine, "simulate_replay_window",
                          return_value=canned):
            resp = client.get("/api/automation/dry-run/replay?hours=24")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["simulated"] is True
        assert mock_reg.get_recent_telemetry.called


# ══════════════════════════════════════════════════════════════════════════
# 4. axe_fleet_to_device bridge
# ══════════════════════════════════════════════════════════════════════════
class TestAxeFleetToDevice:
    def test_maps_aliases_and_status(self):
        d = {"id": "ax-1", "name": "Bitaxe", "status": "ONLINE",
             "telemetry": {"hashrate_hs": 2e12, "temperature": 71,
                           "power_watts": 40, "shares_accepted": 9}}
        dev = axe_fleet_to_device(d)
        assert dev.id == "ax-1"
        assert dev.current_telemetry["hashrate"] == 2e12
        assert dev.current_telemetry["power"] == 40
        assert dev.current_telemetry["accepted_shares"] == 9
        assert dev.current_telemetry["temperature"] == 71

    def test_paused_maps_to_reachable(self):
        d = {"id": "ax-2", "name": "P", "status": "PAUSED", "telemetry": {}}
        dev = axe_fleet_to_device(d)
        # PAUSED is reachable — SafetyEngine must not treat it as offline.
        assert str(dev.status.value).upper() == "WARNING"
