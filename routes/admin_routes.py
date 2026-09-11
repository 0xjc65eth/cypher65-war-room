"""
CYPHER65 // Admin & licensing routes
====================================
Flask Blueprint for the operator-only ``/api/admin/*`` surface.

RFC #478 · PR B1 (Issue #495): mechanical extraction from app.py — same
bodies, same status codes, same payloads, same gate decision. Nothing in
this module is new behaviour.

Routes served (all under /api/admin):
  /docs-feedback, /sessions, /pool-metrics, /error-rate, /degradation-rate,
  /licenses, /analytics, /postgres-readiness, /conversion,
  /rentals/accepted-recos

The shared admin gate ``_admin_request_allowed`` now lives HERE (single
source of truth) and is re-exported by app.py, so
``from app import _admin_request_allowed`` keeps working.

Every route below is gated — including ``/api/admin/sessions``. That was the
last hole (Issue #496): the route predates the gate and leaked the session
list of ALL tenants (``to_dict()`` carries ``btc_address`` and ``tenant_id``)
to any origin. It now applies the same gate as its neighbours, so the
ungated set is empty and the contract test
``test_ungated_admin_routes_are_exactly_the_known_gap`` pins it that way.
"""

import hmac
import os
import time

from flask import Blueprint, Response, jsonify, request

