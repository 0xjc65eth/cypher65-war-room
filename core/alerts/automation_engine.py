"""
CYPHER65 // Automation Engine
=============================
Executes simple automation rules of the form:
    WHEN condition THEN action
where conditions are evaluated against device telemetry and actions are
device commands that must pass through the SafetyEngine.
"""
import json
import os
import time
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.models.device import Device, DeviceStatus, device_status_is_online
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

    Auto-Pilot discipline (P1): execution is FAIL-CLOSED and rate-limited.
      - ``auto_pilot_armed`` per tenant (settings, default off): rules only
        EXECUTE when the tenant has explicitly armed the Auto-Pilot. When
        unarmed, evaluation degrades to a read-only preview (nothing fires).
      - Per-tenant action budget: at most ``max_actions_per_window`` action
        executions per ``action_window_seconds``. Once the budget is spent,
        further matches are reported as ``rate_limited`` and audited — a
        broken rule can never spam the fleet.
      - ``min_interval_seconds`` per rule still applies (cooldown), and
        SafetyEngine validates every action before it runs.
    """

    # Per-tenant action budget (Auto-Pilot rate limiting). Configurable via
    # env for power users; the defaults are deliberately conservative.
    AUTOMATION_MAX_ACTIONS_PER_WINDOW = int(
        os.environ.get("AUTOMATION_MAX_ACTIONS_PER_WINDOW", "10"))
    AUTOMATION_ACTION_WINDOW_S = int(
        os.environ.get("AUTOMATION_ACTION_WINDOW_S", "900"))

    def __init__(self, db_path: str, safety_engine: SafetyEngine,
                 execute_command_callback=None, audit_callback=None):
        self.db_path = db_path
        self.safety_engine = safety_engine
        self.execute_command_callback = execute_command_callback
        self.audit_callback = audit_callback
        self._last_fired: Dict[str, int] = {}
        # tenant_id -> deque of execution timestamps (rolling action budget)
        self._action_history: Dict[str, list] = {}
        self._budget_lock = threading.Lock()

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

    # Fase 3 dry-run (Issue #76): predicted outcome per action command. The
    # simulation shows WHAT the pilot would do and WHAT to expect, so the
    # operator can rehearse before arming.
    ACTION_PREDICTED_OUTCOMES: Dict[str, str] = {
        "restart": "ASIC reinicia — hashrate volta ao normal em ~60-120s "
                   "(janela curta de offline durante o reboot)",
        "pause": "Hashing para — ASIC esfria rapidamente (device continua "
                 "acessível na rede)",
        "resume": "Retoma hashing — hashrate sobe de volta ao nível normal",
        "underclock": "Frequência/voltagem caem — temperatura e consumo "
                      "reduzem (hashrate menor)",
        "overclock": "Frequência/voltagem sobem — hashrate aumenta "
                     "(temperatura e consumo sobem junto)",
        "poweroff": "Device desliga — requer acionamento manual para voltar",
        "start": "Device liga/inicia o hashing",
        "stop": "Device para de hashear",
        "identify": "Identificação visual (LED) acionada — sem impacto no "
                     "hashing",
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

    def is_armed(self, tenant_id: str = "") -> bool:
        """Auto-Pilot armed state for a tenant (fail-closed: default OFF).

        Read from the tenant's settings (``auto_pilot_armed`` = "1"). A
        missing setting or a settings error degrades to False — the pilot
        never executes until the operator explicitly arms it.
        """
        try:
            from services.settings import load_settings as _load
            s = _load(tenant_id=tenant_id or "default")
            return str(s.get("auto_pilot_armed") or "").strip() == "1"
        except Exception:
            return False

    def set_armed(self, tenant_id: str = "", armed: bool = False) -> bool:
        """Arm/disarm the Auto-Pilot for a tenant (persisted in settings).

        Returns True on success. Fail-closed: any error leaves the pilot
        disarmed.
        """
        try:
            from services.settings import save_setting as _save
            return bool(_save("auto_pilot_armed", "1" if armed else "0",
                              tenant_id=tenant_id or "default"))
        except Exception:
            return False

    def _consume_action_budget(self, tenant_id: str, now: int) -> bool:
        """True when the tenant still has action budget for this window.

        Rolling window: prune timestamps older than the window, then check
        the count against the cap. The check+append happens under a lock so
        concurrent polls can't overspend the budget.
        """
        tid = tenant_id or "default"
        window = self.AUTOMATION_ACTION_WINDOW_S
        cap = self.AUTOMATION_MAX_ACTIONS_PER_WINDOW
        with self._budget_lock:
            hist = [t for t in self._action_history.get(tid, []) if (now - t) < window]
            if len(hist) >= cap:
                self._action_history[tid] = hist
                return False
            hist.append(now)
            self._action_history[tid] = hist
            return True

    def _budget_remaining(self, tenant_id: str,
                          now: Optional[int] = None) -> int:
        """Read-only budget probe (Fase 3 dry-run).

        Returns how many action slots would remain in the current window
        WITHOUT consuming anything — the simulation must not spend budget.
        Mirrors the live engine's sequential consumption: the first N
        survivors consume the remaining slots, the overflow is rate-limited.
        """
        tid = tenant_id or "default"
        now = int(time.time()) if now is None else now
        window = self.AUTOMATION_ACTION_WINDOW_S
        cap = self.AUTOMATION_MAX_ACTIONS_PER_WINDOW
        with self._budget_lock:
            hist = [t for t in self._action_history.get(tid, [])
                    if (now - t) < window]
            return max(0, cap - len(hist))

    def evaluate_rules(self, devices: List[Device],
                       tenant_id: str = "") -> List[Dict[str, Any]]:
        """Evaluate the tenant's active rules against the provided devices.

        Auto-Pilot discipline:
          - Rules are loaded scoped to ``tenant_id`` — a named tenant's rules
            NEVER run against another tenant's fleet (previous behavior
            loaded every tenant's rules into the operator's evaluation).
          - When the tenant is NOT armed, nothing executes: the result list
            carries a single ``{"status": "disarmed"}`` marker so callers
            (and the Command Center) can surface the pilot state honestly.
          - Triggered rules that exceed the per-tenant action budget are
            audited as ``RATE_LIMITED`` and returned with that status.
          - Deadlock prevention: conflicting actions on the same device in
            the same cycle resolve by priority (higher wins; ties cancel
            both) exactly as before.
        """
        rules = self.load_rules(tenant_id=tenant_id)
        now = int(time.time())
        armed = self.is_armed(tenant_id)
        if not armed:
            return [{"status": "disarmed", "tenant_id": tenant_id or "default"}]

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
        tid = tenant_id or "default"
        for rule, device in survivors:
            if not self._consume_action_budget(tid, now):
                # Record the cooldown exactly like conflict-cancelled rules:
                # a persistently-matching rule beyond its budget must re-audit
                # at most once per min_interval_seconds instead of spamming
                # RATE_LIMITED every poll cycle (15s).
                self._last_fired[f"{rule.id}:{device.id}"] = now
                self._audit(rule, device, status="RATE_LIMITED",
                            reason=f"tenant action budget exceeded "
                                   f"({self.AUTOMATION_MAX_ACTIONS_PER_WINDOW} / "
                                   f"{self.AUTOMATION_ACTION_WINDOW_S}s)")
                results.append({
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "device_id": device.id,
                    "status": "rate_limited",
                    "reason": "tenant action budget exceeded",
                })
                continue
            results.append(self._execute(rule, device, now))
        return results

    def dry_run_rules(self, devices: List[Device],
                      tenant_id: str = "") -> Dict[str, Any]:
        """Fase 3 (Issue #76): simulated execution — what the armed pilot
        WOULD do right now.

        Runs the exact ``evaluate_rules`` pipeline (conditions + cooldown +
        conflict resolution + tenant budget) against the CURRENT telemetry,
        but with ZERO side effects:
          - never calls execute_command_callback (nothing executes)
          - never audits (no fake EXECUTED rows in the audit trail)
          - never mutates ``_last_fired`` / ``_action_history`` — the
            simulation consumes no cooldown and no budget, so rehearsing
            never delays a real fire
        It also runs REGARDLESS of the armed state (that is the point:
        rehearse before arming) and consults the SafetyEngine read-only to
        predict whether each action would be approved.
        """
        rules = self.load_rules(tenant_id=tenant_id)
        now = int(time.time())
        tid = tenant_id or "default"

        triggered: List[tuple] = []
        for rule in rules:
            device = next((d for d in devices if d.id == rule.target_device_id), None)
            if device is None:
                continue
            if not self._can_fire(rule, device.id, now):
                continue
            if self._evaluate_condition(device, rule):
                triggered.append((rule, device))

        survivors = self._resolve_conflicts(triggered, now, dry=True)
        survivor_ids = {(r.id, d.id) for r, d in survivors}
        cancelled = [(r, d) for r, d in triggered
                     if (r.id, d.id) not in survivor_ids]
        # Sequential budget simulation (mirrors live consumption): the first
        # N survivors consume the remaining slots, the overflow is marked
        # rate_limited — exactly what the armed pilot would do.
        budget_left = self._budget_remaining(tid, now)

        actions: List[Dict[str, Any]] = []
        for rule, device in survivors:
            safety = self._simulate_safety(device, rule)
            if budget_left > 0:
                budget_left -= 1
                budget_status = "would_consume"
            else:
                budget_status = "rate_limited"
            actions.append({
                "rule_id": rule.id,
                "rule_name": rule.name,
                "device_id": device.id,
                "device_name": getattr(device, "name", "") or device.id,
                "condition_metric": rule.condition_metric,
                "condition_operator": rule.condition_operator,
                "condition_value": rule.condition_value,
                "actual_value": self._get_metric(device, rule.condition_metric),
                "action_command": rule.action_command,
                "action_parameters": dict(rule.action_parameters or {}),
                "predicted_outcome": self.ACTION_PREDICTED_OUTCOMES.get(
                    rule.action_command,
                    "Ação executada pelo firmware do device (efeito depende "
                    "do modelo)."),
                "safety_verdict": safety["verdict"],
                "safety_reason": safety["reason"],
                "budget": budget_status,
                "conflict": None,
            })
        for rule, device in cancelled:
            actions.append({
                "rule_id": rule.id,
                "rule_name": rule.name,
                "device_id": device.id,
                "device_name": getattr(device, "name", "") or device.id,
                "condition_metric": rule.condition_metric,
                "condition_operator": rule.condition_operator,
                "condition_value": rule.condition_value,
                "actual_value": self._get_metric(device, rule.condition_metric),
                "action_command": rule.action_command,
                "action_parameters": dict(rule.action_parameters or {}),
                "predicted_outcome": "Cancelada: ação conflita com outra regra "
                                     "do mesmo device no mesmo ciclo.",
                "safety_verdict": "n/a",
                "safety_reason": "",
                "budget": "n/a",
                "conflict": "cancelled_by_conflict",
            })
        return {
            "simulated": True,
            "armed": self.is_armed(tid),
            "count": len(actions),
            # Only actions that WOULD actually run count — a survivor past
            # the budget slot is rate_limited, not executed.
            "would_execute": sum(1 for a in actions
                                  if a["budget"] == "would_consume"),
            "budget_remaining": budget_left > 0,
            "budget_slots_left": budget_left,
            "max_actions_per_window": self.AUTOMATION_MAX_ACTIONS_PER_WINDOW,
            "action_window_seconds": self.AUTOMATION_ACTION_WINDOW_S,
            "actions": actions,
        }

    def _simulate_safety(self, device: Device,
                         rule: AutomationRule) -> Dict[str, str]:
        """Predict the SafetyEngine verdict (read-only, never recorded)."""
        if self.safety_engine is None:
            return {"verdict": "unknown", "reason": "no safety engine"}
        try:
            res = self.safety_engine.validate_command(
                device, rule.action_command, rule.action_parameters)
            if res.allowed:
                return {"verdict": "approved", "reason": ""}
            return {"verdict": "blocked",
                    "reason": res.reason or "SafetyEngine bloqueou (simulado)"}
        except Exception as e:
            return {"verdict": "unknown", "reason": str(e)[:120]}

    def simulate_replay_window(self, rules: List[AutomationRule],
                               history: Dict[str, list],
                               now: Optional[int] = None,
                               max_actions_per_window: Optional[int] = None,
                               window_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Fase 3 (Issue #76): simulate the ARMED pilot over telemetry history.

        PURE — no I/O, no audit, no state mutation, nothing executes. Walks
        each device's samples chronologically and counts how many times each
        rule WOULD have fired in the window, applying the same pipeline as a
        live cycle: per-rule cooldown (min_interval_seconds), same-cycle
        conflict resolution and the per-tenant action budget.

        Args:
            rules: list of AutomationRule.
            history: dict device_id -> list of {ts, **telemetry} payloads in
                the automation metric namespace (temperature, hashrate, ...).
            now / max_actions_per_window / window_seconds: simulation knobs.

        Returns:
            {window_hours, samples, total_fires, total_rate_limited,
             per_rule: [{rule_id, rule_name, device_id, device_name,
                         action_command, fires, rate_limited, first_ts, last_ts}]}
        """
        cap = (self.AUTOMATION_MAX_ACTIONS_PER_WINDOW
               if max_actions_per_window is None else max_actions_per_window)
        window = (self.AUTOMATION_ACTION_WINDOW_S
                  if window_seconds is None else window_seconds)
        now = int(time.time()) if now is None else now
        window_start = now - window

        last_fire: Dict[tuple, int] = {}
        budget_spent = 0
        per_rule: Dict[int, dict] = {}
        samples_total = 0

        for device_id, samples in (history or {}).items():
            ordered = sorted(
                (s for s in samples
                 if isinstance(s, dict) and s.get("ts") is not None),
                key=lambda s: s["ts"])
            ordered = [s for s in ordered if window_start <= s["ts"] <= now]
            samples_total += len(ordered)
            i = 0
            while i < len(ordered):
                ts = ordered[i]["ts"]
                dev = Device(id=device_id,
                             name=str(ordered[i].get("device_name") or device_id),
                             status=DeviceStatus.ONLINE)
                dev.current_telemetry = ordered[i]
                triggered: List[tuple] = []
                for rule in rules:
                    if rule.target_device_id != device_id:
                        continue
                    key = (rule.id, device_id)
                    # None sentinel: a ts of 0 is a legitimate timestamp and
                    # must never count as "fired at epoch 0".
                    prev = last_fire.get(key)
                    if prev is not None and (ts - prev) < rule.min_interval_seconds:
                        continue
                    if self._evaluate_condition(dev, rule):
                        triggered.append((rule, dev))
                for rule, _ in self._resolve_conflicts(triggered, ts, dry=True):
                    key = (rule.id, device_id)
                    last_fire[key] = ts
                    agg = per_rule.get(rule.id)
                    if agg is None:
                        agg = {
                            "rule_id": rule.id,
                            "rule_name": rule.name,
                            "device_id": device_id,
                            "device_name": str(ordered[i].get("device_name")
                                                or device_id),
                            "action_command": rule.action_command,
                            "fires": 0,
                            "rate_limited": 0,
                            "first_ts": ts,
                            "last_ts": ts,
                        }
                        per_rule[rule.id] = agg
                    if budget_spent >= cap:
                        agg["rate_limited"] += 1
                    else:
                        budget_spent += 1
                        agg["fires"] += 1
                        # Timestamps only advance on REAL fires — a rule that
                        # only got rate_limited must not show a "when" it fired.
                        agg["first_ts"] = (min(agg["first_ts"], ts)
                                            if agg.get("first_ts") else ts)
                        agg["last_ts"] = max(agg["last_ts"], ts)
                # Advance past every sample sharing this ts (one cycle).
                while i < len(ordered) and ordered[i]["ts"] == ts:
                    i += 1

        per_rule_list = sorted(per_rule.values(),
                               key=lambda a: (-a["fires"], a["rule_id"]))
        return {
            "window_hours": round(window / 3600, 2),
            "samples": samples_total,
            "total_fires": sum(a["fires"] for a in per_rule_list),
            "total_rate_limited": sum(a["rate_limited"] for a in per_rule_list),
            "per_rule": per_rule_list,
        }

    def _resolve_conflicts(self, triggered: List[tuple],
                           now: Optional[int] = None,
                           dry: bool = False) -> List[tuple]:
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

        ``dry=True`` (Fase 3 dry-run / replay): never audits conflicts and
        never records cooldown — the simulation must not mutate pilot state.
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
                        if not dry:
                            self._audit_conflict(rule_j, dev_j, blocked_by=rule_i.name)
                    elif rule_j.priority > rule_i.priority:
                        cancelled.add(i)
                        if not dry:
                            self._audit_conflict(rule_i, dev_i, blocked_by=rule_j.name)
                    else:  # tie → cancel both, never let them fight
                        cancelled.add(i)
                        cancelled.add(j)
                        if not dry:
                            self._audit_conflict(rule_i, dev_i,
                                                 blocked_by=rule_j.name + " (tie)")
                            self._audit_conflict(rule_j, dev_j,
                                                 blocked_by=rule_i.name + " (tie)")
            for idx, (rule, dev) in enumerate(pairs):
                if idx in cancelled and not dry:
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
