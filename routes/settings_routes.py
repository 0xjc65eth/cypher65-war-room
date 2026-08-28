"""
CYPHER65 // Settings API routes
================================
Flask Blueprint for /api/settings endpoints.
Extracted from app.py — Phase 2a of P0.4 refactoring.
"""

import logging
import os
import time

from flask import Blueprint, jsonify, request

from config import BTC_ADDRESS, WORKER_NAME

log = logging.getLogger("cypher65.settings")
from services.settings import (
    DEFAULT_SETTINGS,
    credential_keys,
    is_default_tenant,
    load_settings,
    save_setting,
    settings_label,
)
from services.tenant import require_tenant, role_required, log_audit
from services.licensing import is_pro

settings_bp = Blueprint("settings", __name__, url_prefix="/api")


@settings_bp.route("/settings", methods=["GET"])
@require_tenant
def api_settings_get(tenant_id: str = ""):
    s = load_settings(tenant_id=tenant_id)
    out = []
    secret_keys = credential_keys()
    for k, v in DEFAULT_SETTINGS.items():
        is_secret = k in secret_keys
        current = s.get(k, v)
        out.append(
            {
                "key": k,
                "value": "" if is_secret else current,
                "default": "" if is_secret else v,
                "label": settings_label(k),
                "secret": is_secret,
                "configured": bool(current) if is_secret else None,
            }
        )
    # Which credential settings are currently OVERRIDDEN by an env var.
    # On a deployed instance (Render) BRAIINS_API_KEY/MRR_API_KEY set in the
    # environment silently win over the Settings modal — surfacing it here
    # lets the UI warn the operator that editing the field won't take effect
    # until the env var is removed. Booleans only — never the values.
    # IMPORTANT: only the operator's default tenant is affected by env vars;
    # named tenants NEVER inherit env credentials (they use their own rows),
    # so env_overrides is all-False for them.
    env_overrides = {
        "braiins_api_key": is_default_tenant(tenant_id)
        and bool((os.environ.get("BRAIINS_API_KEY") or "").strip()),
        "mrr_api_key": is_default_tenant(tenant_id)
        and bool((os.environ.get("MRR_API_KEY") or "").strip()),
        "mrr_api_secret": is_default_tenant(tenant_id)
        and bool((os.environ.get("MRR_API_SECRET") or "").strip()),
    }
    return jsonify(
        {
            "settings": out,
            "freshness_ts": int(time.time()),
            "env_overrides": env_overrides,
            "tenant_id": tenant_id or "default",
        }
    )


@settings_bp.route("/settings", methods=["POST"])
@require_tenant
@role_required("member")
def api_settings_post(tenant_id: str = ""):
    """POST JSON body: {key: value, key: value, ...}"""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "expected JSON object body"}), 400
    applied = []
    rejected = []
    preserved = []
    secret_keys = credential_keys()
    clear_keys = body.pop("_clear_credentials", [])
    if not isinstance(clear_keys, list) or any(
        k not in secret_keys for k in clear_keys
    ):
        return (
            jsonify({"error": "_clear_credentials must contain credential keys"}),
            400,
        )
    for key in clear_keys:
        if save_setting(key, "", tenant_id=tenant_id):
            applied.append(key)
        else:
            rejected.append({"key": key, "reason": "db error"})
    for k, v in body.items():
        # R1 (PRO tier): webhooks are a PRO feature. Off-by-default — the
        # gate only fires when the operator sets PRO_LICENSE_KEYS and the
        # caller has no valid key; otherwise is_pro() is True in open mode.
        if k == "webhook_url" and not is_pro():
            rejected.append(
                {"key": k, "reason": "PRO feature — requires a license key"}
            )
            continue
        # Allow internal keys (prefixed with '_') and known settings
        if not k.startswith("_") and k not in DEFAULT_SETTINGS:
            rejected.append({"key": k, "reason": "unknown key"})
            continue
        if k in secret_keys and (v is None or str(v).strip() == ""):
            preserved.append(k)
            continue
        if save_setting(k, v, tenant_id=tenant_id):
            applied.append(k)
        else:
            rejected.append({"key": k, "reason": "db error"})
    return jsonify({"applied": applied, "preserved": preserved, "rejected": rejected})


