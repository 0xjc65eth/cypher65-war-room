"""
CYPHER65 // Automation Engine
=============================
Executes simple automation rules of the form:
    WHEN condition THEN action
where conditions are evaluated against device telemetry and actions are
device commands that must pass through the SafetyEngine.
"""
import json
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.models.device import Device
from core.safety.safety_engine import SafetyEngine, SafetyResult

log = logging.getLogger("cypher65.automation")


@dataclass
class AutomationRule:
    id: Optional[int]
    name: str
    target_device_id: str
    condition_metric: str
    condition_operator: str  # >, <, >=, <=, ==, !=
    condition_value: float
    action_command: str
    action_parameters: Dict[str, Any]
    is_enabled: bool = True
    min_interval_seconds: int = 60
    tenant_id: str = "default"  # Fase 4 · B2


class AutomationEngine:
    """
    Loads automation rules from the database, evaluates them against the
    current fleet state, and executes actions via the SafetyEngine.
    """

    def __init__(self, db_path: str, safety_engine: SafetyEngine,
                 execute_command_callback=None, audit_callback=None):
        self.db_path = db_path
        self.safety_engine = safety_engine
        self.execute_command_callback = execute_command_callback
        self.audit_callback = audit_callback
        self._last_fired: Dict[str, int] = {}

    def load_rules(self, tenant_id: str = "") -> List[AutomationRule]:
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            if tenant_id:
                c.execute("SELECT * FROM automation_rules WHERE is_enabled=1 AND tenant_id=?", (tenant_id,))
            else:
                c.execute("SELECT * FROM automation_rules WHERE is_enabled=1")
            rows = c.fetchall()
            conn.close()
            return [
                AutomationRule(
                    id=r["id"],
                    name=r["name"],
                    target_device_id=r["target_device_id"],
                    condition_metric=r["condition_metric"],
                    condition_operator=r["condition_operator"],
                    condition_value=float(r["condition_value"]),
                    action_command=r["action_command"],
                    action_parameters=json.loads(r["action_parameters"] or "{}"),
                    is_enabled=bool(r["is_enabled"]),
                    min_interval_seconds=int(r["min_interval_seconds"]) if "min_interval_seconds" in r.keys() else 60,
                    tenant_id=r["tenant_id"] if "tenant_id" in r.keys() else "default",
                )
                for r in rows
            ]
        except Exception as e:
            log.warning("[automation_engine] failed to load rules: %s", e)
            return []

    def evaluate_rules(self, devices: List[Device]) -> List[Dict[str, Any]]:
        """Evaluate all active rules against the provided devices."""
        rules = self.load_rules()
        results = []
        now = int(time.time())
        for rule in rules:
            device = next((d for d in devices if d.id == rule.target_device_id), None)
            if device is None:
                continue
            if not self._can_fire(rule, device.id, now):
                continue
            triggered = self._evaluate_condition(device, rule)
            if triggered:
                results.append(self._execute(rule, device, now))
        return results

    def _evaluate_condition(self, device: Device, rule: AutomationRule) -> bool:
        value = self._get_metric(device, rule.condition_metric)
        if value is None:
            return False
        return self._compare(value, rule.condition_operator, rule.condition_value)

    @staticmethod
    def _get_metric(device: Device, metric: str):
        if metric == "status":
            return 1 if device.status == "ONLINE" else 0
        if metric in ("temperature", "hashrate", "power", "fan_speed", "voltage",
                        "frequency", "accepted_shares", "rejected_shares",
                        "stale_shares"):
            return (device.current_telemetry or {}).get(metric)
        return (device.current_telemetry or {}).get(metric)

    @staticmethod
    def _compare(value, operator: str, threshold) -> bool:
        try:
            if operator == ">":
                return float(value) > float(threshold)
            if operator == "<":
                return float(value) < float(threshold)
            if operator == ">=":
                return float(value) >= float(threshold)
            if operator == "<=":
                return float(value) <= float(threshold)
            if operator == "==":
                return float(value) == float(threshold)
            if operator == "!=":
                return float(value) != float(threshold)
        except (TypeError, ValueError):
            return False
        return False

    def _can_fire(self, rule: AutomationRule, device_id: str, now: int) -> bool:
        """Respect min_interval_seconds cooldown per rule/device."""
        key = f"{rule.id}:{device_id}"
        last = self._last_fired.get(key, 0)
        return (now - last) >= rule.min_interval_seconds

    def _execute(self, rule: AutomationRule, device: Device, now: Optional[int] = None) -> Dict[str, Any]:
        """Run the action for a triggered rule after SafetyEngine validation.

        The cooldown is recorded as soon as the condition matches, regardless of
        whether SafetyEngine allows the action. This prevents a continuously
        matching rule from re-evaluating every poll and spamming the safety
        checks or the device with blocked attempts.
        """
        if now is not None:
            self._last_fired[f"{rule.id}:{device.id}"] = now
        safety_result = self.safety_engine.validate_command(
            device, rule.action_command, rule.action_parameters
        )

        if not safety_result.allowed:
            reason = safety_result.reason or "SafetyEngine blocked action"
            self._audit(rule, device, status="BLOCKED_BY_SAFETY", reason=reason)
            return {
                "rule_id": rule.id,
                "rule_name": rule.name,
                "device_id": device.id,
                "status": "blocked",
                "reason": reason,
            }

        if self.execute_command_callback:
            try:
                result = self.execute_command_callback(
                    device.id, rule.action_command, rule.action_parameters
                )
                self._audit(rule, device, status="EXECUTED", result=result)
                return {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "device_id": device.id,
                    "status": "executed",
                    "result": result,
                }
            except Exception as e:
                self._audit(rule, device, status="EXECUTION_ERROR", reason=str(e))
                return {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "device_id": device.id,
                    "status": "error",
                    "reason": str(e),
                }

        self._audit(rule, device, status="EXECUTED", reason="no callback configured")
        return {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "device_id": device.id,
            "status": "executed",
        }

    def _audit(self, rule: AutomationRule, device: Device, *, status: str, reason: str = "", result: Any = ""):
        log.info("[automation] rule=%s device=%s status=%s reason=%s",
                 rule.name, device.id, status, reason)
        if self.audit_callback:
            try:
                self.audit_callback(
                    ts=int(time.time()),
                    alert_type="automation",
                    device_id=device.id,
                    severity="INFO",
                    action_taken=status,
                    rule_id=rule.id,
                    rule_name=rule.name,
                    action_command=rule.action_command,
                    status=status,
                    reason=reason,
                    result=result,
                    tenant_id=getattr(rule, "tenant_id", "default"),
                )
            except Exception as e:
                log.warning("[automation_engine] audit callback error: %s", e)
