"""
CYPHER65 // Alerts & Automation Routes
=====================================
Exposes REST endpoints for alert management and automation rules.
"""

import json
import logging
import time
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from services.tenant import require_tenant, role_required, log_audit as _log_audit

log = logging.getLogger("cypher65.alerts")
# Issue #204: throttle do warning de amostras dropadas — o WARNING cai no
# bucket de degradação (#202) e o replay pode ser chamado com frequência;
# 1 log / 5min evita floodar o bucket com o mesmo problema recorrente.
_REPLAY_WARN_INTERVAL_S = 300
_last_replay_warn_ts = 0

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api")

VALID_OPS = {">", "<", ">=", "<=", "==", "!="}


# `_get_db` is injected from app.py when the blueprint is registered to
# avoid a runtime circular import.
_get_db = None


def _set_get_db(fn):
    global _get_db
    _get_db = fn


def get_db():
    if _get_db is None:
        raise RuntimeError("get_db factory not configured; call _set_get_db() first")
    return _get_db()


def _row_to_alert(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "severity": row["severity"],
        "category": row["category"],
        "message": row["message"],
        "device_id": row["device_id"],
        "alert_type": row["alert_type"],
        "is_acknowledged": bool(row["is_acknowledged"]),
        "is_active": bool(row["active"]),
        "meta": json.loads(row["meta"] or "{}"),
    }


@alerts_bp.route("/alerts", methods=["GET"])
@require_tenant
def api_alerts(tenant_id: str = ""):
    """Return active alerts for the current tenant, optionally filtered by severity."""
    severity = request.args.get("severity")
    limit = int(request.args.get("limit", 80))
    conn = get_db()
    c = conn.cursor()
    if severity:
        c.execute(
            "SELECT * FROM alerts WHERE active=1 AND severity=? AND tenant_id=? ORDER BY ts DESC LIMIT ?",
            (severity, tenant_id or "default", limit),
        )
    else:
        c.execute(
            "SELECT * FROM alerts WHERE active=1 AND tenant_id=? ORDER BY ts DESC LIMIT ?",
            (tenant_id or "default", limit),
        )
    rows = [_row_to_alert(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"alerts": rows})


@alerts_bp.route("/alerts/acknowledge", methods=["POST"])
@require_tenant
def api_acknowledge_alert(tenant_id: str = ""):
    """Acknowledge one or more alerts by ID (scoped to tenant)."""
    data = request.get_json(silent=True) or {}
    alert_ids = data.get("ids") or [data.get("id")]
    if not alert_ids or alert_ids == [None]:
        return jsonify({"success": False, "error": "id or ids required"}), 400

    conn = get_db()
    c = conn.cursor()
    placeholders = ",".join(["?"] * len(alert_ids))
    tid = tenant_id or "default"
    # bandit B608 false positive: placeholders is generated ?-markers only
    # (count of a validated id list) — no user input reaches the SQL text.
    c.execute(
        f"UPDATE alerts SET is_acknowledged=1, active=0 WHERE id IN ({placeholders}) AND tenant_id=?",  # nosec B608
        tuple(alert_ids) + (tid,),
    )
    conn.commit()
    conn.close()
    _log_audit(tid, "alert.acknowledge", details={"ids": alert_ids})
    return jsonify({"success": True, "acknowledged_ids": alert_ids})


@alerts_bp.route("/alerts/history", methods=["GET"])
@require_tenant
def api_alert_history(tenant_id: str = ""):
    """Return the tenant's alert history/audit log."""
    limit = int(request.args.get("limit", 200))
    device_id = request.args.get("device_id")
    conn = get_db()
    c = conn.cursor()
    if device_id:
        c.execute(
            "SELECT * FROM alert_history WHERE device_id=? AND tenant_id=? ORDER BY ts DESC LIMIT ?",
            (device_id, tenant_id or "default", limit),
        )
    else:
        c.execute(
            "SELECT * FROM alert_history WHERE tenant_id=? ORDER BY ts DESC LIMIT ?",
            (tenant_id or "default", limit),
        )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"history": rows})


