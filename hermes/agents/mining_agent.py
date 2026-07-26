"""
MiningAgent
===========
Specialized agent for mining status, hashrate, and worker analysis.
Uses REAL data from the polling loop (state.latest_snapshot).

Data sources: state.latest_snapshot (primary), payload (fallback).
"""

from typing import Dict, Any
import time

try:
    import services.state as _state
except ImportError:
    _state = None


def _safe_int(val, default=0):
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _get_real_data():
    """Extract real mining data from the polling loop snapshot."""
    if _state is None:
        return {}
    snap = getattr(_state, "latest_snapshot", None) or {}
    worker = snap.get("worker") or {}
    network = snap.get("network") or {}
    btc = snap.get("btc_price") or {}
    return {
        "user_hashrate": _safe_float(worker.get("hashrate")),
        "worker_status": worker.get("status", "unknown"),
        "worker_best_diff": worker.get("bestDifficulty", "—"),
        "worker_last_submit": worker.get("lastSubmission", 0),
        "worker_uptime": worker.get("uptime", 0),
        "all_workers": snap.get("all_workers") or [],
        "network_hashrate": _safe_float(network.get("hashrate"), 6e20),
        "network_difficulty": _safe_float(network.get("difficulty")),
        "pool_hashrate": _safe_float(snap.get("pool_hashrate")),
        "pool_workers": snap.get("pool_workers", 0),
        "btc_usd": _safe_float(btc.get("usd")),
        "session_share_count": getattr(_state, "session_share_count", 0),
        "_data_source": "REAL" if (
            _safe_float(worker.get("hashrate")) > 0
            or len(snap.get("all_workers") or []) > 0
            or getattr(_state, "session_share_count", 0) > 0
            or (worker.get("bestDifficulty") and worker.get("bestDifficulty") != "—")
        ) else "NO_DATA",
    }


class MiningAgent:
    """Analyzes mining operation status with real data."""

    def __init__(self, probability_engine=None):
        self.probability_engine = probability_engine

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Main entry point for MiningAgent.

        Uses real data from state.latest_snapshot if payload is empty.
        """
        # If payload has no real data, fetch from state directly
        if not payload.get("_data_source") or payload.get("_data_source") == "NO_DATA":
            real = _get_real_data()
            if real.get("_data_source") == "REAL":
                payload = {**real, **payload}

        intent = payload.get("intent", "")
        user_hashrate = payload.get("user_hashrate", 0)
        network_hashrate = payload.get("network_hashrate", 6e20)
        worker_status = payload.get("worker_status", "unknown")
        worker_name = payload.get("worker_name", "")
        worker_best_diff = payload.get("worker_best_diff", "—")
        worker_last_submit = _safe_int(payload.get("worker_last_submit", 0))
        worker_uptime = _safe_int(payload.get("worker_uptime", 0))
        all_workers = payload.get("all_workers", [])
        pool_hashrate = payload.get("pool_hashrate", 0)
        pool_workers_count = payload.get("pool_workers", 0)
        network_difficulty = payload.get("network_difficulty", 0)
        session_share_count = payload.get("session_share_count", 0)
        data_source = payload.get("_data_source", "NO_DATA")

        result = {
            "agent": "MiningAgent",
            "status": "success",
            "data_source": data_source,
            "analysis": {},
        }

        # Build real worker analysis
        hashrate_ths = user_hashrate / 1e12 if user_hashrate else 0

        status_labels = {
            "hashing": "ONLINE · HASHING",
            "online": "ONLINE",
            "idle": "IDLE",
            "offline": "OFFLINE",
            "unknown": "UNKNOWN",
        }
        status_display = status_labels.get(worker_status.lower(), worker_status.upper())

        # Worker analysis
        worker_analysis = {
            "hashrate_hs": user_hashrate,
            "hashrate_ths": round(hashrate_ths, 2),
            "status": worker_status,
            "status_display": status_display,
            "best_difficulty": worker_best_diff,
            "worker_count": len(all_workers),
            "session_share_count": session_share_count,
        }

        # Last share age
        if worker_last_submit:
            age_s = int(time.time()) - worker_last_submit
            if age_s < 60:
                worker_analysis["last_share_age"] = f"{age_s}s ago"
            elif age_s < 3600:
                worker_analysis["last_share_age"] = f"{age_s // 60}min ago"
            else:
                worker_analysis["last_share_age"] = f"{age_s // 3600}h ago"
        else:
            worker_analysis["last_share_age"] = "no shares yet"

        # Uptime
        if worker_uptime:
            days = worker_uptime // 86400
            hours = (worker_uptime % 86400) // 3600
            worker_analysis["uptime_display"] = f"{days}d {hours}h"

        # Pool context
        worker_analysis["pool_hashrate_ths"] = round(pool_hashrate / 1e12, 2) if pool_hashrate else 0
        worker_analysis["pool_workers"] = pool_workers_count

        # Probability if we have real hashrate and difficulty
        duration = payload.get("duration", 86400)
        if user_hashrate > 0 and network_difficulty > 0 and self.probability_engine:
            try:
                prob = self.probability_engine.calculate_block_probability(
                    user_hashrate, network_hashrate, duration, network_difficulty
                )
                worker_analysis["probability"] = prob
            except Exception:
                worker_analysis["probability"] = None

        # ── Per-field data source categorization ──
        worker_analysis["data_sources"] = {
            "hashrate_hs": "REAL" if user_hashrate > 0 else "NO_DATA",
            "hashrate_ths": "CALCULATED" if user_hashrate > 0 else "NO_DATA",
            "status": "REAL",
            "status_display": "CALCULATED",
            "best_difficulty": "REAL" if worker_best_diff and worker_best_diff != "—" else "NO_DATA",
            "worker_count": "REAL",
            "session_share_count": "REAL",
            "last_share_age": "CALCULATED" if worker_last_submit else "NO_DATA",
            "uptime_display": "CALCULATED" if worker_uptime else "NO_DATA",
            "pool_hashrate_ths": "CALCULATED" if pool_hashrate else "NO_DATA",
            "pool_workers": "REAL" if pool_workers_count else "NO_DATA",
            "probability": "CALCULATED" if worker_analysis.get("probability") else "NOT AVAILABLE",
        }

        result["analysis"] = worker_analysis

        # Natural language summary — report what we have, not just when hashrate > 0
        summary_parts = []
        if worker_name and worker_name not in ("unknown", ""):
            summary_parts.append(f"Worker: {worker_name}")
        if hashrate_ths > 0:
            summary_parts.append(f"Current hashrate: {hashrate_ths:.2f} TH/s")
        if status_display and status_display != "UNKNOWN":
            summary_parts.append(f"Status: {status_display}")
        if worker_best_diff and str(worker_best_diff) not in ("", "—", "0"):
            summary_parts.append(f"Best difficulty: {worker_best_diff}")
        if worker_analysis.get("last_share_age") not in (None, "no shares yet", ""):
            summary_parts.append(f"Last share: {worker_analysis['last_share_age']}")
        if len(all_workers) > 0:
            summary_parts.append(f"Active workers: {len(all_workers)}")
        if worker_analysis.get("probability"):
            p = worker_analysis["probability"]
            summary_parts.append(
                f"P(>=1 block in 24h): {p['probability_at_least_one']:.6f} "
                f"(≈{p['probability_at_least_one']*100:.4f}%)"
            )
        if summary_parts:
            result["summary"] = " | ".join(summary_parts)
        else:
            result["summary"] = (
                "No real mining data available. "
                "Connect a wallet address to view your operation."
            )

        return result
