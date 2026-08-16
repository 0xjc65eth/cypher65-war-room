"""
CYPHER65 // Auto-Pilot — Advisory Mode (Issue #20 · Fase 2 do Big Bet)
======================================================================
Consolidated per-device recommendations BEFORE the pilot acts. For each
device the advisory layer answers "what is wrong and what should I do?":

  - offline       → restart (crit)
  - temp_high     → pause   (warn)
  - hashrate_drop → restart (gold)
  - rig_poor      → blacklist the rig (warn)
  - buy           → open the Braiins spot flow pre-filled (gold)

Every recommendation carries ONE actionable action with a label, so the
panel can render a real button (not just a navigation target). Accepts /
ignores are recorded in a per-tenant audit trail (``auto_pilot_rec_audit``)
so operators can review what the pilot suggested and what they did about it.

Design:
  - ``build_advisory_recommendations()`` is PURE (data in → list out) and
    mirrors the ``helpers.build_command_center`` ethos: no network, no DB,
    never raises. It shares the SAME thresholds (AP_TEMP_HIGH_C,
    AP_HASHRATE_DROP_RATIO) so the advisory layer and the Command Center
    never disagree.
  - ``build_recommendations_for_tenant()`` collects real data (live fleet
    telemetry, 7d peak, worst rigs, arbitrage window) and feeds the pure
    builder. Tenant-scoped + fail-closed: any collection error degrades to
    the empty list, never a crash.
  - The audit trail is a plain SQLite table with tenant scoping; reads/writes
    go through the shared services.db connection helper.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from helpers import AP_TEMP_HIGH_C, AP_HASHRATE_DROP_RATIO

log = logging.getLogger("cypher65.auto_pilot")

# Severity rank used to order recommendations (highest wins).
_AP_SEVERITY_ORDER = {"crit": 0, "gold": 1, "warn": 2, "info": 3}

# Rig-blacklist recommendation threshold: only rigs with this danger score
# (or above) are suggested for blacklisting. Mirrors the worst-rigs panel.
AP_RIG_POOR_DANGER_MIN = 60.0

# Audit trail table name (per-tenant rows).
AP_AUDIT_TABLE = "auto_pilot_rec_audit"


# ─────────────────────────────────────────────────────────────────────────
#  Pure builder — data in, recommendations out (never raises)
# ─────────────────────────────────────────────────────────────────────────


def _num(v):
    try:
        f = float(v)
        return f if (f == f and f != float("inf") and f != float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _device_status(d: dict) -> str:
    return str(d.get("status") or "").upper()


def _device_temp(d: dict) -> Optional[float]:
    # Telemetry may carry temperature under either key; the fleet registry
    # with_telemetry=True nests it under d["telemetry"].
    tel = d.get("telemetry") if isinstance(d.get("telemetry"), dict) else {}
    for k in ("temperature", "temp"):
        v = tel.get(k) if tel else None
        if v is None:
            v = d.get(k)
        num = _num(v)
        if num is not None:
            return num
    return None


def _device_hashrate(d: dict) -> Optional[float]:
    tel = d.get("telemetry") if isinstance(d.get("telemetry"), dict) else {}
    for k in ("hashrate_hs", "hashrate"):
        v = tel.get(k) if tel else None
        if v is None:
            v = d.get(k)
        num = _num(v)
        if num is not None:
            return num
    return None


def _device_cap(d: dict, cap: str) -> bool:
    caps = d.get("capabilities")
    if isinstance(caps, dict):
        return bool(caps.get(cap))
    if isinstance(caps, str):
        try:
            return bool(json.loads(caps).get(cap))
        except (ValueError, TypeError):
            return False
    return False


def axe_fleet_to_device(d: dict):
    """Bridge an axe-fleet device dict into a core Device (Fase 3 dry-run).

    The AutomationEngine operates on ``core.models.device.Device`` objects
    whose ``current_telemetry`` uses the core metric names (hashrate, power,
    accepted_shares, ...). Axe telemetry carries hashrate_hs, power_watts,
    shares_* — this maps the aliases so rule conditions evaluate correctly.
    """
    from core.models.device import Device, DeviceStatus

    tel = d.get("telemetry") if isinstance(d.get("telemetry"), dict) else {}
    sample = dict(tel)
    sample.setdefault("hashrate", tel.get("hashrate_hs"))
    sample.setdefault("power", tel.get("power_watts"))
    sample.setdefault("fan_speed", tel.get("fan_speed"))
    sample.setdefault("voltage", tel.get("voltage_mv"))
    sample.setdefault("frequency", tel.get("frequency_mhz"))
    sample.setdefault("accepted_shares", tel.get("shares_accepted"))
    sample.setdefault("rejected_shares", tel.get("shares_rejected"))
    sample.setdefault("stale_shares", tel.get("shares_stale"))

    _STATUS_MAP = {
        "ONLINE": DeviceStatus.ONLINE,
        "HASHING": DeviceStatus.ONLINE,
        "WARNING": DeviceStatus.WARNING,
        "IDLE": DeviceStatus.ONLINE,  # reachable, not hashing
        "PAUSED": DeviceStatus.WARNING,  # reachable (never "offline")
        "ERROR": DeviceStatus.CRITICAL,
        "OFFLINE": DeviceStatus.OFFLINE,
    }
    dev = Device(
        id=str(d.get("id") or ""),
        name=str(d.get("name") or d.get("id") or ""),
        status=_STATUS_MAP.get(
            str(d.get("status") or "").upper(), DeviceStatus.OFFLINE
        ),
    )
    dev.current_telemetry = sample
    return dev


def build_advisory_recommendations(
    fleet: Optional[List[dict]] = None,
    peak_7d: float = 0.0,
    worst_rigs: Optional[List[dict]] = None,
    arb_window: Optional[list] = None,
    blacklisted_rigs: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Consolidated per-device advisory recommendations (PURE).

    Args:
        fleet: list of device dicts (id, name, status, capabilities,
               telemetry{temperature, hashrate_hs}).
        peak_7d: worker hashrate peak observed in the last 7 days (H/s).
        worst_rigs: ``compute_worst_rigs()`` output rows (rig_id, name,
                    danger, ewma_delivery_pct, samples, grade).
        arb_window: non-empty when an arbitrage buy window is open
                    (evaluate_market_arb_alerts dry_run output).
        blacklisted_rigs: rig ids already blacklisted (skip rig_poor recs).

    Returns a list of recommendation dicts:
      {
        "id": "ap-<issue>-<device_id>",       # stable id for the audit trail
        "device_id": str, "device_name": str,
        "issue_type": str, "severity": str,
        "message": str,
        "action": {"type": str, "label": str},
      }

    Honest + fail-closed: only real conditions emit a recommendation; a
    fleet device without telemetry is never guessed. Never raises.
    """
    recs: List[Dict[str, Any]] = []

    fleet = [d for d in (fleet or []) if isinstance(d, dict)]
    blacklist = set(str(r) for r in (blacklisted_rigs or []))

    for d in fleet:
        did = str(d.get("id") or d.get("device_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or did)
        status = _device_status(d)
        temp = _device_temp(d)
        hr = _device_hashrate(d)
        can_restart = _device_cap(d, "restart")
        can_pause = _device_cap(d, "pause")

        # ── 1. offline → restart (crit) ──
        if status == "OFFLINE":
            recs.append(
                {
                    "id": f"ap-offline-{did}",
                    "device_id": did,
                    "device_name": name,
                    "issue_type": "offline",
                    "severity": "crit",
                    "message": (
                        f"{name} está OFFLINE — sem hashrate reportado. "
                        "Reiniciar costuma recuperar o miner em segundos."
                    ),
                    "action": {
                        "type": "restart" if can_restart else "navigate",
                        "label": "REINICIAR" if can_restart else "VER FLEET",
                    },
                }
            )
            continue  # offline devices: one recommendation is enough

        # ── 2. temp_high → pause (warn) ──
        if temp is not None and temp >= AP_TEMP_HIGH_C:
            recs.append(
                {
                    "id": f"ap-temp_high-{did}",
                    "device_id": did,
                    "device_name": name,
                    "issue_type": "temp_high",
                    "severity": "warn",
                    "message": (
                        f"{name} a {temp:.0f}°C (limite {AP_TEMP_HIGH_C:.0f}°C) — "
                        "risco térmico. Pause e melhore o airflow."
                    ),
                    "action": {
                        "type": "pause" if can_pause else "navigate",
                        "label": "PAUSAR" if can_pause else "VER FLEET",
                    },
                }
            )

        # ── 3. hashrate_drop → restart (gold) ──
        peak = _num(peak_7d)
        if peak and hr and hr > 0 and hr < peak * AP_HASHRATE_DROP_RATIO:
            drop_pct = (1 - hr / peak) * 100
            recs.append(
                {
                    "id": f"ap-hashrate_drop-{did}",
                    "device_id": did,
                    "device_name": name,
                    "issue_type": "hashrate_drop",
                    "severity": "gold",
                    "message": (
                        f"{name} com hashrate {drop_pct:.0f}% abaixo do pico de 7d "
                        "— restart ou verificação de rede local."
                    ),
                    "action": {
                        "type": "restart" if can_restart else "navigate",
                        "label": "REINICIAR" if can_restart else "VER FLEET",
                    },
                }
            )

    # ── 4. rig_poor → blacklist (warn) ──
    for r in worst_rigs or []:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("rig_id") or "").strip()
        if not rid or rid in blacklist:
            continue
        danger = _num(r.get("danger"))
        if danger is None or danger < AP_RIG_POOR_DANGER_MIN:
            continue
        rname = str(r.get("name") or rid)
        recs.append(
            {
                "id": f"ap-rig_poor-{rid}",
                "device_id": rid,
                "device_name": rname,
                "issue_type": "rig_poor",
                "severity": "warn",
                "message": (
                    f"Rig {rname} com danger {danger:.0f}/100 e entrega média "
                    f"{r.get('ewma_delivery_pct', '?')}% — adicione à blacklist "
                    "para não alugar de novo."
                ),
                "action": {"type": "blacklist", "label": "BLACKLIST RIG"},
            }
        )

    # ── 5. buy window → comprar (gold) ──
    if arb_window:
        recs.append(
            {
                "id": "ap-buy-window",
                "device_id": "",
                "device_name": "Hash Market",
                "issue_type": "buy",
                "severity": "gold",
                "message": (
                    "Janela de arbitragem aberta — mercado abaixo do seu custo "
                    "médio. Comprar hashrate agora captura a diferença."
                ),
                "action": {"type": "buy", "label": "COMPRAR AGORA"},
            }
        )

    # Rank by severity (crit > gold > warn), stable by rule order.
    recs.sort(key=lambda r: _AP_SEVERITY_ORDER.get(r.get("severity", "info"), 99))
    return recs


# ─────────────────────────────────────────────────────────────────────────
#  Real-data collection (tenant-scoped, fail-closed)
# ─────────────────────────────────────────────────────────────────────────


def _collect_fleet(tenant_id: str = "") -> List[dict]:
    """Live fleet devices with telemetry from the axe registry."""
    try:
        from axe_fleet.routes import _registry

        if _registry is None:
            return []
        return _registry.list_devices(tenant_id=tenant_id, with_telemetry=True) or []
    except Exception as e:
        log.warning("[auto_pilot] fleet collection failed: %s", e)
        return []


def _collect_peak_7d(tenant_id: str = "") -> float:
    """Max worker hashrate observed over the last 7 days (proximity_history)."""
    try:
        from services.db import get_db

        conn = get_db()
        row = conn.execute(
            "SELECT MAX(worker_hashrate) FROM proximity_history WHERE ts >= ?",
            (int(time.time()) - 7 * 86400,),
        ).fetchone()
        conn.close()
        if row and row[0]:
            return float(row[0])
    except Exception as e:
        log.warning("[auto_pilot] peak query failed: %s", e)
    return 0.0


def _collect_worst_rigs(tenant_id: str = "", limit: int = 6) -> List[dict]:
    try:
        from services.rental_performance import compute_worst_rigs

        return (compute_worst_rigs(tenant_id=tenant_id, limit=limit) or {}).get(
            "worst", []
        )
    except Exception as e:
        log.warning("[auto_pilot] worst rigs failed: %s", e)
        return []


def _collect_arb_window(tenant_id: str = "") -> list:
    try:
        from services.rental_performance import evaluate_market_arb_alerts

        return evaluate_market_arb_alerts(tenant_id=tenant_id, dry_run=True) or []
    except Exception as e:
        log.warning("[auto_pilot] arb window failed: %s", e)
        return []


def _collect_blacklisted(tenant_id: str = "") -> List[str]:
    try:
        from services.rental_performance import get_rig_blacklist

        return get_rig_blacklist(tenant_id=tenant_id) or []
    except Exception as e:
        log.warning("[auto_pilot] blacklist read failed: %s", e)
        return []


def build_recommendations_for_tenant(tenant_id: str = "") -> List[Dict[str, Any]]:
    """Collect real data for the tenant and build advisory recommendations.

    Fail-closed: any collection error degrades to the empty list.
    """
    return build_advisory_recommendations(
        fleet=_collect_fleet(tenant_id),
        peak_7d=_collect_peak_7d(tenant_id),
        worst_rigs=_collect_worst_rigs(tenant_id),
        arb_window=_collect_arb_window(tenant_id),
        blacklisted_rigs=_collect_blacklisted(tenant_id),
    )


# ─────────────────────────────────────────────────────────────────────────
#  Audit trail — accepted / ignored recommendations (per tenant)
# ─────────────────────────────────────────────────────────────────────────


def _ensure_audit_table(conn) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {AP_AUDIT_TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT '',
        rec_id TEXT NOT NULL,
        device_id TEXT NOT NULL DEFAULT '',
        device_name TEXT NOT NULL DEFAULT '',
        issue_type TEXT NOT NULL DEFAULT '',
        action_type TEXT NOT NULL DEFAULT '',
        decision TEXT NOT NULL,      -- accepted | ignored
        note TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '',
        created_ts INTEGER
    )"""
    )
    conn.commit()


def record_rec_decision(
    tenant_id: str,
    rec: Dict[str, Any],
    decision: str,
    note: str = "",
    action_result: Optional[Dict[str, Any]] = None,
) -> bool:
    """Record an accepted/ignored recommendation in the audit trail.

    Returns True on success. Fail-closed: storage hiccup → False, never a
    raise into the caller.
    """
    try:
        from services.db import get_db

        conn = get_db()
        _ensure_audit_table(conn)
        now = int(time.time())
        result_json = json.dumps(action_result)[:500] if action_result else ""
        # AP_AUDIT_TABLE is an internal module constant — no user input.
        conn.execute(
            f"INSERT INTO {AP_AUDIT_TABLE} "  # nosec B608
            "(ts, tenant_id, rec_id, device_id, device_name, issue_type, "
            " action_type, decision, note, result, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now,
                tenant_id or "default",
                str(rec.get("id") or ""),
                str(rec.get("device_id") or ""),
                str(rec.get("device_name") or ""),
                str(rec.get("issue_type") or ""),
                str((rec.get("action") or {}).get("type") or ""),
                decision,
                (note or "")[:500],
                result_json,
                now,
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning("[auto_pilot] audit record failed: %s", e)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  Fase 4 (Issue #178): execução autônoma atrás do gate PRO
#  O piloto armado + PRO + execução autônoma ON age SOZINHO sobre as ações
#  físicas das recomendações advisory — restart/pause/underclock — sem o
#  clique manual do operador, respeitando safety + cooldown + orçamento e
#  auditando cada resultado no auto_pilot_rec_audit (note="autonomous").
# ═══════════════════════════════════════════════════════════════════════

# Apenas ações FÍSICAS e reversíveis auto-executam. Ações financeiras
# (blacklist de rig = decisão contratual; buy = dinheiro real) e
# informativas (navigate) continuam MANUAIS — o piloto nunca gasta dinheiro
# nem muda contratos sozinho.
AUTONOMOUS_SAFE_ACTIONS = ("restart", "pause", "underclock")

# Cooldown por ação (segundos): restart é pesado (reboot do miner leva
# ~2min) → 15min entre restarts do MESMO device; pause (resfriamento) pode
# agir mais rápido. Env-tunable para power users.
_AUTONOMOUS_COOLDOWN_S = {
    "restart": int(os.environ.get("AUTO_PILOT_RESTART_COOLDOWN_S", "900")),
    "pause": int(os.environ.get("AUTO_PILOT_PAUSE_COOLDOWN_S", "600")),
    "underclock": int(os.environ.get("AUTO_PILOT_UNDERCLOCK_COOLDOWN_S", "900")),
}
AUTONOMOUS_DEFAULT_COOLDOWN_S = 900

# (tenant_id, device_id, action) -> last execution ts. Thread-safe via lock
# (o pass autônomo roda na thread do poll; o toggle na thread da request).
_autonomous_cooldown: Dict[tuple, int] = {}
_autonomous_lock = threading.Lock()


def _autonomous_cooldown_for(action: str) -> int:
    return _AUTONOMOUS_COOLDOWN_S.get(action, AUTONOMOUS_DEFAULT_COOLDOWN_S)


def is_autonomous_enabled(tenant_id: str = "") -> bool:
    """Execução autônoma ligada para o tenant (fail-closed: default OFF)."""
    try:
        from services.settings import load_settings

        s = load_settings(tenant_id=tenant_id or "default")
        return str(s.get("auto_pilot_autonomous") or "").strip() == "1"
    except Exception:
        return False


def set_autonomous_enabled(tenant_id: str = "", enabled: bool = False) -> bool:
    """Persist the autonomous toggle (settings whitelist enforces the key)."""
    try:
        from services.settings import save_setting

        return bool(
            save_setting(
                "auto_pilot_autonomous",
                "1" if enabled else "0",
                tenant_id=tenant_id or "default",
            )
        )
    except Exception:
        return False


def autonomous_status(tenant_id: str = "") -> Dict[str, Any]:
    """Status do toggle para o módulo Automations (gate + switches)."""
    from core.alerts.automation_engine import AutomationEngine
    from services.licensing import server_pro_active

    tid = tenant_id or "default"
    engine = AutomationEngine("", None)  # settings-only reads
    return {
        "pro": server_pro_active(),
        "armed": engine.is_armed(tid),
        "autonomous": is_autonomous_enabled(tid),
        "safe_actions": list(AUTONOMOUS_SAFE_ACTIONS),
        "cooldowns": dict(_AUTONOMOUS_COOLDOWN_S),
    }


def execute_autonomous_actions(
    tenant_id: str = "",
    engine=None,
    execute_fn=None,
    recs: Optional[List[Dict[str, Any]]] = None,
    fleet: Optional[List[dict]] = None,
    now: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fase 4 — o piloto armado + PRO executa sozinho as ações físicas das
    recomendações advisory (restart/pause/underclock).

    Gates (TODOS precisam passar — fail-closed, como o resto do Auto-Pilot):
      1. ``server_pro_active()``   — gate PRO (open mode = sempre True)
      2. ``engine.is_armed(tid)``  — piloto explicitamente ARMADO
      3. ``is_autonomous_enabled`` — toggle de execução autônoma ON

    Depois, por recomendação com ação segura:
      - cooldown por (tenant, device, ação) — nunca repete no mesmo window
      - orçamento por tenant COMPARTILHADO com as regras (um orçamento do
        piloto — o mesmo _consume_action_budget do AutomationEngine)
      - SafetyEngine (fail-closed: bloqueou = não executa, audita BLOCKED)
      - execute_fn(device_id, command) → executor do fleet (fila do agente)
      - cada execução/erro auditado no auto_pilot_rec_audit com
        decision="accept", note="autonomous"

    ``recs``/``fleet`` injetáveis para testes herméticos (quando None, coleta
    do registry real). Nunca levanta: falha por item degrada a um status.

    Returns:
        Lista de resultados por item:
          {rec_id, device_id, action, status: executed|blocked|rate_limited|
           cooldown|skipped|error, reason, ts}
    """
    results: List[Dict[str, Any]] = []
    tid = tenant_id or "default"
    now = int(time.time()) if now is None else now
    try:
        from services.licensing import server_pro_active

        if not server_pro_active():
            return [{"status": "skipped", "reason": "pro_gate", "ts": now}]
        if engine is None:
            return [{"status": "skipped", "reason": "no_engine", "ts": now}]
        if not engine.is_armed(tid):
            return [{"status": "skipped", "reason": "not_armed", "ts": now}]
        if not is_autonomous_enabled(tid):
            return [{"status": "skipped", "reason": "not_enabled", "ts": now}]

        if fleet is None:
            fleet = _collect_fleet(tid)
        if recs is None:
            recs = build_advisory_recommendations(
                fleet=fleet,
                peak_7d=_collect_peak_7d(tid),
                worst_rigs=_collect_worst_rigs(tid),
                arb_window=_collect_arb_window(tid),
                blacklisted_rigs=_collect_blacklisted(tid),
            )
        fleet_by_id = {str(d.get("id") or ""): d for d in (fleet or [])}

        for rec in recs or []:
            action = rec.get("action") or {}
            atype = str(action.get("type") or "").lower()
            if atype not in AUTONOMOUS_SAFE_ACTIONS:
                continue  # blacklist / buy / navigate ficam manuais
            did = str(rec.get("device_id") or "")
            if not did:
                continue

            # Cooldown por (tenant, device, ação) — nunca repete no window.
            key = (tid, did, atype)
            with _autonomous_lock:
                last = _autonomous_cooldown.get(key, 0)
                if (now - last) < _autonomous_cooldown_for(atype):
                    results.append(
                        {
                            "rec_id": rec.get("id"),
                            "device_id": did,
                            "action": atype,
                            "status": "cooldown",
                            "reason": "",
                            "ts": now,
                        }
                    )
                    continue
                _autonomous_cooldown[key] = now

            # Orçamento compartilhado do piloto (janela rolante por tenant).
            if not engine._consume_action_budget(tid, now):
                results.append(
                    {
                        "rec_id": rec.get("id"),
                        "device_id": did,
                        "action": atype,
                        "status": "rate_limited",
                        "reason": "tenant action budget exceeded",
                        "ts": now,
                    }
                )
                continue

            # SafetyEngine (fail-closed): valida o Device core montado do
            # dict vivo do fleet (mesma ponte da Fase 3 dry-run).
            dev = fleet_by_id.get(did)
            if dev is None:
                results.append(
                    {
                        "rec_id": rec.get("id"),
                        "device_id": did,
                        "action": atype,
                        "status": "skipped",
                        "reason": "device_not_found",
                        "ts": now,
                    }
                )
                continue
            safety = None
            try:
                safety = engine.safety_engine.validate_command(
                    axe_fleet_to_device(dev), atype, {}
                )
            except Exception as e:
                results.append(
                    {
                        "rec_id": rec.get("id"),
                        "device_id": did,
                        "action": atype,
                        "status": "error",
                        "reason": "safety check failed: %s" % e,
                        "ts": now,
                    }
                )
                continue
            if safety is not None and not safety.allowed:
                reason = safety.reason or "SafetyEngine blocked action"
                record_rec_decision(
                    tid,
                    rec,
                    "accept",
                    note="autonomous:blocked",
                    action_result={"ok": False, "error": reason},
                )
                results.append(
                    {
                        "rec_id": rec.get("id"),
                        "device_id": did,
                        "action": atype,
                        "status": "blocked",
                        "reason": reason,
                        "ts": now,
                    }
                )
                continue

            outcome: Dict[str, Any] = {"ok": False, "error": "no executor"}
            if execute_fn is not None:
                try:
                    outcome = execute_fn(did, atype) or outcome
                except Exception as e:
                    outcome = {"ok": False, "error": str(e)}
            record_rec_decision(
                tid,
                rec,
                "accept",
                note="autonomous" if outcome.get("ok") else "autonomous:error",
                action_result=outcome,
            )
            results.append(
                {
                    "rec_id": rec.get("id"),
                    "device_id": did,
                    "action": atype,
                    "status": "executed" if outcome.get("ok") else "error",
                    "reason": outcome.get("error", ""),
                    "ts": now,
                }
            )
        return results
    except Exception as e:
        log.warning("[auto_pilot] autonomous pass failed: %s", e)
        return [{"status": "error", "reason": str(e), "ts": now}]


def get_rec_audit(tenant_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """Recent accepted/ignored recommendations for the tenant (ts desc)."""
    try:
        from services.db import get_db

        conn = get_db()
        _ensure_audit_table(conn)
        # AP_AUDIT_TABLE is an internal module constant — no user input.
        rows = conn.execute(
            f"SELECT * FROM {AP_AUDIT_TABLE} WHERE tenant_id=? "
            "ORDER BY ts DESC, id DESC LIMIT ?",  # nosec B608
            (tenant_id or "default", max(1, min(int(limit), 200))),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning("[auto_pilot] audit read failed: %s", e)
        return []