@alerts_bp.route("/automation-rules", methods=["GET", "POST"])
@require_tenant
def api_automation_rules(tenant_id: str = ""):
    tid = tenant_id or "default"
    conn = get_db()
    c = conn.cursor()

    if request.method == "GET":
        c.execute(
            "SELECT * FROM automation_rules WHERE tenant_id=? ORDER BY id DESC",
            (tid,),
        )
        rows = []
        for r in c.fetchall():
            row = dict(r)
            try:
                row["action_parameters"] = json.loads(
                    row.get("action_parameters") or "{}"
                )
            except Exception:
                row["action_parameters"] = {}
            rows.append(row)
        conn.close()
        return jsonify({"rules": rows})

    data = request.get_json(silent=True) or {}
    required = [
        "name",
        "target_device_id",
        "condition_metric",
        "condition_operator",
        "condition_value",
        "action_command",
    ]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"success": False, "error": f"missing fields: {missing}"}), 400

    if data["condition_operator"] not in VALID_OPS:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"invalid operator: {data['condition_operator']}",
                }
            ),
            400,
        )
    try:
        condition_value = float(data["condition_value"])
    except (TypeError, ValueError):
        return (
            jsonify({"success": False, "error": "condition_value must be numeric"}),
            400,
        )
    try:
        min_interval = int(data.get("min_interval_seconds", 60))
        if min_interval < 0:
            return (
                jsonify(
                    {"success": False, "error": "min_interval_seconds must be >= 0"}
                ),
                400,
            )
    except (TypeError, ValueError):
        return (
            jsonify(
                {"success": False, "error": "min_interval_seconds must be an integer"}
            ),
            400,
        )

    c.execute(
        """INSERT INTO automation_rules
        (name, target_device_id, condition_metric, condition_operator,
         condition_value, action_command, action_parameters, is_enabled, min_interval_seconds, tenant_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["name"],
            data["target_device_id"],
            data["condition_metric"],
            data["condition_operator"],
            float(data["condition_value"]),
            data["action_command"],
            json.dumps(data.get("action_parameters", {})),
            int(data.get("is_enabled", True)),
            min_interval,
            tid,
        ),
    )
    conn.commit()
    rule_id = c.lastrowid
    conn.close()
    _log_audit(
        tid,
        "automation.rule.create",
        target=str(rule_id),
        details={"name": data["name"], "action_command": data["action_command"]},
    )
    return jsonify({"success": True, "id": rule_id})


@alerts_bp.route("/automation-rules/<int:rule_id>", methods=["PUT", "DELETE"])
@require_tenant
def api_automation_rule(rule_id: int, tenant_id: str = ""):
    tid = tenant_id or "default"
    conn = get_db()
    c = conn.cursor()

    if request.method == "DELETE":
        c.execute(
            "DELETE FROM automation_rules WHERE id=? AND tenant_id=?", (rule_id, tid)
        )
        conn.commit()
        conn.close()
        _log_audit(tid, "automation.rule.delete", target=str(rule_id))
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}

    # Validate operator/value before touching the database.
    if "condition_operator" in data and data["condition_operator"] not in VALID_OPS:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"invalid operator: {data['condition_operator']}",
                }
            ),
            400,
        )
    if "condition_value" in data:
        try:
            data["condition_value"] = float(data["condition_value"])
        except (TypeError, ValueError):
            return (
                jsonify({"success": False, "error": "condition_value must be numeric"}),
                400,
            )
    if "min_interval_seconds" in data:
        try:
            if int(data["min_interval_seconds"]) < 0:
                return (
                    jsonify(
                        {"success": False, "error": "min_interval_seconds must be >= 0"}
                    ),
                    400,
                )
        except (TypeError, ValueError):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "min_interval_seconds must be an integer",
                    }
                ),
                400,
            )

    fields = []
    values = []
    for field in [
        "name",
        "target_device_id",
        "condition_metric",
        "condition_operator",
        "condition_value",
        "action_command",
        "action_parameters",
        "is_enabled",
        "min_interval_seconds",
    ]:
        if field in data:
            if field == "action_parameters":
                fields.append(f"{field}=?")
                values.append(json.dumps(data[field]))
            elif field in ("is_enabled", "min_interval_seconds"):
                fields.append(f"{field}=?")
                values.append(int(data[field]))
            elif field == "condition_value":
                fields.append(f"{field}=?")
                values.append(data[field])
            else:
                fields.append(f"{field}=?")
                values.append(data[field])
    if not fields:
        return jsonify({"success": False, "error": "no fields to update"}), 400

    values.append(rule_id)
    values.append(tid)
    # bandit B608 false positive: field comes from the fixed whitelist tuple
    # above (never from raw request keys) — values are bound as ?-parameters.
    c.execute(
        f"UPDATE automation_rules SET {','.join(fields)} WHERE id=? AND tenant_id=?",  # nosec B608
        tuple(values),
    )
    conn.commit()
    conn.close()
    _log_audit(
        tid, "automation.rule.update", target=str(rule_id), details={"fields": fields}
    )
    return jsonify({"success": True})


@alerts_bp.route("/automation-executions", methods=["GET"])
@require_tenant
def api_automation_executions(tenant_id: str = ""):
    """Return recent automation rule executions, scoped to this tenant's rules.

    UX audit Quick Win: ends the "black box" — the operator sees when each
    rule last ran and with what status. `automation_execution_log` has no
    tenant column, so tenant isolation is enforced by joining on the tenant's
    rule ids (rules the tenant owns or once owned).
    """
    tid = tenant_id or "default"
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """SELECT a.id, a.ts, a.rule_id, a.rule_name, a.device_id,
                      a.action_command, a.status, a.reason, a.result
               FROM automation_execution_log a
               INNER JOIN automation_rules r ON r.id = a.rule_id AND r.tenant_id = ?
               ORDER BY a.ts DESC, a.id DESC LIMIT ?""",
            (tid, limit),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e), "executions": []}), 500
    for r in rows:
        try:
            r["result"] = json.loads(r.get("result") or "{}")
        except Exception:
            r["result"] = {}
    return jsonify({"executions": rows})


@alerts_bp.route("/automation/status", methods=["GET"])
@require_tenant
@role_required("viewer")
def api_automation_status(tenant_id: str = ""):
    """Auto-Pilot armed state + action budget for the caller's tenant.

    Returns:
      {"armed": bool, "max_actions_per_window": n,
       "action_window_seconds": s, "actions_in_window": n}
    """
    from core.alerts.automation_engine import AutomationEngine

    tid = tenant_id or "default"
    try:
        engine = AutomationEngine("", None)  # settings-only reads, no DB use
        armed = engine.is_armed(tid)
        budget = engine.AUTOMATION_MAX_ACTIONS_PER_WINDOW
        window = engine.AUTOMATION_ACTION_WINDOW_S
        with engine._budget_lock:
            now = int(time.time())
            hist = [
                t for t in engine._action_history.get(tid, []) if (now - t) < window
            ]
            used = len(hist)
        return jsonify(
            {
                "armed": armed,
                "max_actions_per_window": budget,
                "action_window_seconds": window,
                "actions_in_window": used,
            }
        )
    except Exception as e:
        return jsonify({"armed": False, "error": str(e)}), 500


@alerts_bp.route("/automation/arm", methods=["POST"])
@require_tenant
@role_required("admin")
def api_automation_arm(tenant_id: str = ""):
    """Arm/disarm the Auto-Pilot for the caller's tenant.

    Body: {"armed": true|false}. Arming is the explicit confirmation gate
    (fail-closed): rules never execute until the tenant arms the pilot;
    disarming immediately stops autonomous actions.
    """
    from core.alerts.automation_engine import AutomationEngine

    tid = tenant_id or "default"
    data = request.get_json(silent=True) or {}
    armed = bool(data.get("armed"))
    try:
        engine = AutomationEngine("", None)
        ok = engine.set_armed(tid, armed)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    if not ok:
        return (
            jsonify({"success": False, "error": "could not persist armed state"}),
            500,
        )
    _log_audit(tid, "automation.arm", details={"armed": armed})
    return jsonify({"success": True, "armed": armed})


# ═══════════════════════════════════════════════════════════════════════
#  Issue #178 · Auto-Pilot Fase 4 — execução autônoma atrás do gate PRO
#  GET  /api/auto-pilot/autonomous → status (pro/armed/autonomous/cooldowns)
#  POST /api/auto-pilot/autonomous → toggle {autonomous: bool} (gate PRO)
# ═══════════════════════════════════════════════════════════════════════


@alerts_bp.route("/auto-pilot/autonomous", methods=["GET"])
@require_tenant
@role_required("viewer")
def api_auto_pilot_autonomous_status(tenant_id: str = ""):
    """Issue #178 — status do modo autônomo (gate PRO + switches)."""
    from services.auto_pilot import autonomous_status

    tid = tenant_id or "default"
    try:
        return jsonify(autonomous_status(tid))
    except Exception as e:
        return jsonify({"autonomous": False, "error": str(e)}), 500


@alerts_bp.route("/auto-pilot/autonomous", methods=["POST"])
@require_tenant
@role_required("admin")
def api_auto_pilot_autonomous_set(tenant_id: str = ""):
    """Issue #178 — liga/desliga a execução autônoma (fail-closed).

    LIGAR é gateado por PRO (is_pro() da request): em modo licensed sem
    chave válida → 402 com payload de upgrade (frente renderiza o CTA PRO).
    Desligar é sempre permitido (kill switch). A execução em si ainda exige
    ARMADO + server_pro_active() no pass do poll (dupla checagem).
    """
    from services.auto_pilot import set_autonomous_enabled
    from services.licensing import is_pro

    tid = tenant_id or "default"
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("autonomous"))
    if enabled and not is_pro():
        return (
            jsonify(
                {
                    "success": False,
                    "error": "execução autônoma é um recurso PRO — licença necessária",
                    "code": "LICENSE_REQUIRED",
                    "required_tier": "pro",
                    "upgrade": {"plan": "PRO", "price_usd_month": 9},
                }
            ),
            402,
        )
    ok = set_autonomous_enabled(tid, enabled)
    if not ok:
        return (
            jsonify({"success": False, "error": "could not persist autonomous state"}),
            500,
        )
    _log_audit(tid, "auto_pilot.autonomous", details={"autonomous": enabled})
    return jsonify({"success": True, "autonomous": enabled})


