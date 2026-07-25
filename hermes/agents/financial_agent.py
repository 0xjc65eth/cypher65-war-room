"""
FinancialAgent
==============
Specialized agent for ROI, cost, revenue, and profitability analysis.
Uses real hashrate + BTC price when available. Marks all outputs as ESTIMATED.

Data sources: state.latest_snapshot (primary), payload (fallback).
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


def _get_real_data():
    """Extract real financial data from polling loop snapshot."""
    if _state is None:
        return {}
    snap = getattr(_state, "latest_snapshot", None) or {}
    worker = snap.get("worker") or {}
    network = snap.get("network") or {}
    btc = snap.get("btc_price") or {}
    return {
        "user_hashrate": _safe_float(worker.get("hashrate")),
        "network_hashrate": _safe_float(network.get("hashrate"), 6e20),
        "pool_hashrate": _safe_float(snap.get("pool_hashrate")),
        "btc_usd": _safe_float(btc.get("usd")),
        "btc_brl": _safe_float(btc.get("brl")),
        "_data_source": "REAL" if _safe_float(worker.get("hashrate")) > 0 else "NO_DATA",
    }


class FinancialAgent:
    """Handles financial calculations with real data where possible."""

    def __init__(self):
        self.name = "FinancialAgent"

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # If payload has no real data, fetch from state directly
        if not payload.get("_data_source") or payload.get("_data_source") == "NO_DATA":
            real = _get_real_data()
            if real.get("_data_source") == "REAL":
                payload = {**real, **payload}
        user_hashrate = payload.get("user_hashrate", 0)
        network_hashrate = payload.get("network_hashrate", 6e20)
        btc_usd = payload.get("btc_usd", 0)
        btc_brl = payload.get("btc_brl", 0)
        pool_hashrate = payload.get("pool_hashrate", 0)
        data_source = payload.get("_data_source", "NO_DATA")

        result = {
            "agent": self.name,
            "status": "success",
            "data_source": data_source,
            "analysis": {},
        }

        if data_source != "REAL" or user_hashrate <= 0:
            result["analysis"] = {
                "status": "DATA REQUIRED",
                "message": (
                    "Financial analysis requires real mining data. "
                    "Connect a wallet with active workers to see estimates."
                ),
                "note": "All values below are ESTIMATED from available data.",
            }
            return result

        hashrate_ths = user_hashrate / 1e12

        # ── Pool mode revenue (FPPS-like estimate) ──
        # Reward: pool blocks found * (your_hashrate / pool_hashrate)
        # Approximate daily pool blocks: 144 * (pool_hashrate / network_hashrate)
        # Your share: reward * (your_hashrate / pool_hashrate) * (1 - pool_fee) * (1 - orphan_rate)
        if pool_hashrate > 0 and network_hashrate > 0 and btc_usd > 0:
            daily_pool_blocks = 144.0 * (pool_hashrate / network_hashrate)
            block_reward_btc = 3.125  # post-halving
            avg_tx_fee_btc = 0.05     # conservative
            total_reward = block_reward_btc + avg_tx_fee_btc
            pool_fee_pct = 0.015
            orphan_rate = 0.005

            daily_reward_btc = (
                daily_pool_blocks
                * total_reward
                * (user_hashrate / pool_hashrate)
                * (1 - pool_fee_pct)
                * (1 - orphan_rate)
            )
        else:
            daily_reward_btc = 0

        daily_revenue_usd = daily_reward_btc * btc_usd if btc_usd else 0
        daily_revenue_brl = daily_reward_btc * btc_brl if btc_brl else 0

        result["analysis"] = {
            "status": "ESTIMATED",
            "data_provenance": "REAL hashrate + BTC price, estimated pool share",
            "hashrate_ths": round(hashrate_ths, 2),
            "btc_price_usd": btc_usd,
            "btc_price_brl": btc_brl,
            "estimated_daily_btc": round(daily_reward_btc, 8),
            "estimated_daily_usd": round(daily_revenue_usd, 2),
            "estimated_daily_brl": round(daily_revenue_brl, 2),
            "estimated_monthly_usd": round(daily_revenue_usd * 30, 2),
            "estimated_monthly_brl": round(daily_revenue_brl * 30, 2),
            "note": (
                "ESTIMATED VALUES based on current hashrate and BTC price. "
                "Actual earnings vary with pool luck, difficulty changes, "
                "and market conditions. Pool fee assumed at 1.5%, orphan rate 0.5%."
            ),
        }

        if daily_reward_btc == 0:
            result["analysis"]["status"] = "INSUFFICIENT DATA"
            result["analysis"]["message"] = (
                "Not enough data for revenue estimate. "
                "Pool hashrate or network hashrate unavailable."
            )

        return result
