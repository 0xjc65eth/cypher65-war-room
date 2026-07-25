"""
PerformanceAgent
================
Specialized agent for mining performance analysis using real data.
Analyzes hashrate, uptime, share cadence, and detects anomalies.

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
    """Extract real performance data from polling loop snapshot."""
    if _state is None:
        return {}
    snap = getattr(_state, "latest_snapshot", None) or {}
    worker = snap.get("worker") or {}
    return {
        "user_hashrate": _safe_float(worker.get("hashrate")),
        "worker_status": worker.get("status", "unknown"),
        "worker_last_submit": worker.get("lastSubmission", 0),
        "worker_uptime": worker.get("uptime", 0),
        "all_workers": snap.get("all_workers") or [],
        "session_share_count": getattr(_state, "session_share_count", 0),
        "_data_source": "REAL" if _safe_float(worker.get("hashrate")) > 0 else "NO_DATA",
    }


class PerformanceAgent:
    """Handles performance monitoring with real mining data."""

    def __init__(self):
        self.name = "PerformanceAgent"

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # If payload has no real data, fetch from state directly
        if not payload.get("_data_source") or payload.get("_data_source") == "NO_DATA":
            real = _get_real_data()
            if real.get("_data_source") == "REAL":
                payload = {**real, **payload}
        user_hashrate = payload.get("user_hashrate", 0)
        worker_status = payload.get("worker_status", "unknown")
        worker_last_submit = _safe_int(payload.get("worker_last_submit", 0))
        worker_uptime = _safe_int(payload.get("worker_uptime", 0))
        all_workers = payload.get("all_workers", [])
        session_share_count = payload.get("session_share_count", 0)
        data_source = payload.get("_data_source", "NO_DATA")

        result = {
            "agent": self.name,
            "status": "success",
            "data_source": data_source,
            "analysis": {},
        }

        if data_source != "REAL":
            result["analysis"] = {
                "status": "NO DATA",
                "message": "Performance metrics require active mining data.",
                "metrics_available": ["hashrate", "uptime", "shares", "last_submission"],
                "metrics_unavailable": ["temperature", "power", "fan_speed", "hardware_errors"],
            }
            return result

        # ── Build real performance analysis ──
        metrics = {
            "hashrate_ths": round(user_hashrate / 1e12, 2) if user_hashrate else 0,
            "worker_status": worker_status,
            "worker_count": len(all_workers),
            "session_shares": session_share_count,
            "uptime_seconds": worker_uptime,
        }

        # Last share staleness
        if worker_last_submit:
            staleness_s = int(time.time()) - worker_last_submit
            metrics["last_share_staleness_s"] = staleness_s
            if staleness_s > 300:
                metrics["stale_warning"] = True
                metrics["stale_message"] = f"No share for {staleness_s // 60} minutes — worker may be stalled."
            else:
                metrics["stale_warning"] = False
        else:
            metrics["last_share_staleness_s"] = None
            metrics["stale_warning"] = True
            metrics["stale_message"] = "No shares detected yet."

        # Uptime
        if worker_uptime:
            days = worker_uptime // 86400
            hours = (worker_uptime % 86400) // 3600
            metrics["uptime_display"] = f"{days}d {hours}h"
        else:
            metrics["uptime_display"] = "—"

        # Worker-level performance (best/worst by hashrate)
        if all_workers:
            workers_with_hr = [w for w in all_workers if isinstance(w, dict) and w.get("hashrate")]
            if workers_with_hr:
                best = max(workers_with_hr, key=lambda w: float(w.get("hashrate", 0)))
                worst = min(workers_with_hr, key=lambda w: float(w.get("hashrate", 0)))
                metrics["best_worker"] = best.get("name", "unknown")
                metrics["best_worker_hr_ths"] = round(float(best.get("hashrate", 0)) / 1e12, 2)
                metrics["worst_worker"] = worst.get("name", "unknown")
                metrics["worst_worker_hr_ths"] = round(float(worst.get("hashrate", 0)) / 1e12, 2)

        # Detection flags
        detection = []
        if metrics.get("stale_warning"):
            detection.append("STALE_WORKER")
        if worker_status.lower() == "offline":
            detection.append("OFFLINE")
        if worker_status.lower() == "idle":
            detection.append("IDLE")

        metrics["detection_flags"] = detection if detection else ["HEALTHY"]

        # Unavailable metrics (explicitly marked)
        metrics["unavailable_metrics"] = {
            "temperature": "NOT AVAILABLE — requires ASIC/miner API access",
            "power_watts": "NOT AVAILABLE — requires ASIC/miner API access",
            "fan_speed": "NOT AVAILABLE — requires ASIC/miner API access",
            "hardware_errors": "NOT AVAILABLE — requires ASIC/miner API access",
        }

        # ── Per-field data source categorization ──
        metrics["data_sources"] = {
            "hashrate_ths": "CALCULATED",
            "worker_status": "REAL",
            "worker_count": "REAL",
            "session_shares": "REAL",
            "uptime_seconds": "REAL",
            "uptime_display": "CALCULATED" if worker_uptime else "NO_DATA",
            "last_share_staleness_s": "CALCULATED" if worker_last_submit else "NO_DATA",
            "stale_warning": "CALCULATED",
            "stale_message": "CALCULATED" if worker_last_submit else "NO_DATA",
            "best_worker": "CALCULATED" if (all_workers and any(isinstance(w, dict) and w.get("hashrate") for w in all_workers)) else "NO_DATA",
            "best_worker_hr_ths": "CALCULATED" if (all_workers and any(isinstance(w, dict) and w.get("hashrate") for w in all_workers)) else "NO_DATA",
            "worst_worker": "CALCULATED" if (all_workers and any(isinstance(w, dict) and w.get("hashrate") for w in all_workers)) else "NO_DATA",
            "worst_worker_hr_ths": "CALCULATED" if (all_workers and any(isinstance(w, dict) and w.get("hashrate") for w in all_workers)) else "NO_DATA",
            "detection_flags": "CALCULATED",
            "temperature": "NOT AVAILABLE",
            "power_watts": "NOT AVAILABLE",
            "fan_speed": "NOT AVAILABLE",
            "hardware_errors": "NOT AVAILABLE",
        }

        result["analysis"] = metrics
        return result