# ═══════════════════════════════════════════════════════════════════════
#  Issue #76 · Auto-Pilot Fase 3 — dry-run visual (execução simulada)
#  Simula o que o piloto FARIA com as regras armadas — resultados previstos
#  + veredito do SafetyEngine — SEM executar/auditar/mutar nada.
# ═══════════════════════════════════════════════════════════════════════


@alerts_bp.route("/automation/dry-run", methods=["GET"])
@require_tenant
@role_required("viewer")
def api_automation_dry_run(tenant_id: str = ""):
    """Issue #76 — simulated execution: what the armed pilot WOULD do now.

    Runs the full evaluate_rules pipeline (conditions + cooldown + conflicts
    + tenant budget) over the CURRENT fleet telemetry, but executes/audits/
    mutates NOTHING (no cooldown or budget consumed). Consults the
    SafetyEngine read-only to predict each action's verdict. Runs regardless
    of the armed state — rehearse before arming.
    """
    tid = tenant_id or "default"
    try:
        from config import DB_PATH as _ap_db_path
        from core.alerts.automation_engine import AutomationEngine
        from core.safety.safety_engine import SafetyEngine
        from services.auto_pilot import axe_fleet_to_device
        from services.snapshot_enrichment import get_auto_pilot_engine as _get_ap_engine
        from axe_fleet.routes import _registry

        # Prefer the boot engine: its _action_history carries the REAL
        # per-tenant budget consumption, so the simulated budget is truthful.
        engine = _get_ap_engine() or AutomationEngine(_ap_db_path, SafetyEngine())
        fleet = []
        if _registry is not None:
            fleet = _registry.list_devices(tenant_id=tid, with_telemetry=True) or []
        devices = [axe_fleet_to_device(d) for d in fleet if d.get("id")]
        return jsonify(engine.dry_run_rules(devices, tenant_id=tid))
    except Exception as e:
        return jsonify({"simulated": True, "error": str(e), "actions": []}), 500


