"""
CYPHER65 // Export & Config routes
===================================
Flask Blueprint for CSV/JSON exports and config backup/restore.
Fase 6: migrated from app.py — registered in app.py.

The export routes are auth-gated (require_tenant + role_required) but the
underlying data is not tenant-filtered yet (Fase 4 · B2 pending for the
snapshots/alerts/share_timeline tables). The gates prevent anonymous access
while the data-layer isolation is completed.
"""

import os
import json
import time
import csv as _csv
from io import StringIO as _StringIO

from flask import Blueprint, jsonify, request, Response

import config
import services.state as _state
from helpers import csv_neutralize as _csv_neutralize
from services.db import get_db
from services.settings import (
    load_settings,
    DEFAULT_SETTINGS,
    credential_keys,
    redact_settings,
    save_setting,
    is_default_tenant,
)
from services.tenant import require_tenant, role_required

export_bp = Blueprint("export", __name__, url_prefix="/api")

# Issue #201: per-export row cap (env-gated like RENTAL_SWEEP_INTERVAL).
# Truncation is ALWAYS surfaced (CSV metadata row / JSON total+truncated) —
# an export is never silently incomplete.
EXPORT_ROW_LIMIT = int(os.environ.get("EXPORT_ROW_LIMIT", "5000") or "5000")


@export_bp.route("/export/<table>.<fmt>")
@require_tenant
@role_required("viewer")
def api_export(table, fmt, tenant_id: str = ""):
    """Export a table as csv or json. Tables: snapshots, alerts, share_timeline,
    highest_diff_events.

    Tenant isolation (Fase 4 · B2):
      - ``alerts`` carries ``tenant_id`` → rows are filtered to the caller's
        tenant (a named tenant NEVER sees another tenant's alerts).
      - ``snapshots`` / ``share_timeline`` / ``highest_diff_events`` are
        OPERATOR-only tables (per-tenant polling keeps state in-memory via
        SessionManager, never in these SQLite tables). A named tenant asking
        for them is rejected fail-closed (403) — the operator's telemetry is
        never exportable by another account.

    Export completeness (Issue #201): the response carries the FULL row count
    for the range (``total``) and a ``truncated`` flag when EXPORT_ROW_LIMIT
    dropped rows. JSON always includes both fields; CSV adds a ``#``-prefixed
    metadata row (same convention as the tax export) ONLY when truncated, so
    non-truncated CSVs stay byte-identical to the legacy format.
    """
    allowed = {"snapshots", "alerts", "share_timeline", "highest_diff_events"}
    if table not in allowed:
        return jsonify({"error": f"unknown table {table}"}), 400
    tid = tenant_id or "default"
    # Operator-only tables: only the deployment owner's default tenant may
    # export them. Named tenants get a fail-closed 403 instead of a dump.
    if table != "alerts" and tid != "default":
        return (
            jsonify(
                {
                    "error": "forbidden",
                    "detail": "this table is operator-scoped and not available to your tenant",
                }
            ),
            403,
        )
    rng = request.args.get("range", "24h")
    span = {
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
        "all": 10**10,
    }.get(rng, 86400)
    since = int(time.time()) - span
    conn = get_db()
    c = conn.cursor()
    # Issue #201: count the FULL result set in range FIRST so truncation by
    # EXPORT_ROW_LIMIT is never silent — total/truncated ride every payload.
    if table == "alerts":
        c.execute(
            "SELECT COUNT(*) FROM alerts WHERE ts >= ? AND tenant_id = ?",
            (since, tid),
        )
    else:
        c.execute(f"SELECT COUNT(*) FROM {table} WHERE ts >= ?", (since,))  # nosec B608
    total = int(c.fetchone()[0] or 0)
    # bandit B608 false positive: table validated against the allowed set at
    # the top of this handler — never a raw request value in the SQL text.
    if table == "alerts":
        c.execute(
            f"SELECT * FROM {table} WHERE ts >= ? AND tenant_id = ? "  # nosec B608
            "ORDER BY ts DESC LIMIT ?",
            (since, tid, EXPORT_ROW_LIMIT),
        )
    else:
        c.execute(
            f"SELECT * FROM {table} WHERE ts >= ? ORDER BY ts DESC LIMIT ?",  # nosec B608
            (since, EXPORT_ROW_LIMIT),
        )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    truncated = total > len(rows)
    if fmt == "csv":
        buf = _StringIO()
        if truncated:
            # Metadata row FIRST (#-prefixed, same convention as the tax
            # export) so a truncated export is never presented as complete.
            _csv.writer(buf).writerow(
                [
                    "# CYPHER65 export",
                    f"table={table}",
                    # rng is user-controlled (validated by lookup with default,
                    # but never echoed raw) — csv_neutralize keeps the shared
                    # anti-formula-injection discipline (Issue #196).
                    f"range={_csv_neutralize(rng)}",
                    f"total={total}",
                    "truncated=true",
                ]
            )
        if rows:
            writer = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        out = buf.getvalue()
        return Response(
            out,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={table}_{rng}.csv"},
        )
    elif fmt == "json":
        return Response(
            json.dumps(
                {
                    "table": table,
                    "range": rng,
                    "rows": rows,
                    "total": total,
                    "truncated": truncated,
                },
                default=str,
            ),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={table}_{rng}.json"},
        )
    else:
        return jsonify({"error": f"unknown format {fmt}"}), 400


@export_bp.route("/config/backup")
@require_tenant
@role_required("viewer")
def api_config_backup(tenant_id: str = ""):
    """Download entire config (settings + worker + btc_address) as JSON.

    Tenant-scoped: a named tenant downloads THEIR OWN settings — never the
    operator's global table (which may hold the operator's provider keys).
    """
    s = redact_settings(load_settings(tenant_id=tenant_id))
    payload = {
        "settings": s,
        # These legacy values are operator-global, not tenant-scoped. Never
        # leak them into a named tenant's otherwise isolated export.
        "worker_name": config.WORKER_NAME if is_default_tenant(tenant_id) else "",
        "btc_address": config.BTC_ADDRESS if is_default_tenant(tenant_id) else "",
        "exported_ts": int(time.time()),
        "version": 2,
        "credentials_included": False,
    }
    return Response(
        json.dumps(payload, indent=2, default=str),
        mimetype="application/json",
        headers={
            "Content-Disposition": "attachment; filename=cypher65_config_backup.json"
        },
    )


@export_bp.route("/config/restore", methods=["POST"])
@require_tenant
@role_required("member")
def api_config_restore(tenant_id: str = ""):
    """Restore settings from a backup JSON body.

    Tenant-scoped: writes into the CALLER's own tenant_settings rows — a
    named tenant can NEVER overwrite the operator's global table.
    Only updates keys that exist in DEFAULT_SETTINGS.
    """
    body = request.get_json(silent=True) or {}
    settings = body.get("settings") or {}
    if not isinstance(settings, dict):
        return jsonify({"error": "expected object with 'settings' key"}), 400
    applied, rejected = [], []
    secret_keys = credential_keys()
    for k, v in settings.items():
        if k not in DEFAULT_SETTINGS:
            rejected.append(k)
            continue
        if k in secret_keys and (v is None or str(v).strip() == ""):
            continue
        if save_setting(k, v, tenant_id=tenant_id):
            applied.append(k)
    return jsonify({"applied": applied, "rejected": rejected})
