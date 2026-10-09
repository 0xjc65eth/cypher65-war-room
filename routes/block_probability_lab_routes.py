"""
CYPHER65 // Block Probability Lab routes
=========================================

A dashboard blueprint exposing the consolidated Block Probability Lab:

  MODEL INPUTS      - what the operator sees, with Metric Provenance
                      Contract labels (LIVE | DERIVED | FALLBACK |
                      MANUAL | STALE | UNKNOWN)
  TARGET PROBABILITY SOLVER - P(>=1) targets 10/25/50/75/90% in
                      configurable windows
  HASHPOWER/NETWORK WHAT-IF - how network growth changes P(>=1)
  HISTORICAL BEST SHARE - descriptive target ratio, NOT an odds change
  SOLO MODEL SUMMARY - honest P(>=1), expected time, window odds
  SHARE STATISTICS - P50/P75/P90/P95/P99/MAX of share difficulty +
                      sample count

Every endpoint is pure computation (stateless). The Metric Provenance
Contract labels are exposed on the model-inputs endpoint so the frontend
can render "state" and age honestly and never turn a missing value into a
promise.

Security: the block-model lab is advisory; it never dispatches a command,
purchases hashpower and never claims a block deadline.
"""

import logging
from flask import Blueprint, jsonify, request

from services.block_probability_lab import (
    target_probability_for_p1_in_window,
    target_probability_solver,
    probability_horizons,
    hashpower_network_what_if,
    historical_best_share,
    solo_model_summary,
    share_statistics,
    evidence_state_from_inputs,
    model_inputs,
)

log = logging.getLogger("cypher65.block-probability-lab")

dashboard_bp = Blueprint(
    "block_probability_lab", __name__, url_prefix="/api/block-probability-lab"
)

QUERY_WINDOW = (
    "10m", "30m", "1h", "2h", "4h", "6h", "12h", "24h", "7d", "30d"
)


def _default_snapshot():
    """Best-effort snapshot for the lab when the dashboard is not connected
    to a live wallet. Never fabricates a hashrate: returns UNKNOWN/0."""
    import services.state as _state
    snap = getattr(_state, "latest_snapshot", None) or {}
    # Only try to read a timestamp attribute if it actually exists.
    ts = None
    if hasattr(_state, "_last_snapshot_ts"):
        try:
            ts = int(getattr(_state, "_last_snapshot_ts", 0))
        except (TypeError, ValueError):
            ts = None
    return {
        "user_hashrate": float((snap.get("worker") or {}).get("hashrate", 0) or 0),
        "network_hashrate": float((snap.get("network") or {}).get("hashrate", 0) or 0),
        "network_difficulty": float((snap.get("network") or {}).get("difficulty", 0) or 0),
        "source": "snapshot",
        "observed_at": request.args.get("observed_at") or ts,
        "age_seconds": 0,
    }


@dashboard_bp.route("/model-inputs", methods=["GET"])
@dashboard_bp.route("/model-inputs", methods=["POST"])
def api_model_inputs():
    """Model inputs card for the Block Probability Lab.

    GET: reads the latest snapshot (USER_HASHRATE + NETWORK_HASHRATE) and
    labels the provenance with the Metric Provenance Contract.
    POST: accepts explicit {user_hashrate, network_hashrate,
           network_difficulty, network_hashrate_source, observed_at,
           age_seconds, state}.
    """
    body = request.get_json(silent=True) or {}
    if request.method == "POST":
        user_hr = body.get("user_hashrate")
        net_hr = body.get("network_hashrate")
        net_diff = body.get("network_difficulty")
        src = body.get("network_hashrate_source", "UNKNOWN")
        observed_at = body.get("observed_at")
        age = body.get("age_seconds")
        state = body.get("state", "UNKNOWN")
    else:
        snap = _default_snapshot()
        user_hr = snap["user_hashrate"]
        net_hr = snap["network_hashrate"]
        net_diff = snap["network_difficulty"]
        src = snap.get("source", "UNKNOWN")
        observed_at = snap.get("observed_at")
        age = snap.get("age_seconds", 0)
        state = _state_source_label(user_hr, net_hr, snap.get("network_hashrate_source"))

    # Metric Provenance Contract normalization
    valid = {"LIVE", "DERIVED", "FALLBACK", "MANUAL", "STALE", "UNKNOWN"}
    if src not in valid:
        src = "UNKNOWN"
    if state not in valid:
        state = "UNKNOWN"

    return jsonify(
        model_inputs(
            user_hashrate=user_hr,
            network_hashrate=net_hr,
            network_difficulty=net_diff,
            source=src,
            observed_at=observed_at,
            age_seconds=age,
            state=state,
        )
    )