@alerts_bp.route("/automation/dry-run/replay", methods=["GET"])
@require_tenant
@role_required("viewer")
def api_automation_dry_run_replay(tenant_id: str = ""):
    """Issue #76 — 24h replay: how many times each rule WOULD have fired.

    Pure simulation over the REAL persisted telemetry history (axe registry):
    per-cycle cooldown + conflict resolution + per-tenant budget applied
    exactly like a live cycle. Nothing executes.

    Query params: hours (default 24, max 24), limit (samples per device).
    """
    tid = tenant_id or "default"
    hours = request.args.get("hours", 24, type=int) or 24
    hours = min(max(hours, 1), 24)
    limit = request.args.get("limit", 288, type=int) or 288
    try:
        from config import DB_PATH as _ap_db_path
        from core.alerts.automation_engine import AutomationEngine
        from core.safety.safety_engine import SafetyEngine
        from services.snapshot_enrichment import get_auto_pilot_engine as _get_ap_engine
        from axe_fleet.routes import _registry

        engine = _get_ap_engine() or AutomationEngine(_ap_db_path, SafetyEngine())
        rules = engine.load_rules(tenant_id=tid)
        history: dict = {}
        # Issue #204: amostras sem ts são dropadas das séries — contabilizar
        # (antes: subconta silenciosa dos gráficos de alerta). O warning cai
        # no bucket de degradação (#202) quando o app está com o sampler ativo.
        dropped_ts = 0
        if _registry is not None:
            for dev in _registry.list_devices(tenant_id=tid) or []:
                dev_id = dev.get("id")
                if not dev_id:
                    continue
                rows = (
                    _registry.get_recent_telemetry(dev_id, limit=limit, tenant_id=tid)
                    or []
                )
                samples = []
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    p = r.get("payload")
                    if not isinstance(p, dict):
                        continue
                    sample = dict(p)
                    sample["ts"] = int(p.get("ts") or r.get("ts") or 0)
                    if not sample["ts"]:
                        dropped_ts += 1
                        continue
                    sample.setdefault("hashrate", p.get("hashrate_hs"))
                    sample.setdefault("power", p.get("power_watts"))
                    sample.setdefault("fan_speed", p.get("fan_speed"))
                    sample.setdefault("voltage", p.get("voltage_mv"))
                    sample.setdefault("frequency", p.get("frequency_mhz"))
                    sample.setdefault("accepted_shares", p.get("shares_accepted"))
                    sample.setdefault("rejected_shares", p.get("shares_rejected"))
                    sample.setdefault("stale_shares", p.get("shares_stale"))
                    samples.append(sample)
                if samples:
                    history[dev_id] = samples
        window_s = hours * 3600
        result = engine.simulate_replay_window(rules, history, window_seconds=window_s)
        result["armed"] = engine.is_armed(tid)
        # Issue #204: superfície honesta do descarte — o cliente sabe quantas
        # amostras saíram das séries por ts ausente/0.
        result["dropped_ts_samples"] = dropped_ts
        if dropped_ts:
            global _last_replay_warn_ts
            _now = int(time.time())
            if _now - _last_replay_warn_ts >= _REPLAY_WARN_INTERVAL_S:
                _last_replay_warn_ts = _now
                log.warning(
                    "[alerts replay] %d amostras de telemetria sem ts dropadas das series",
                    dropped_ts,
                )
        return jsonify(result)
    except Exception as e:
        return jsonify({"simulated": True, "error": str(e), "per_rule": []}), 500