@settings_bp.route("/settings/test-braiins", methods=["POST"])
@require_tenant
@role_required("member")
def api_settings_test_braiins(tenant_id: str = ""):
    """Validate the configured Braiins Hashpower key against the live API.

    Same probe the RENTALS panel runs (fetch_braiins_contracts), with an
    explicit verdict so the operator can diagnose "chave não reconhecida"
    right inside the Settings modal:
      - configured: False           → no key stored anywhere
      - verdict "ok"                → key accepted (n contracts/bids found)
      - verdict "rejected" (401/403) → key present but the API refused it
      - env_override: True          → an env var beats the field below
    """
    from agents.solo_mining_advisor.tools import braiins_credentials
    from services import rental_performance as _rp

    # Tenant-scoped: the test probes the CALLER's own key. Env-var override
    # only applies to the operator's default tenant (named tenants never
    # inherit env credentials).
    env_key = is_default_tenant(tenant_id) and bool(
        (os.environ.get("BRAIINS_API_KEY") or "").strip()
    )
    key = (braiins_credentials(tenant_id=tenant_id).get("api_key") or "").strip()
    if not key:
        return jsonify(
            {
                "success": False,
                "configured": False,
                "status": "missing",
                "provider": "braiins",
                "read_only": True,
                "env_override": env_key,
                "error": "BRAIINS_API_KEY not configured — add the owner token below",
            }
        )

    try:
        result = _rp.fetch_braiins_contracts(tenant_id=tenant_id)
        if result.get("needs_auth"):
            return jsonify(
                {
                    "success": False,
                    "configured": True,
                    "status": "rejected",
                    "provider": "braiins",
                    "read_only": True,
                    "env_override": env_key,
                    "verdict": "rejected",
                    "error": result.get("error")
                    or "Braiins API rejected the key (HTTP 401/403)",
                }
            )
        if not result.get("success"):
            return jsonify(
                {
                    "success": False,
                    "configured": True,
                    "status": "provider_error",
                    "provider": "braiins",
                    "read_only": True,
                    "env_override": env_key,
                    "verdict": "error",
                    "error": result.get("error") or "Braiins API returned no data",
                }
            )
        return jsonify(
            {
                "success": True,
                "configured": True,
                "status": "accepted",
                "provider": "braiins",
                "read_only": True,
                "env_override": env_key,
                "verdict": "ok",
                "contracts": len(result.get("contracts", [])),
            }
        )
    except Exception as e:
        log.warning("[settings] Braiins credential probe failed: %s", type(e).__name__)
        return (
            jsonify(
                {
                    "success": False,
                    "configured": True,
                    "status": "provider_unavailable",
                    "provider": "braiins",
                    "read_only": True,
                    "env_override": env_key,
                    "verdict": "error",
                    "error": "Braiins provider unavailable or returned an invalid response",
                }
            ),
            502,
        )


@settings_bp.route("/settings/test-mrr", methods=["POST"])
@require_tenant
@role_required("member")
def api_settings_test_mrr(tenant_id: str = ""):
    """Run a single read-only, tenant-scoped MRR authentication probe."""
    from services.rental_performance import probe_mrr_credentials

    result = probe_mrr_credentials(tenant_id=tenant_id)
    env_override = is_default_tenant(tenant_id) and bool(
        (os.environ.get("MRR_API_KEY") or "").strip()
        or (os.environ.get("MRR_API_SECRET") or "").strip()
    )
    payload = {
        **result,
        "env_override": env_override,
        "checked_at": int(time.time()),
        "endpoint": "/whoami",
        "read_only": True,
    }
    log_audit(
        tenant_id,
        "settings.provider_diagnostic",
        target="mrr",
        details={
            "status": result.get("status"),
            "configured": result.get("configured"),
        },
    )
    return jsonify(payload)


@settings_bp.route("/settings/test-webhook", methods=["POST"])
@require_tenant
@role_required("member")
def api_settings_test_webhook(tenant_id: str = ""):
    """Send a sample alert payload to the configured webhook_url.

    UX audit Quick Win: lets the operator validate the notification channel
    (Discord/Telegram) without waiting for a real alert event. Same payload
    shape the polling loop fires on every alert, same PRO gate as webhook_url.
    """
    s = load_settings(tenant_id=tenant_id)
    url = (s.get("webhook_url") or "").strip()
    if not url:
        return (
            jsonify({"error": "webhook_url not configured — set it in Settings first"}),
            400,
        )
    if not is_pro():
        return jsonify({"error": "PRO feature — requires a license key"}), 403
    payload = {
        "event": "cypher65_war_room_alert",
        "severity": "TEST",
        "category": "test",
        "message": "🧪 Teste do CYPHER65 — se você leu esta mensagem, seu webhook está configurado corretamente",
        "ts": int(time.time()),
        "worker": WORKER_NAME,
        "address": BTC_ADDRESS,
    }
    try:
        import requests  # lazy: this module stays dependency-free at import time

        r = requests.post(url, json=payload, timeout=6)
        return jsonify({"success": True, "status_code": r.status_code})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 502


