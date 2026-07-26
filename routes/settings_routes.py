"""
CYPHER65 // Settings API routes
================================
Flask Blueprint for /api/settings endpoints.
Extracted from app.py — Phase 2a of P0.4 refactoring.
"""
import time

from flask import Blueprint, jsonify, request

from services.settings import DEFAULT_SETTINGS, load_settings, save_setting, settings_label

settings_bp = Blueprint("settings", __name__, url_prefix="/api")


@settings_bp.route("/settings", methods=["GET"])
def api_settings_get():
    s = load_settings()
    out = []
    for k, v in DEFAULT_SETTINGS.items():
        out.append({"key": k, "value": s.get(k, v), "default": v, "label": settings_label(k)})
    return jsonify({"settings": out, "freshness_ts": int(time.time())})


@settings_bp.route("/settings", methods=["POST"])
def api_settings_post():
    """POST JSON body: {key: value, key: value, ...}"""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "expected JSON object body"}), 400
    applied = []
    rejected = []
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS:
            rejected.append({"key": k, "reason": "unknown key"})
            continue
        if save_setting(k, v):
            applied.append(k)
        else:
            rejected.append({"key": k, "reason": "db error"})
    return jsonify({"applied": applied, "rejected": rejected})