# ═══════════════════════════════════════════════════════════════════════
#  Issue #20 · Auto-Pilot advisory mode — Fase 2 do Big Bet
#  Recomendações consolidadas por dispositivo com ação acionável + audit
#  trail (aceitas/ignoradas). Fail-closed e tenant-scoped.
# ═══════════════════════════════════════════════════════════════════════


@alerts_bp.route("/auto-pilot/recommendations", methods=["GET"])
@require_tenant
@role_required("viewer")
def api_auto_pilot_recommendations(tenant_id: str = ""):
    """Issue #20 — advisory recommendations for the caller's tenant.

    Returns:
      {
        "recommendations": [...],   # build_advisory_recommendations output
        "count": n,
        "armed": bool,              # Auto-Pilot armed state (context)
      }

    Each recommendation carries ``action.type`` + ``action.label`` so the
    UI can render a one-click button (restart / pause / blacklist / buy).
    """
    from services.auto_pilot import build_recommendations_for_tenant
    from core.alerts.automation_engine import AutomationEngine

    tid = tenant_id or "default"
    try:
        recs = build_recommendations_for_tenant(tid)
        armed = AutomationEngine("", None).is_armed(tid)
        return jsonify({"recommendations": recs, "count": len(recs), "armed": armed})
    except Exception as e:
        return (
            jsonify(
                {"recommendations": [], "count": 0, "armed": False, "error": str(e)}
            ),
            500,
        )


