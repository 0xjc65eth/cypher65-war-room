"""
CYPHER65 // Export & Config routes
===================================
Flask Blueprint for CSV/JSON exports and config backup/restore.
Extracted from app.py — Phase 2a of P0.4 refactoring.
"""
import json
import time
import csv as _csv
from io import StringIO as _StringIO

from flask import Blueprint, jsonify, request, current_app

import config
from services.db import get_db
from services.settings import load_settings

export_bp = Blueprint("export", __name__, url_prefix="/api")


@export_bp.route("/export/<table>.<fmt>")
def api_export(table, fmt):
    """Export a table as csv or json."""
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
        return current_app.response_class(
            out,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={table}_{rng}.csv"},
        )
    elif fmt == "json":
        return current_app.response_class(
            json.dumps({"table": table, "range": rng, "rows": rows}, default=str),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={table}_{rng}.json"},
        )
    else:
        return jsonify({"error": f"unknown format {fmt}"}), 400


@export_bp.route("/config/backup")
def api_config_backup():
    """Download entire config as JSON."""
    s = load_settings()
    payload = {
        "settings": s,
        "worker_name": config.WORKER_NAME,
        "btc_address": config.BTC_ADDRESS,
        "exported_ts": int(time.time()),
        "version": 1,
    }
    return current_app.response_class(
        json.dumps(payload, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=cypher65_config_backup.json"},
    )


@export_bp.route("/config/restore", methods=["POST"])
def api_config_restore():
    """Restore settings from a backup JSON body."""
    from services.settings import DEFAULT_SETTINGS, save_setting

    body = request.get_json(silent=True) or {}
    settings = body.get("settings") or {}
    if not isinstance(settings, dict):
        return jsonify({"error": "expected object with 'settings' key"}), 400
    applied, rejected = [], []
    for k, v in settings.items():
        if k not in DEFAULT_SETTINGS:
            rejected.append(k)
            continue
        if save_setting(k, v):
            applied.append(k)
    return jsonify({"applied": applied, "rejected": rejected})