@settings_bp.route("/settings/test-auto-exclude-alert", methods=["POST"])
@require_tenant
@role_required("member")
def api_settings_test_auto_exclude_alert(tenant_id: str = ""):
    """Send a SAMPLE auto-exclusion alert (webhook + push) to validate the
    tenant's notification configuration.

    Unlike test-webhook (generic payload, webhook only), this fires the SAME
    message shape the periodic sweep dispatches on a real auto-exclusion
    (Issue #102) through the SAME builders the async dispatch path uses
    (send_webhook_for_alert + notify_tenant_alert), synchronously, so the
    operator gets a real verdict: ``webhook_ok`` + ``push_targets``.

    Response (always 200 unless PRO-gated):
      - message: the sample payload that was (or would be) sent
      - webhook_configured / webhook_ok / webhook_reason / webhook_min_severity
      - push_targets: number of devices the push reached (0 = none)
      - success: True when at least one channel delivered
      - guidance: actionable hint when nothing is configured

    PRO gate: unlike test-webhook (403 for every non-PRO caller), this only
    gates the WEBHOOK channel (403 when a URL is configured and the license
    gate is closed) — Web Push is not a PRO feature, so a push-only tenant
    can still validate its channel without a key.
    Never raises.
    """
    s = load_settings(tenant_id=tenant_id)
    url = (s.get("webhook_url") or "").strip()
    min_sev = s.get("webhook_min_severity", "WARN")
    # Same PRO gate as webhook_url itself + test-webhook: only relevant when
    # PRO_LICENSE_KEYS is set (open mode → is_pro() is always True).
    if url and not is_pro():
        return jsonify({"error": "PRO feature — requires a license key"}), 403

    severity = "WARN"
    category = "rental_auto_exclude"
    ts = int(time.time())
    message = (
        "rig rig-teste auto-excluído por sub-entrega — grade F · entrega "
        "57.5% · 2 amostras — régua: floor F, mín 2 · "
        "[TESTE — nenhuma exclusão real foi feita]"
    )

    webhook_ok = False
    webhook_reason = "not configured"
    if url:
        from services.push_notifier import (
            send_webhook_for_alert,
            severity_meets_threshold,
        )

        try:
            webhook_ok = send_webhook_for_alert(
                url=url,
                severity=severity,
                category=category,
                message=message,
                ts=ts,
                min_severity=min_sev,
            )
        except Exception:
            webhook_ok = False
        if webhook_ok:
            webhook_reason = "ok"
        elif not severity_meets_threshold(severity, min_sev):
            webhook_reason = f"below threshold (WARN < {min_sev})"
        else:
            webhook_reason = "POST failed — check the URL"

    # notify_tenant_alert never raises (per-subscription try/except, VAPID +
    # pywebpush guards) — belt-and-suspenders wrapper for the endpoint.
    push_targets = 0
    from services.push_notifier import notify_tenant_alert

    try:
        push_targets = notify_tenant_alert(tenant_id, severity, category, message)
    except Exception as e:
        push_targets = 0
        log.warning("[settings] test push error: %s", e)

    success = bool(webhook_ok or push_targets > 0)
    guidance = ""
    if not url and push_targets <= 0:
        guidance = (
            "nenhum canal configurado — configure webhook_url e/ou assine "
            "Web Push (VAPID) neste navegador para receber o alerta real"
        )
    return jsonify(
        {
            "success": success,
            "message": message,
            "severity": severity,
            "category": category,
            "webhook_configured": bool(url),
            "webhook_ok": webhook_ok,
            "webhook_reason": webhook_reason,
            "webhook_min_severity": min_sev,
            "push_targets": push_targets,
            "guidance": guidance,
        }
    )


# ── FASE 2: Wallet history endpoint ──


@settings_bp.route("/wallet/history", methods=["GET"])
@require_tenant
@role_required("viewer")
def get_wallet_history(tenant_id: str = ""):
    """Return list of past wallet addresses, most recent first."""
    try:
        from app import get_db

        conn = get_db()
        rows = conn.execute(
            "SELECT address, worker, connected_at, label FROM wallet_address_history "
            "ORDER BY connected_at DESC LIMIT 20"
        ).fetchall()
        conn.close()
        return jsonify({"success": True, "history": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