@alerts_bp.route("/auto-pilot/recommendations/<rec_id>/respond", methods=["POST"])
@require_tenant
@role_required("admin")
def api_auto_pilot_respond(rec_id: str, tenant_id: str = ""):
    """Issue #20 — accept/ignore an advisory recommendation (audited).

    Body: {"decision": "accept"|"ignore", "note": "..." (optional)}

    Accepting executes the recommendation's action when executable from the
    cloud:
      - restart / pause  → runs the fleet device command (agent-managed
        devices route through the local-agent queue, same as the panel).
      - blacklist        → adds the rig to the tenant's rental blacklist.
      - buy              → returns ``open_buy_flow: true`` so the frontend
        opens the Braiins spot flow pre-filled (real-money step stays in
        the UI with its own typed confirmation).
      - navigate         → informational only; nothing to execute.

    Every decision (accepted OR ignored) is recorded in the tenant's audit
    trail (auto_pilot_rec_audit) — the operator can always review what the
    pilot suggested and what they did about it.
    """
    from services.auto_pilot import (
        build_recommendations_for_tenant,
        record_rec_decision,
    )

    tid = tenant_id or "default"
    data = request.get_json(silent=True) or {}
    decision = str(data.get("decision") or "").strip().lower()
    note = str(data.get("note") or "")
    if decision not in ("accept", "ignore"):
        return (
            jsonify(
                {"success": False, "error": "decision must be 'accept' or 'ignore'"}
            ),
            400,
        )

    # Rebuild current recommendations and match by stable id. A rec that no
    # longer exists (condition cleared) can still be audited as ignored
    # with a note — accept requires the rec to still be present.
    try:
        recs = build_recommendations_for_tenant(tid)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    rec = next((r for r in recs if r.get("id") == rec_id), None)

    if decision == "accept" and rec is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "recomendação não está mais ativa (condição já resolvida)",
                }
            ),
            409,
        )

    action_type = (rec or {}).get("action", {}).get("type", "") if rec else ""
    action_result = None
    open_buy_flow = False

    if decision == "accept" and rec:
        if action_type in ("restart", "pause"):
            did = str(rec.get("device_id") or "")
            if did:
                # Reuse the fleet command executor (same agent-queue path the
                # Fleet panel uses) via a lazy import to avoid a circular
                # import at module load. NOTE: like the Fleet panel, this path
                # does NOT re-run SafetyEngine — the operator explicitly
                # confirmed the action in the UI (intentional; the automation
                # engine keeps its own safety-gated execution path).
                try:
                    from axe_fleet.routes import _execute_device_command

                    resp = _execute_device_command(did, action_type)
                    # _execute_device_command returns (jsonify(...), status)
                    # tuples on its error paths — unpack both shapes and honor
                    # the tuple's status (the jsonify body alone reports 200).
                    resp_status = None
                    if isinstance(resp, tuple) and len(resp) == 2:
                        resp, resp_status = resp
                    payload = resp.get_json() if hasattr(resp, "get_json") else {}
                    status = (
                        resp_status if resp_status is not None else resp.status_code
                    )
                    if status == 200:
                        action_result = {"ok": True, **payload}
                    else:
                        action_result = {
                            "ok": False,
                            "error": payload.get("error") or f"HTTP {status}",
                        }
                except Exception as e:
                    action_result = {"ok": False, "error": str(e)}
        elif action_type == "blacklist":
            rid = str(rec.get("device_id") or "")
            if rid:
                try:
                    from services.rental_performance import add_rig_to_blacklist

                    ok = add_rig_to_blacklist(rid, tenant_id=tid)
                    action_result = {"ok": ok}
                except Exception as e:
                    action_result = {"ok": False, "error": str(e)}
        elif action_type == "buy":
            # Real-money purchase stays in the UI (typed confirmation). The
            # backend records the accept and signals the frontend to open
            # the Braiins spot flow pre-filled.
            open_buy_flow = True
            action_result = {"ok": True, "open_buy_flow": True}

    recorded = record_rec_decision(
        tid,
        rec or {"id": rec_id},
        decision,
        note=note,
        action_result=action_result,
    )
    _log_audit(
        tid,
        "auto_pilot.respond",
        target=str(rec_id),
        details={"decision": decision, "action_type": action_type, "note": note[:200]},
    )
    return jsonify(
        {
            "success": True,
            "recorded": recorded,
            "decision": decision,
            "action_type": action_type,
            "action_result": action_result,
            "open_buy_flow": open_buy_flow,
        }
    )


@alerts_bp.route("/auto-pilot/recommendations/audit", methods=["GET"])
@require_tenant
@role_required("viewer")
def api_auto_pilot_audit(tenant_id: str = ""):
    """Issue #20 — audit trail of accepted/ignored recommendations."""
    from services.auto_pilot import get_rec_audit

    tid = tenant_id or "default"
    try:
        # request.args.get(type=int) returns None on malformed input — clamp
        # like api_automation_executions does (never int(None) → 500).
        limit = request.args.get("limit", 50)
        limit = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        audit = get_rec_audit(tid, limit=limit)
        return jsonify({"audit": audit, "count": len(audit)})
    except Exception as e:
        return jsonify({"audit": [], "count": 0, "error": str(e)}), 500
