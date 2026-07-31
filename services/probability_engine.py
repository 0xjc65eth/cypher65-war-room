"""
CYPHER65 — Probability Engine Integration
========================================
Endpoints and UI helpers for the Block Probability Engine.
"""
import logging
from flask import jsonify, request, current_app
from services.probability import (
    calculate_block_probability,
    calculate_multiple_periods,
)

log = logging.getLogger("cypher65.probability")

# Default network hashrate if API is unavailable (~600 EH/s for 2026)
DEFAULT_NETWORK_HASHRATE = 6e20


def _get_snapshot_hashrate() -> dict:
    """Try to read the current user hashrate and network hashrate from
    the shared state (latest_snapshot). Returns defaults if unavailable."""
    import services.state as _state
    snap = getattr(_state, "latest_snapshot", None) or {}
    worker = snap.get("worker") or {}
    net = snap.get("network") or {}

    user_hr = float(worker.get("hashrate", 0) or 0)
    net_hr = float(net.get("hashrate", 0) or 0)
    net_diff = float(net.get("difficulty", 0) or 0)

    if net_hr <= 0:
        net_hr = DEFAULT_NETWORK_HASHRATE

    return {
        "user_hashrate": user_hr,
        "network_hashrate": net_hr,
        "network_difficulty": net_diff if net_diff > 0 else None,
    }


def register_probability_routes(app):
    """Register probability API routes on the Flask app."""

    @app.route("/api/probability")
    def api_probability():
        """
        Calculate block-finding probabilities for a single time window.

        Query params:
            hashrate: user hashrate in H/s (optional, uses snapshot if omitted)
            network_hashrate: network hashrate in H/s (optional)
            duration: duration in seconds (default 86400 = 24h)
        """
        try:
            snap = _get_snapshot_hashrate()
            user_hr = float(request.args.get("hashrate", snap["user_hashrate"]))
            network_hr = float(request.args.get("network_hashrate", snap["network_hashrate"]))
            duration = int(request.args.get("duration", 86400))

            if user_hr <= 0:
                return jsonify({"error": "hashrate parameter is required and must be > 0"}), 400

            result = calculate_block_probability(user_hr, network_hr, duration, snap["network_difficulty"])
            result["input"] = {
                "user_hashrate": user_hr,
                "network_hashrate": network_hr,
                "duration_seconds": duration,
                "source": "snapshot" if snap["user_hashrate"] > 0 else "fallback",
            }

            return jsonify(result)

        except Exception as e:
            log.warning("/api/probability error: %s", e)
            return jsonify({"error": str(e)}), 400

    @app.route("/api/probability/full")
    def api_probability_full():
        """
        Return probabilities for multiple standard periods with scenarios.

        Scenarios:
          - conservative: 80% of user hashrate (worst case)
          - base: 100% of user hashrate
          - aggressive: 120% of user hashrate (best case, e.g. after tuning)

        Each scenario returns probabilities for 1h, 6h, 12h, 24h, 7d, 30d.
        """
        try:
            snap = _get_snapshot_hashrate()
            user_hr = float(request.args.get("hashrate", snap["user_hashrate"]))
            network_hr = float(request.args.get("network_hashrate", snap["network_hashrate"]))

            if user_hr <= 0:
                return jsonify({
                    "error": "hashrate required. Use ?hashrate=X or connect a wallet.",
                    "hint": "Connect a BTC wallet to auto-detect hashrate, or pass ?hashrate=12345678901234",
                }), 400

            # Three scenarios
            scenarios = {
                "conservative": round(user_hr * 0.80, 0),
                "base": round(user_hr, 0),
                "aggressive": round(user_hr * 1.20, 0),
            }

            result = {
                "user_hashrate": user_hr,
                "user_hashrate_str": _fmt_hashrate_short(user_hr),
                "network_hashrate": network_hr,
                "network_hashrate_str": _fmt_hashrate_short(network_hr),
                "network_difficulty": snap["network_difficulty"],
                "source": "snapshot" if snap["user_hashrate"] > 0 else "manual",
                "scenarios": {},
            }

            for scenario_name, hr in scenarios.items():
                periods = calculate_multiple_periods(hr, network_hr, snap["network_difficulty"])
                result["scenarios"][scenario_name] = {
                    "hashrate": hr,
                    "hashrate_str": _fmt_hashrate_short(hr),
                    "periods": periods.get("periods", {}),
                }

            return jsonify(result)

        except Exception as e:
            log.warning("/api/probability/full error: %s", e)
            return jsonify({"error": str(e)}), 400

    return app


def _fmt_hashrate_short(hr: float) -> str:
    """Format hashrate to a short human-readable string."""
    if hr >= 1e15:
        return f"{hr/1e15:.2f} PH/s"
    if hr >= 1e12:
        return f"{hr/1e12:.2f} TH/s"
    if hr >= 1e9:
        return f"{hr/1e9:.2f} GH/s"
    if hr >= 1e6:
        return f"{hr/1e6:.2f} MH/s"
    return f"{hr:.0f} H/s"


# ── Note: _fmt_hashrate_short() is an inline simplified version of
# helpers.fmt_hashrate(), kept here to avoid circular imports.