import services.beta_analytics as _beta_analytics
import services.conversion as _conversion
import services.doc_feedback as _doc_feedback
import services.error_tracker as _error_tracker
import services.postgres_readiness as _postgres_readiness
import services.rental_performance as _rental_perf
from config import DB_PATH
from services.db import get_db
from services.licensing import issue_license as _licensing_issue
from services.sentry_telemetry import get_sentry_config, sentry_active as _sentry_active
from services.user_polling import (
    POLL_POOL as _POLL_POOL,
    auto_exclude_alert_counters as _auto_exclude_alert_counters,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

# Honest Sentry badge on /api/admin/error-rate: parsed once at import from the
# same env-gated config app.py uses (compute_release() is cached, so this
# costs no extra git call).
_SENTRY_CFG = get_sentry_config()
_SENTRY_ENVIRONMENT = _SENTRY_CFG["environment"]

# The session store is owned by app.py (constructed at boot). It is injected
# instead of imported to avoid a runtime circular import — same pattern as
# axe_fleet.init_routes() and alerts_routes._set_get_db().
_session_manager = None


def init_admin_routes(session_manager):
    """Inject the boot SessionManager (called from app.py)."""
    global _session_manager
    _session_manager = session_manager


def _admin_request_allowed() -> bool:
    """Admin gate compartilhado (Issue #254) — localhost REAL ou X-API-Key.

    Sev-2 fix: no Render (e em qualquer proxy reverso) o `remote_addr` do
    request vira loopback — o gate antigo (`remote_addr in loopback`) tratava
    o proxy como operador local e expunha as rotas /api/admin/* publicamente
    (validado em produção: /api/admin/conversion respondia 200 sem key).
    Agora a presença de header de proxy (X-Forwarded-For / Forwarded) marca o
    request como REMOTO → exige X-API-Key válida. Localhost real (sem proxy)
    segue liberado para dev / ssh-tunnel.

    Fail-closed para credenciais declaradas (Issue #481): se o chamador
    ENVIA um X-API-Key (declara uma credencial) e ela NÃO confere com a
    API_KEY do operador, o request é NEGADO mesmo vindo de localhost —
    não há "sucesso autenticado" com credencial inválida. Comportamento
    idêntico em remote (que já exigia a key). Ausência de header em
    localhost continua liberada (dev / Render Shell), e API_KEY não
    configurada preserva o localhost-trust original (Issue #254).
    """
    remote = (request.remote_addr or "").strip()
    operator_key = (os.environ.get("API_KEY") or "").strip()
    sent = (request.headers.get("X-API-Key") or "").strip()
    proxied = bool(
        (request.headers.get("X-Forwarded-For") or "").strip()
        or (request.headers.get("Forwarded") or "").strip()
    )
    local = (not proxied) and remote in ("127.0.0.1", "::1", "localhost")
    key_matches = bool(operator_key and hmac.compare_digest(sent, operator_key))
    # Credencial declarada e errada → fail-closed (Issue #481), em qualquer
    # origem. Credencial correta → sempre autorizado.
    if sent and not key_matches:
        return False
    return local or key_matches


@admin_bp.route("/docs-feedback", methods=["GET"])
def api_admin_docs_feedback():
    """Admin-gated summary of doc feedback (Learning FAQ loop).

    Same gate as /api/admin/conversion (localhost or operator X-API-Key).
    Returns per-section helpful %, totals, and the recurring questions list
    (comments typed on thumbs-down votes) — the input to the FAQ loop.
    """
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403
    return jsonify(_doc_feedback.doc_feedback_summary())


@admin_bp.route("/sessions", methods=["GET"])
def api_admin_sessions():
    """List all active sessions + pool observability (debug/admin).

    Admin-gated exactly like the other routes in this blueprint (localhost
    without a declared credential, or the operator X-API-Key) — Issue #496.
    Before the fix this endpoint answered ANY origin and returned every
    tenant's session (``btc_address``, ``tenant_id``); it now fails closed to
    403 like its neighbours.

    The ``pool`` block exposes PollWorkerPool health: active sessions,
    polls/sec (sliding 60s window), ready-queue depth, scheduled heap,
    live worker threads, total poll/error counters, and auto_exclude_alerts
    (auto-exclusion alerts dispatched by path: sweep vs panel) — everything
    an operator needs to spot a thundering-herd or a stuck pool at a glance.
    """
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403
    sessions = _session_manager.get_all_sessions()
    pool = _POLL_POOL.stats()  # never raises, even on an unstarted pool
    # Auto-exclude alert observability (Issue #112): how many alertas the
    # pilot dispatched per path (sweep do pool vs detail do painel) — same
    # in-memory lifecycle as the pool counters.
    pool["auto_exclude_alerts"] = _auto_exclude_alert_counters()
    return jsonify(
        {
            "count": len(sessions),
            "sessions": [s.to_dict() for s in sessions],
            "pool": pool,
        }
    )


@admin_bp.route("/pool-metrics", methods=["GET"])
def api_admin_pool_metrics():
    """Pool-health trend history from the persistent 60s sampler (Issue #17).

    Admin-gated exactly like /api/admin/conversion (localhost or the operator
    X-API-Key) — never exposed to the public. Returns the pool_metrics rows
    (sessions_active, polls_per_sec, queue_pending, total_polls, …) over the
    last ``hours`` (default 24) so the Admin CFO renders trend lines that
    survive restarts (unlike the in-memory /api/admin/sessions counters).
    """
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403

    hours = request.args.get("hours", 24, type=int)
    if hours < 1 or hours > 7 * 24:
        hours = 24
    limit = request.args.get("limit", 0, type=int)
    if limit < 0 or limit > 2000:
        limit = 0
    if limit == 0:
        # Default cap keeps the JSON/Chart.js light: 24h@60s = 1440 points.
        limit = 1500
    from services.pool_metrics import fetch_history as _fetch_pm

    conn = get_db()
    try:
        points = _fetch_pm(conn, hours=hours, limit=limit)
    finally:
        conn.close()
    return jsonify({"hours": hours, "count": len(points), "points": points})


@admin_bp.route("/error-rate", methods=["GET"])
def api_admin_error_rate():
    """Error-rate telemetry (Issue #176) — admin-gated like pool-metrics.

    Returns the local error_metrics aggregation: total error events in the
    window, peak per hour, hourly buckets with per-module breakdown, top
    modules, and the most recent errors WITH their request_id (so an
    operator can correlate with the JSON logs / Sentry). The ``sentry_enabled``
    flag drives the admin badge — honest: local telemetry works with or
    without a DSN.
    """
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403

    hours = request.args.get("hours", 24, type=int)
    if hours < 1 or hours > 7 * 24:
        hours = 24
    limit = request.args.get("limit", 60, type=int)
    if limit < 1 or limit > 500:
        limit = 60
    conn = get_db()
    try:
        data = _error_tracker.fetch_error_rate(conn, hours=hours, limit=limit)
    finally:
        conn.close()
    # Honest badge: reflects whether the SDK actually INIT'd (DSN set AND
    # package importable) — never claims Sentry is on when init was skipped.
    data["sentry_enabled"] = _sentry_active()
    data["sentry_release"] = _SENTRY_CFG["release"]
    data["sentry_environment"] = _SENTRY_ENVIRONMENT
    return jsonify(data)


@admin_bp.route("/degradation-rate")
def api_admin_degradation_rate():
    """WARNING/degradation telemetry (Issue #202) — admin-gated like error-rate.

    Same gate (localhost or operator X-API-Key). Returns the
    degradation_metrics aggregation: total WARNINGs in the window, peak per
    hour, hourly buckets with per-module breakdown, top modules, and the most
    recent warnings WITH their request_id — plus the rate-alert flags (``spike``
    = pico >= 100/h; ``sustained`` = warnings in >= 2 distinct hours) and the
    since-boot counter. Honest: an empty response means zero warnings.
    """
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403

    hours = request.args.get("hours", 24, type=int)
    if hours < 1 or hours > 7 * 24:
        hours = 24
    limit = request.args.get("limit", 60, type=int)
    if limit < 1 or limit > 500:
        limit = 60
    conn = get_db()
    try:
        data = _error_tracker.fetch_degradation_rate(conn, hours=hours, limit=limit)
    finally:
        conn.close()
    return jsonify(data)


@admin_bp.route("/licenses", methods=["POST"])
def api_admin_issue_license():
    """Manual PRO key issuance (community/beta keys).

    Gated to localhost requests or a valid X-API-Key matching the operator's
    API_KEY env var — never exposed to the public checkout path."""
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403
    body = request.get_json(silent=True) or {}
    months = body.get("months")
    if months is not None:
        try:
            months = int(months)
        except (TypeError, ValueError):
            months = None
    plan = (body.get("plan") or "pro").strip().lower()
    if plan not in ("pro", "premium"):
        return jsonify({"error": "plan must be 'pro' or 'premium'"}), 400
    key = _licensing_issue(
        plan=plan,
        email=(body.get("email") or "").strip(),
        source=(body.get("source") or "admin").strip(),
        months=months,
    )
    return jsonify({"ok": True, "license_key": key}), 200


@admin_bp.route("/analytics", methods=["GET"])
def api_admin_analytics():
    """Beta analytics report: DAU/WAU, module usage, time per module, dropoff.

    Admin-gated exactly like /api/admin/conversion.
    """
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403
    days = request.args.get("days", 30, type=int)
    days = max(1, min(days, 365))
    report = _beta_analytics.get_report(days=days)
    return jsonify(report)


@admin_bp.route("/postgres-readiness", methods=["GET"])
def api_admin_postgres_readiness():
    """Redacted, read-only traction gate for the future Postgres rehearsal."""
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403
    try:
        report = _postgres_readiness.readiness_report(
            os.environ.get("DB_PATH", DB_PATH)
        )
    except _postgres_readiness.ReadinessError as exc:
        # The exception contract never contains tokens, DSNs, or database rows.
        return jsonify({"decision": "blocked", "error": str(exc)}), 503
    return jsonify(report)


@admin_bp.route("/conversion", methods=["GET"])
def api_admin_conversion():
    """CFO dashboard: PRO funnel report + LTV/CAC estimates.

    Admin-gated exactly like /api/admin/licenses (localhost or operator API
    key) — never exposed to the public.
    """
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403
    days = request.args.get("days", 30, type=int)
    weeks = request.args.get("weeks", 8, type=int)
    if weeks < 1 or weeks > 52:
        weeks = 8
    weekly = _conversion.funnel_weekly_report(weeks=weeks)
    # Issue #156 (18-B): ?format=csv exports the weekly trend as a
    # spreadsheet (BOM UTF-8, attachment) — same payload, same gate.
    if request.args.get("format", "").lower() == "csv":
        out_csv = "\ufeff" + _conversion.funnel_weekly_csv(weekly)
        fname = f"funnel_weekly_{int(time.time())}.csv"
        resp = Response(out_csv, mimetype="text/csv")
        resp.headers["Content-Disposition"] = f"attachment; filename={fname}"
        return resp
    funnel = _conversion.funnel_report(days=days)
    econ = _conversion.ltv_cac_report(paid_count=funnel.get("paid_count"))
    # Issue #163: alert when one feature concentrates too much of the
    # paywalls (?feature_pct= threshold, default 50%) — the #1 friction
    # point jumps out instead of hiding in the breakdown list.
    feature_pct = request.args.get("feature_pct", 50, type=float)
    if feature_pct < 1 or feature_pct > 100:
        feature_pct = 50
    feature_alert = _conversion.detect_feature_overconcentration(
        funnel.get("paywall_by_feature") or [], min_pct=feature_pct
    )
    return jsonify(
        {
            "funnel": funnel,
            "economics": econ,
            "days": days,
            "weekly": weekly,
            "feature_alert": feature_alert,
        }
    )


@admin_bp.route("/rentals/accepted-recos", methods=["GET"])
def api_admin_rentals_accepted_recos():
    """Global audit trail of accepted recommendations (ALL tenants).

    Admin-gated exactly like /api/admin/conversion (localhost or operator API
    key) — never exposed to the public. Aggregates every tenant's
    accepted-recommendation ledger (default + named) with the delivery
    outcome afterwards, so the platform operator sees the fleet of 'rigs
    blacklisted after the pilot flagged them' decisions at a glance.
    Query params: ?days=30 (window; default 0 = all time, unlike
    /api/admin/conversion's 30-day default) and ?limit=500 (max decisions;
    ``count`` remains the true total). ?format=csv returns the full audit
    trail as a spreadsheet (BOM UTF-8, attachment) — same payload, same
    gate.
    """
    if not _admin_request_allowed():
        return jsonify({"error": "admin access required"}), 403
    days = request.args.get("days", 0, type=int)
    if request.args.get("format", "").lower() == "csv":
        # Spreadsheet export = the FULL audit trail: default to the cap
        # (1000) instead of the JSON pagination default (200) — a truncated
        # file must never be mistaken for the complete audit. A caller can
        # still pass a smaller ?limit to narrow the export.
        limit = request.args.get("limit", 1000, type=int)
        limit = max(1, min(limit, 1000))
        payload = _rental_perf.compute_admin_accepted_recos(days=days, limit=limit)
        out_csv = "\ufeff" + _rental_perf.admin_accepted_recos_csv(payload)
        fname = f"accepted_recos_audit_{int(time.time())}.csv"
        resp = Response(out_csv, mimetype="text/csv")
        resp.headers["Content-Disposition"] = f"attachment; filename={fname}"
        return resp
    limit = request.args.get("limit", 200, type=int)
    limit = max(1, min(limit, 1000))
    payload = _rental_perf.compute_admin_accepted_recos(days=days, limit=limit)
    # Tenant worse-concentration report (padrão global de reincidência): the
    # platform operator sees WHICH tenants have a concentrated 'worse'
    # verdict pattern. Thresholds tunable via query (defaults 2/0.5).
    payload["worse_concentration"] = _rental_perf.detect_tenant_worse_concentration(
        days=days,
        min_worse=request.args.get("worse_min", 2, type=int),
        worse_ratio=request.args.get("worse_ratio", 0.5, type=float),
    )
    # Auto-exclusion history (global, WHEN + CAUSE): every rig the pilot
    # auto-excluded across ALL tenants with the snapshot + rule that fired.
    hist = _rental_perf.admin_auto_exclusion_history(days=days)
    payload["auto_exclusions"] = hist
    # Auto-exclusion CONCENTRATION (padrão global do piloto): grouping by
    # tenant + by régua (floor/mín) + systemic rigs — aggregated from the
    # SAME history pass above (zero drift, ONE audit pass, not two).
    payload["auto_exclusion_aggregates"] = _rental_perf._aggregate_exclusions(
        hist.get("exclusions") or []
    )
    payload["auto_exclusion_aggregates"]["days"] = days if days else None
    return jsonify(payload)
