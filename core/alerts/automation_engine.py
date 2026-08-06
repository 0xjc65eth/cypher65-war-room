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

from core.models.device import Device, device_status_is_online
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
    priority: int = 0  # Deadlock prevention: higher wins conflicting pairs


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
                    priority=int(r["priority"]) if "priority" in r.keys() else 0,
                )
                for r in rows
            ]
        except Exception as e:
            log.warning("[automation_engine] failed to load rules: %s", e)
            return []

    # Action pairs that are mutually exclusive on the SAME device. When two
    # rules would fire conflicting actions in one cycle, deadlock prevention
    # elects the higher-priority rule (or cancels both when tied) and logs.
    _CONFLICTING_ACTIONS: Dict[str, str] = {
        "overclock": "underclock",
        "underclock": "overclock",
        "pause": "resume",
        "resume": "pause",
        "restart": "poweroff",
        "poweroff": "restart",
        "start": "stop",
        "stop": "start",
    }

    def preview_rules(self, devices: List[Device],
                      tenant_id: str = "") -> List[Dict[str, Any]]:
        """P1 Auto-Pilot advisory: which enabled rules WOULD fire right now.

        Read-only by design — evaluates conditions + cooldown against the
        devices but NEVER executes, validates through SafetyEngine or audits.
        The Command Center consumes this to surface "this rule is ready to
        fire" as a decision card, keeping autonomous execution gated for the
        later Auto-Pilot phase.

        Returns a list of dicts (one per would-fire rule):
          {rule_id, rule_name, device_id, condition_metric, condition_operator,
           condition_value, action_command, action_parameters}
        """
        rules = self.load_rules(tenant_id=tenant_id)
        now = int(time.time())
        preview: List[Dict[str, Any]] = []
        for rule in rules:
            device = next((d for d in devices if d.id == rule.target_device_id), None)
            if device is None:
                continue
            if not self._can_fire(rule, device.id, now):
                continue
            if self._evaluate_condition(device, rule):
                preview.append({
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "device_id": device.id,
                    "condition_metric": rule.condition_metric,
                    "condition_operator": rule.condition_operator,
                    "condition_value": rule.condition_value,
                    "action_command": rule.action_command,
                    "action_parameters": dict(rule.action_parameters or {}),
                })
        return preview

    def evaluate_rules(self, devices: List[Device]) -> List[Dict[str, Any]]:
        """Evaluate all active rules against the provided devices.

        Deadlock prevention: triggered rules are collected per device first;
        when two rules would execute CONFLICTING actions on the same device
        in the same cycle, the higher-priority rule wins and the loser is
        audited as CANCELLED (conflict). Ties cancel both and log.
        """
        rules = self.load_rules()
        now = int(time.time())
        triggered: List[tuple] = []  # (rule, device)
        for rule in rules:
            device = next((d for d in devices if d.id == rule.target_device_id), None)
            if device is None:
                continue
            if not self._can_fire(rule, device.id, now):
                continue
            if self._evaluate_condition(device, rule):
                triggered.append((rule, device))

        survivors = self._resolve_conflicts(triggered, now)
        results = []
        for rule, device in survivors:
            results.append(self._execute(rule, device, now))
        return results

    def _resolve_conflicts(self, triggered: List[tuple],
                           now: Optional[int] = None) -> List[tuple]:
        """Drop conflicting rules on the same device, keeping higher priority.

        Non-conflicting rules always survive. Conflicting pairs are resolved
        by priority alone: higher priority wins; equal priorities cancel BOTH
        with a log (a stale/uncertain rule should never fight the other). The
        rule id never breaks a tie — insertion order must not decide a
        conflict. Losers are audited as CANCELLED_BY_CONFLICT so operators
        see why nothing ran.

        Cancelled rules ALSO record their cooldown (like execution does), so a
        persistent conflict re-audits at most once per min_interval_seconds
        instead of spamming the log every poll cycle.
        """
        now = int(time.time()) if now is None else now
        if len(triggered) <= 1:
            return triggered
        by_device: Dict[str, List[tuple]] = {}
        for rule, device in triggered:
            by_device.setdefault(device.id, []).append((rule, device))

        survivors: List[tuple] = []
        for device_id, pairs in by_device.items():
            if len(pairs) == 1:
                survivors.append(pairs[0])
                continue
            cancelled: set = set()  # indices into `pairs`
            for i in range(len(pairs)):
                for j in range(i + 1, len(pairs)):
                    rule_i, dev_i = pairs[i]
                    rule_j, dev_j = pairs[j]
                    if not self._actions_conflict(rule_i.action_command,
                                                  rule_j.action_command):
                        continue
                    # Compare priority ONLY: equal priorities are a genuine
                    # tie (cancel both). The rule id must never break the tie —
                    # that would let insertion order decide a conflict.
                    if rule_i.priority > rule_j.priority:
                        cancelled.add(j)
                        self._audit_conflict(rule_j, dev_j, blocked_by=rule_i.name)
                    elif rule_j.priority > rule_i.priority:
                        cancelled.add(i)
                        self._audit_conflict(rule_i, dev_i, blocked_by=rule_j.name)
                    else:  # tie → cancel both, never let them fight
                        cancelled.add(i)
                        cancelled.add(j)
                        self._audit_conflict(rule_i, dev_i,
                                             blocked_by=rule_j.name + " (tie)")
                        self._audit_conflict(rule_j, dev_j,
                                             blocked_by=rule_i.name + " (tie)")
            for idx, (rule, dev) in enumerate(pairs):
                if idx in cancelled:
                    # Rate-limit re-audits for persistent conflicts.
                    self._last_fired[f"{rule.id}:{dev.id}"] = now
            survivors.extend(p for idx, p in enumerate(pairs) if idx not in cancelled)
        return survivors

    @staticmethod
    def _actions_conflict(a: str, b: str) -> bool:
        if a == b:
            return False  # same action twice is harmless (idempotent)
        return AutomationEngine._CONFLICTING_ACTIONS.get(a) == b

    def _audit_conflict(self, rule: AutomationRule, device: Device,
                        *, blocked_by: str):
        log.warning("[automation] rule=%s device=%s CANCELLED_BY_CONFLICT "
                    "(blocked by %s)", rule.name, device.id, blocked_by)
        if self.audit_callback:
            try:
                self.audit_callback(
                    ts=int(time.time()),
                    alert_type="automation",
                    device_id=device.id,
                    severity="WARN",
                    action_taken="CANCELLED_BY_CONFLICT",
                    rule_id=rule.id,
                    rule_name=rule.name,
                    action_command=rule.action_command,
                    status="cancelled",
                    reason=f"conflicting action with {blocked_by}",
                    result="",
                    tenant_id=getattr(rule, "tenant_id", "default"),
                )
            except Exception as e:
                log.warning("[automation_engine] audit callback error: %s", e)

    def _evaluate_condition(self, device: Device, rule: AutomationRule) -> bool:
        value = self._get_metric(device, rule.condition_metric)
        if value is None:
            return False
        return self._compare(value, rule.condition_operator, rule.condition_value)

    @staticmethod
    def _get_metric(device: Device, metric: str):
        if metric == "status":
            # Shared normalization (handles str-Enum lowercase values AND plain
            # strings) — WARNING counts as reachable, so a degraded device
            # never evaluates as offline for automation conditions.
            return 1 if device_status_is_online(device.status) else 0
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