@dashboard_bp.route("/target-solver", methods=["GET"])
def api_target_solver():
    """Target probability solver for P(>=1) of 10/25/50/75/90% in a window.

    Query: ?target=0.10&window_seconds=3600
    Response: share_of_network_required + required_user_hashrate (needs the
    current network hashrate). NEVER a mean interval or countdown.
    """
    try:
        target = float(request.args.get("target", 0.10))
        window = float(request.args.get("window_seconds", 3600.0))
    except (TypeError, ValueError):
        return jsonify({"error": "target and window_seconds must be numbers"}), 400

    # Allow the UI to pick from 10/25/50/75/90 by name
    by_name = {"10": 0.10, "25": 0.25, "50": 0.50, "75": 0.75, "90": 0.90}
    if request.args.get("target") in by_name:
        target = by_name[request.args.get("target")]

    result = target_probability_solver(
        user_hr=None,
        net_hr=None,
        target_p=target,
        window_seconds=window,
    )
    return jsonify(result)


@dashboard_bp.route("/target-p1-window", methods=["GET"])
def api_target_p1_window():
    """Cached target user hashrate for P(>=1) = 10% per window (solver
    constant). Exposes a single reachable target without recomputing each
    request."""
    window = request.args.get("window_seconds", 600.0)
    try:
        window = float(window)
    except (TypeError, ValueError):
        return jsonify({"error": "window_seconds must be a number"}), 400
    return jsonify(target_probability_for_p1_in_window(window))


@dashboard_bp.route("/horizon", methods=["GET"])
def api_horizon():
    """Probability for one window (the solver's epoch).
    Query: ?window_seconds=86400&user_hashrate=...&network_hashrate=...
    """
    try:
        window = float(request.args.get("window_seconds", 86400.0))
    except (TypeError, ValueError):
        return jsonify({"error": "window_seconds must be a number"}), 400

    user_hr = request.args.get("user_hashrate")
    net_hr = request.args.get("network_hashrate")
    try:
        user_hr = float(user_hr) if user_hr not in (None, "") else None
        net_hr = float(net_hr) if net_hr not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({
            "error": "user_hashrate and network_hashrate must be numbers"
        }), 400

    return jsonify(
        probability_horizons(
            user_hr=user_hr,
            network_hr=net_hr,
            duration_seconds=window,
        )
    )


@dashboard_bp.route("/what-if", methods=["GET"])
def api_what_if():
    """Network hashrate what-if for a fixed window. Query the base network
    hashrate and list scenarios with a multiplier or an absolute value.

    Example: ?base_network_hashrate=6e20&scenarios=1.5,0.5
    or ?base_network_hashrate=6e20&scenarios=8e20,1e20
    """
    base = request.args.get("base_network_hashrate")
    try:
        base = float(base) if base not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"error": "base_network_hashrate must be a number"}), 400
    raw = request.args.get("scenarios", "")
    if raw:
        try:
            vals = [float(x) for x in raw.split(",")]
        except ValueError:
            return jsonify({"error": "scenarios must be comma-separated numbers"}), 400
    else:
        vals = [base * 1.5, base * 0.5] if base else []

    return jsonify(
        hashpower_network_what_if(
            base_user_hr=None,
            base_network_hr=base,
            scenarios=[{"network_hashrate": v} for v in vals],
        )
    )


@dashboard_bp.route("/best-share", methods=["GET"])
def api_best_share():
    """Historical best share as a descriptive target ratio.
    Query: ?best_diff=5e13&network_difficulty=1e14
    The best share is a RECORD and does NOT increase the next-hash odds.
    """
    try:
        bd = request.args.get("best_diff")
        nd = request.args.get("network_difficulty")
        bd = float(bd) if bd not in (None, "") else None
        nd = float(nd) if nd not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({
            "error": "best_diff and network_difficulty must be numbers"
        }), 400
    return jsonify(historical_best_share(best_diff_raw=bd, network_difficulty=nd))


