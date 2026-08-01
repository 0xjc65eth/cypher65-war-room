"""
CYPHER65 // Alert Engine
=========================
Evaluates configurable alert rules against device telemetry and pool state,
persists alerts to SQLite, and dispatches critical alerts to push notifications.
"""
import copy
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

from core.models.device import Device

log = logging.getLogger("cypher65.alerts")


@dataclass
class AlertRule:
    name: str
    metric: str
    operator: str  # '>', '<', '>=', '<=', '==', '!='
    threshold: float
    severity: str  # CRIT, WARN, INFO, GOLD
    category: str
    device_id: Optional[str] = None
    model: Optional[str] = None
    enabled: bool = True
    cooldown_seconds: int = 300
    tenant_id: str = "default"  # Fase 4 · B2


@dataclass
class Alert:
    ts: int
    severity: str
    category: str
    message: str
    device_id: Optional[str] = None
    alert_type: str = "threshold"
    is_acknowledged: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)
    tenant_id: str = "default"  # Fase 4 · B2


class AlertEngine:
    """
    Evaluates telemetry/pool data against AlertRules and produces Alert objects.
    Supports configurable thresholds per device and per model.
    """

    DEFAULT_RULES = [
        # ── Temperature ──
        AlertRule("temp_critical", "temperature", ">", 75.0, "CRIT", "temperature"),
        AlertRule("temp_high", "temperature", ">", 65.0, "WARN", "temperature"),
        AlertRule("temp_warm", "temperature", ">", 55.0, "INFO", "temperature"),

        # ── Hashrate ──
        AlertRule("hashrate_zero", "hashrate_hs", "==", 0, "CRIT", "hashrate_drop"),
        AlertRule("hashrate_drop_severe", "hashrate_drop_pct", ">", 80.0, "CRIT", "hashrate_drop"),
        AlertRule("hashrate_drop", "hashrate_drop_pct", ">", 30.0, "WARN", "hashrate_drop"),

        # ── Reject / Stale ──
        AlertRule("reject_rate_crit", "reject_rate", ">", 10.0, "CRIT", "reject_rate"),
        AlertRule("reject_rate_high", "reject_rate", ">", 3.0, "WARN", "reject_rate"),
        AlertRule("stale_rate_crit", "stale_rate", ">", 10.0, "CRIT", "stale_rate"),
        AlertRule("stale_rate_high", "stale_rate", ">", 3.0, "WARN", "stale_rate"),

        # ── Connectivity ──
        AlertRule("device_offline", "status", "==", 0, "CRIT", "device_offline"),
        AlertRule("pool_disconnect", "pool_online", "==", 0, "CRIT", "pool_disconnect"),
    ]

    def __init__(self, db_path: str, push_callback: Optional[Callable] = None):
        self.db_path = db_path
        self.push_callback = push_callback
        self._last_fired: Dict[str, int] = {}
        self._rules: List[AlertRule] = list(self.DEFAULT_RULES)

    def _load_rules(self, tenant_id: str = "") -> List[AlertRule]:
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            if tenant_id:
                c.execute("SELECT * FROM alert_rules WHERE enabled=1 AND tenant_id=?", (tenant_id,))
            else:
                c.execute("SELECT * FROM alert_rules WHERE enabled=1")
            rows = c.fetchall()
            conn.close()
            if not rows:
                # No custom rules configured — fall back to defaults
                return copy.deepcopy(self._rules)
            rules = []
            for r in rows:
                rules.append(AlertRule(
                    name=r["name"],
                    metric=r["metric"],
                    operator=r["operator"],
                    threshold=float(r["threshold"]),
                    severity=r["severity"],
                    category=r["category"],
                    device_id=r["device_id"],
                    model=r["model"],
                    enabled=bool(r["enabled"]),
                    cooldown_seconds=int(r["cooldown_seconds"]),
                    tenant_id=r["tenant_id"] if "tenant_id" in r.keys() else "default",
                ))
            return rules
        except Exception as e:
            log.warning("[alert_engine] failed to load custom rules: %s", e)
            return copy.deepcopy(self._rules)

    @property
    def rules(self) -> List[AlertRule]:
        return self._load_rules()

    def evaluate(self, devices: List[Device], pool: Optional[Dict[str, Any]] = None) -> List[Alert]:
        """Evaluate all enabled rules and return generated alerts."""
        rules = self.rules
        alerts: List[Alert] = []
        for device in devices:
            for rule in rules:
                if rule.device_id and rule.device_id != device.id:
                    continue
                if rule.model and rule.model != device.model:
                    continue
                alert = self._check_rule(device, rule)
                if alert:
                    alerts.append(alert)

        if pool is not None:
            alert = self._check_pool(pool)
            if alert:
                alerts.append(alert)

        return alerts

    def _check_pool(self, pool: Dict[str, Any]) -> Optional[Alert]:
        if not pool or pool.get("hashrate") is None:
            sig = "pool_disconnect"
            if not self._can_fire(sig):
                return None
            self._last_fired[sig] = int(time.time())
            return Alert(
                ts=int(time.time()),
                severity="CRIT",
                category="pool_disconnect",
                message="Pool stats are unavailable",
                alert_type="pool",
            )
        return None

    def _check_rule(self, device: Device, rule: AlertRule) -> Optional[Alert]:
        value = self._get_metric(device, rule.metric)
        if value is None:
            return None

        triggered = self._compare(value, rule.operator, rule.threshold)
        if not triggered:
            return None

        sig = f"{rule.name}:{device.id}"
        if not self._can_fire(sig, rule.cooldown_seconds):
            return None

        self._last_fired[sig] = int(time.time())
        return Alert(
            ts=int(time.time()),
            severity=rule.severity,
            category=rule.category,
            message=f"{device.name} {rule.metric}={value} {rule.operator} {rule.threshold}",
            device_id=device.id,
            alert_type="threshold",
        )

    def _get_metric(self, device: Device, metric: str):
        if metric == "status":
            return 1 if device.status == "ONLINE" else 0
        if metric == "temperature":
            return (device.current_telemetry or {}).get("temperature")
        if metric == "hashrate_drop_pct":
            # placeholder; computed externally if needed
            return (device.current_telemetry or {}).get("hashrate_drop_pct")
        if metric == "reject_rate":
            return (device.current_telemetry or {}).get("reject_rate")
        if metric == "stale_rate":
            return (device.current_telemetry or {}).get("stale_rate")
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

    def _can_fire(self, signature: str, cooldown_seconds: int = 300) -> bool:
        last = self._last_fired.get(signature, 0)
        return (int(time.time()) - last) >= cooldown_seconds

    def persist(self, alerts: List[Alert]):
        """Persist alerts to the SQLite database and the audit log."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            for a in alerts:
                # active=1 explicit: the legacy alerts table's default is 0,
                # so relying on the schema default would make alerts invisible
                # to /api/alerts (which filters WHERE active=1).
                c.execute(
                    """INSERT INTO alerts (ts, severity, category, message, device_id, alert_type, is_acknowledged, active, meta, tenant_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (a.ts, a.severity, a.category, a.message, a.device_id or "", a.alert_type,
                     1 if a.is_acknowledged else 0, json.dumps(a.meta), a.tenant_id or "default"),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("[alert_engine] persist error: %s", e)

        # Mirror every generated alert into the audit log for history/auditing.
        # Kept separate so a missing audit table never blocks the core alert.
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            for a in alerts:
                c.execute(
                    """INSERT INTO alert_history (ts, alert_type, device_id, severity, action_taken, tenant_id)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        a.ts,
                        a.alert_type or "threshold",
                        a.device_id or "",
                        a.severity,
                        a.message,
                        a.tenant_id or "default",
                    ),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("[alert_engine] audit history error: %s", e)

    def dispatch_push(self, alerts: List[Alert]):
        """Dispatch push notifications for critical alerts."""
        if not self.push_callback:
            return
        for a in alerts:
            if a.severity in ("CRIT", "CRITICAL", "WARN"):
                try:
                    self.push_callback(a.severity, a.category, a.message)
                except Exception as e:
                    log.warning("[alert_engine] push dispatch error: %s", e)
