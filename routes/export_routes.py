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
import json
import time
import csv as _csv
from io import StringIO as _StringIO

from flask import Blueprint, jsonify, request, Response

import config
import services.state as _state
from services.db import get_db
from services.settings import load_settings, DEFAULT_SETTINGS, save_setting
from services.tenant import require_tenant, role_required

export_bp = Blueprint("export", __name__, url_prefix="/api")


@export_bp.route("/export/<table>.<fmt>")
@require_tenant
@role_required("viewer")
def api_export(table, fmt, tenant_id: str = ""):
    """Export a table as csv or json. Tables: snapshots, alerts, share_timeline,
    highest_diff_events."""
    allowed = {"snapshots", "alerts", "share_timeline", "highest_diff_events"}
    if table not in allowed:
        return jsonify({"error": f"unknown table {table}"}), 400
    rng = request.args.get("range", "24h")
    span = {
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
        "all": 10 ** 10,
    }.get(rng, 86400)
    since = int(time.time()) - span
    conn = get_db()
    c = conn.cursor()
    c.execute(f"SELECT * FROM {table} WHERE ts >= ? ORDER BY ts DESC LIMIT 5000", (since,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    if fmt == "csv":
        buf = _StringIO()
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
            json.dumps({"table": table, "range": rng, "rows": rows}, default=str),
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
    s = load_settings(tenant_id=tenant_id)
    payload = {
        "settings": s,
        "worker_name": config.WORKER_NAME,
        "btc_address": config.BTC_ADDRESS,
        "exported_ts": int(time.time()),
        "version": 1,
    }
    return Response(
        json.dumps(payload, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=cypher65_config_backup.json"},
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
    for k, v in settings.items():
        if k not in DEFAULT_SETTINGS:
            rejected.append(k)
            continue
        if save_setting(k, v, tenant_id=tenant_id):
            applied.append(k)
    return jsonify({"applied": applied, "rejected": rejected})
