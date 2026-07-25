"""
ProbabilityAgent
================
Specialized agent for block probability calculations.
Uses real network difficulty + user hashrate from state.latest_snapshot.
"""

from typing import Dict, Any

try:
    import services.state as _state
except ImportError:
    _state = None


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class ProbabilityAgent:
    """Handles block probability queries with real data."""

    def __init__(self, probability_engine):
        self.probability_engine = probability_engine

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        user_hashrate = payload.get("user_hashrate", 0)
        network_hashrate = payload.get("network_hashrate", 6e20)
        duration = payload.get("duration", 86400)
        network_difficulty = payload.get("network_difficulty", 0)

        # If payload has no real hashrate, fetch from state directly
        if user_hashrate <= 0 and _state is not None:
            snap = getattr(_state, "latest_snapshot", None) or {}
            worker = snap.get("worker") or {}
            network = snap.get("network") or {}
            user_hashrate = _safe_float(worker.get("hashrate"))
            if not network_hashrate or network_hashrate == 6e20:
                network_hashrate = _safe_float(network.get("hashrate"), 6e20)
            if not network_difficulty:
                network_difficulty = _safe_float(network.get("difficulty"))

        if not self.probability_engine:
            return {
                "agent": "ProbabilityAgent",
                "status": "error",
                "message": "Probability engine not available"
            }

        if user_hashrate <= 0:
            return {
                "agent": "ProbabilityAgent",
                "status": "error",
                "message": "No hashrate data available. Connect a wallet to see probabilities."
            }

        prob = self.probability_engine.calculate_block_probability(
            user_hashrate, network_hashrate, duration, network_difficulty
        )

        pct = prob.get("probability_at_least_one", 0) * 100 if prob else 0
        expected_days = prob.get("expected_time_days", 0) if prob else 0

        return {
            "agent": "ProbabilityAgent",
            "status": "success",
            "probability": prob,
            "summary": (
                f"With {user_hashrate/1e12:.2f} TH/s over {duration/3600:.1f}h: "
                f"P(>=1 block) = {pct:.6f}% | "
                f"Expected time: {expected_days:,.0f} days"
            ),
        }