@dashboard_bp.route("/solo", methods=["GET"])
def api_solo():
    """Solo model summary: P(>=1), expected time and window odds.
    Query: ?user_hashrate=1e11&network_hashrate=6e20&window_seconds=86400
    """
    try:
        user_hr = request.args.get("user_hashrate")
        net_hr = request.args.get("network_hashrate")
        window = request.args.get("window_seconds", 86400.0)
        try:
            user_hr = float(user_hr) if user_hr not in (None, "") else None
            net_hr = float(net_hr) if net_hr not in (None, "") else None
            window = float(window)
        except (TypeError, ValueError):
            return jsonify({
                "error": "user_hashrate, network_hashrate and window_seconds must be numbers"
            }), 400
    except Exception as e:
        log.warning("api/solo error: %s", e)
        return jsonify({"error": str(e)}), 400

    return jsonify(
        solo_model_summary(
            user_hr=user_hr,
            network_hr=net_hr,
            duration_seconds=window,
        )
    )


@dashboard_bp.route("/share-statistics", methods=["GET"])
def api_share_statistics():
    """Share statistics for the SESSION EVIDENCE panel: P50/P75/P90/P95/P99/MAX
    of share difficulty, plus sample count and window.

    Query (or JSON body): ?session_share_count=100&share_diffs=4e13,6e13,5e13
    """
    body = request.get_json(silent=True) or {}
    session_share_count = body.get("session_share_count")
    share_calc_history = body.get("share_calc_history")
    window = body.get("window_seconds", 3600.0)
    try:
        session_share_count = int(session_share_count) if session_share_count not in (None, "") else None
        window = float(window)
    except (TypeError, ValueError):
        return jsonify({
            "error": "session_share_count and window_seconds must be numbers"
        }), 400

    if isinstance(share_calc_history, str):
        # Accept a comma-separated numeric string too
        raw = [x.strip() for x in share_calc_history.split(",") if x.strip()]
        try:
            share_calc_history = [{"share_diff_raw": float(x)} for x in raw]
        except ValueError:
            return jsonify({
                "error": "share_calc_history values must be numbers"
            }), 400

    return jsonify(
        share_statistics(
            session_share_count=session_share_count,
            share_calc_history=share_calc_history,
            window_seconds=window,
        )
    )


@dashboard_bp.route("/evidence-state", methods=["GET", "POST"])
@dashboard_bp.route("/session-evidence", methods=["GET", "POST"])
def api_evidence_state():
    """Map live inputs to one of GOOD COVERAGE | PARTIAL | STALE |
    INSUFFICIENT | NO DATA. Pure derivation; no scoring. Also returns
    SESSION EVIDENCE fields."""
    body = request.get_json(silent=True) or {}
    try:
        user_hr = float(body.get("user_hashrate", request.args.get("user_hashrate", 0)))
        net_hr = float(body.get("network_hashrate", request.args.get("network_hashrate", 0)))
        shares = int(body.get("session_share_count", request.args.get("session_share_count", 0)))
        age = float(body.get("age_seconds", request.args.get("age_seconds", 0)))
        share_calc_history = body.get("share_calc_history", body.get("history")) or []
        window = float(body.get("window_seconds", request.args.get("window_seconds", 3600.0)))
    except (TypeError, ValueError):
        return jsonify({
            "error": "user_hashrate, network_hashrate, session_share_count and age_seconds must be numbers"
        }), 400
    stats = share_statistics(shares, share_calc_history, window)
    return jsonify({
        "evidence_state": evidence_state_from_inputs(user_hr, net_hr, shares, age),
        "session_evidence": {
            "session_shares": shares,
            "valid_modeled_shares": stats.get("valid_modeled_shares", len([x for x in share_calc_history or [] if x.get("share_diff_raw")])) if share_calc_history else stats.get("valid_modeled_shares"),
            "observed_window": stats.get("observed_window"),
            "observed_window_seconds": stats.get("observed_window_seconds"),
            "last_share_age": stats.get("last_share_age"),
            "last_share_age_seconds": stats.get("last_share_age_seconds"),
            "data_gaps": stats.get("data_gaps", 0),
            "avg_share_difficulty": stats.get("avg_share_difficulty"),
            "share_difficulty_trend": stats.get("share_diff_trend", stats.get("trend")),
            "sample_count": stats.get("sample_count"),
            "evidence_state": evidence_state_from_inputs(user_hr, net_hr, shares, age),
        },
        **stats,
    })


def _state_source_label(user_hr, net_hr, network_source):
    """Derive a compact state label from the supply."""
    if user_hr <= 0 or net_hr <= 0:
        return "UNKNOWN"
    if network_source == "FALLBACK":
        return "FALLBACK"
    if network_source == "DERIVED":
        return "DERIVED"
    if network_source == "LIVE":
        return "LIVE"
    return "UNKNOWN"
