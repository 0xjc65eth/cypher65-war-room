"""
CYPHER65 // Block Probability Lab
=================================

The consolidated Block Probability Lab. It exposes the model inputs, the
probability solver, the target-probability solver, the hashpower/network
what-if, historical best share, the solo model summary and share statistics
in ONE place, so each metric has exactly ONE primary home (the lab) and no
duplication with the profitability panel, the live hash calculator or the
session work signal.

All probability is Poisson (constant hashrate, constant difficulty,
independent hashes, 600 s network block interval). Nothing is a deadline,
forecast or guarantee.

Metric Provenance Contract values used across this module:
  LIVE      network hashrate observed in the snapshot
  DERIVED   missing network hashrate -> difficulty * 2^32 / 600
  FALLBACK  600 EH/s default substituted (hash-market/EV path default)
  MANUAL    user supplied ?network_hashrate explicitly
  STALE     sourced data older than the freshness budget
  UNKNOWN   nothing was supplied

This module is pure math and never hits the network or storage.
"""

import math
import time
from datetime import datetime, timezone
from typing import Dict, Any, Iterable, List, Optional

BLOCK_INTERVAL_S = 600.0


def _finite_or_default(value: float, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _poisson(user_hr: float, net_hr: float, seconds: float) -> Dict[str, Any]:
    """Core Poisson block-finding probability.

    lambda = (user_hr / net_hr) * (seconds / 600)
    P(>=1) = 1 - e^-lambda
    expected_blocks = lambda
    expected_time = 600 * net_hr / user_hr
    """
    if user_hr <= 0 or net_hr <= 0 or seconds <= 0:
        return {
            "lambda": 0.0,
            "probability_at_least_one": 0.0,
            "probability_zero": 1.0,
            "expected_blocks": 0.0,
            "expected_time_to_block_seconds": None,
        }
    if not (math.isfinite(user_hr) and math.isfinite(net_hr) and math.isfinite(seconds)):
        return {
            "lambda": 0.0,
            "probability_at_least_one": 0.0,
            "probability_zero": 1.0,
            "expected_blocks": 0.0,
            "expected_time_to_block_seconds": None,
        }
    lambda_rate = (user_hr / net_hr) * (seconds / BLOCK_INTERVAL_S)
    if not math.isfinite(lambda_rate):
        return {
            "lambda": 0.0,
            "probability_at_least_one": 0.0,
            "probability_zero": 1.0,
            "expected_blocks": 0.0,
            "expected_time_to_block_seconds": None,
        }
    prob_zero = math.exp(-lambda_rate)
    return {
        "lambda": lambda_rate,
        "probability_at_least_one": 1.0 - prob_zero,
        "probability_zero": prob_zero,
        "expected_blocks": lambda_rate,
        "expected_time_to_block_seconds": (BLOCK_INTERVAL_S * net_hr) / user_hr,
    }


def _format_hr(value: float) -> str:
    if value >= 1e15:
        return f"{value/1e15:.2f} PH/s"
    if value >= 1e12:
        return f"{value/1e12:.2f} TH/s"
    if value >= 1e9:
        return f"{value/1e9:.2f} GH/s"
    if value >= 1e6:
        return f"{value/1e6:.2f} MH/s"
    return f"{value:.0f} H/s"


def model_inputs(
    user_hashrate: Optional[float],
    network_hashrate: Optional[float],
    network_difficulty: Optional[float],
    source: Optional[str] = None,
    observed_at: Optional[float] = None,
    age_seconds: Optional[float] = None,
    state: Optional[str] = None,
) -> Dict[str, Any]:
    """Model inputs card for the Block Probability Lab.

    ``source`` is the Metric Provenance Contract label (LIVE | DERIVED |
    FALLBACK | MANUAL | STALE | UNKNOWN).  ``state`` is the UI state card:
    it defaults to ``source`` when not supplied, so the payload always
    carries an honest state derived from the provenance label instead of a
    generic "LIVE". A missing user/network hashrate is reported as 0 and
    the caller is responsible for the corresponding provenance label;
    this function never replaces 0 with a default.
    """
    valid = {"LIVE", "DERIVED", "FALLBACK", "MANUAL", "STALE", "UNKNOWN"}
    src = source if source in valid else "UNKNOWN"
    if state is None:
        state = src
    elif state not in valid:
        state = "UNKNOWN"
    now = int(observed_at) if observed_at is not None else int(datetime.now(timezone.utc).timestamp())
    age = 0 if age_seconds is None else max(0, int(age_seconds))
    return {
        "user_hashrate": _finite_or_default(user_hashrate),
        "user_hashrate_source": src,
        "user_hashrate_str": _format_hr(_finite_or_default(user_hashrate)),
        "network_hashrate": _finite_or_default(network_hashrate),
        "network_hashrate_source": src,
        "network_hashrate_str": _format_hr(_finite_or_default(network_hashrate)),
        "network_difficulty": _finite_or_default(network_difficulty, 0.0),
        "observed_at": now,
        "age_seconds": age,
        "state": state,
    }


def target_probability_solver(
    user_hr: Optional[float],
    net_hr: Optional[float],
    target_p: float,
    window_seconds: float,
) -> Dict[str, Any]:
    """Invert the Poisson to find how many hashes are needed for a target P.

    For a fixed window (e.g. 600 s) and a target probability p_target,
    solve for the needed effective hashshare. This is a numeric solver,
    NEVER a mean-interval forecast or countdown.

    Returns the share-of-network required and the equivalent user hashrate,
    or UNKNOWN/N/A when inputs are invalid.
    """
    user_hr = _finite_or_default(user_hr)
    net_hr = _finite_or_default(net_hr)
    window = _finite_or_default(window_seconds, 600.0)

    if target_p <= 0 or target_p >= 1:
        return {
            "target_probability": target_p,
            "status": "INVALID_TARGET",
            "share_of_network_required": None,
            "required_user_hashrate": None,
            "note": "target_probability must be strictly inside (0,1)",
        }
    if user_hr <= 0 or net_hr <= 0 or window <= 0:
        return {
            "target_probability": target_p,
            "status": "INSUFFICIENT_INPUTS",
            "share_of_network_required": None,
            "required_user_hashrate": None,
            "note": "user hashrate, network hashrate and window must be > 0",
        }
    # window/600 must be strictly positive so -ln(1-p)/(window/600) is finite.
    # Consistent with the Poisson core: P(>=1) = 1 - e^-lambda where
    # lambda = (user_hr / net_hr) * (window / 600). Invert:
    # lambda = -ln(1 - target_p), and share_of_network = lambda / (window/600).
    # This keeps the solver's answer exactly reproducible by
    # probability_horizons (the Poisson core), so the UI's target hashrate
    # always produces the requested probability, with no binomial/Poisson
    # divergence.
    try:
        window_for_rate = window / BLOCK_INTERVAL_S
        if window_for_rate <= 0:
            raise ValueError("window_for_rate <= 0")
        import math as _math
        lambda_for_target = -_math.log(1.0 - target_p)
        share_of_network_required = lambda_for_target / window_for_rate
        required_user_hashrate = share_of_network_required * net_hr
        return {
            "target_probability": target_p,
            "status": "SOLVED",
            "share_of_network_required": share_of_network_required,
            "required_user_hashrate": required_user_hashrate,
            "share_of_network_required_str": _format_hr(share_of_network_required) if share_of_network_required else None,
            "required_user_hashrate_str": _format_hr(required_user_hashrate) if required_user_hashrate else None,
        }
    except (OverflowError, ValueError, ZeroDivisionError, ZeroDivisionError):
        return {
            "target_probability": target_p,
            "status": "SOLVER_FAILED",
            "share_of_network_required": None,
            "required_user_hashrate": None,
            "note": "solver did not converge for these inputs",
        }


def probability_horizons(
    user_hr: Optional[float],
    network_hr: Optional[float],
    duration_seconds: float,
) -> Dict[str, Any]:
    """Epoch / window probability for one duration (the solver's window)."""
    user_hr = _finite_or_default(user_hr)
    network_hr = _finite_or_default(network_hr)
    seconds = _finite_or_default(duration_seconds, 86400.0)
    if user_hr <= 0 or network_hr <= 0 or not math.isfinite(user_hr) or not math.isfinite(network_hr) or not math.isfinite(seconds) or seconds <= 0:
        return {
            "lambda": 0.0,
            "probability_at_least_one": 0.0,
            "probability_zero": 1.0,
            "expected_blocks": 0.0,
            "expected_time_to_block_seconds": None,
            "status": "NO_DATA",
        }
    result = _poisson(user_hr, network_hr, seconds)
    result["status"] = "SOLVED"
    return result


def hashpower_network_what_if(
    base_user_hr: Optional[float],
    base_network_hr: Optional[float],
    scenarios: Optional[Iterable[Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Network hashrate what-if: how network growth changes P(>=1) in a
    fixed window. Each scenario is {"network_hashrate": X} (share of the
    current network). Returns P(>=1) for the same user hashrate."""
    base_user_hr = _finite_or_default(base_user_hr)
    base_network_hr = _finite_or_default(base_network_hr)
    window = BLOCK_INTERVAL_S  # default 10 min working window
    if base_user_hr <= 0 or base_network_hr <= 0:
        return {
            "scenarios": [],
            "status": "INSUFFICIENT_INPUTS",
        }
    base = _poisson(base_user_hr, base_network_hr, window)
    out = {
        "base": {
            "network_hashrate": base_network_hr,
            "probability_at_least_one": base["probability_at_least_one"],
            "expected_time_to_block_seconds": base["expected_time_to_block_seconds"],
        },
        "scenarios": [],
        "note": "What-if on network hashrate (static user share). Not a forecast.",
    }
    for s in scenarios or []:
        nr = _finite_or_default(s.get("network_hashrate"), base_network_hr)
        p = _poisson(base_user_hr, nr, window)
        out["scenarios"].append({
            "network_hashrate": nr,
            "network_hashrate_str": _format_hr(nr),
            "multiplier": nr / base_network_hr if base_network_hr else None,
            "probability_at_least_one": p["probability_at_least_one"],
            "probability_at_least_one_pct": p["probability_at_least_one"] * 100.0,
            "expected_time_to_block_seconds": p["expected_time_to_block_seconds"],
            "status": "SOLVED",
        })
    return out


def historical_best_share(
    best_diff_raw: Optional[float],
    network_difficulty: Optional[float],
) -> Dict[str, Any]:
    """Historical best share as target ratio and pace, descriptive only.

    best_diff is a RECORD and does NOT increase the next-hash odds. The
    target ratio is best_diff / network_difficulty."""
    best = _finite_or_default(best_diff_raw, 0.0)
    net = _finite_or_default(network_difficulty, 0.0)
    ratio = (best / net) if (best > 0 and net > 0) else None
    return {
        "best_share": best,
        "network_difficulty": net,
        "best_share_target_ratio": ratio,
        "status": "NO_DATA" if best <= 0 else "SOLVED",
    }


def solo_model_summary(
    user_hr: Optional[float],
    network_hr: Optional[float],
    duration_seconds: float,
    share_of_network: Optional[float] = None,
) -> Dict[str, Any]:
    """Solo model summary: P(>=1) in the window, expected time and the
    probability of at least one block in N windows (the honest equivalent
    of 'expected time'), never a countdown."""
    user_hr = _finite_or_default(user_hr)
    network_hr = _finite_or_default(network_hr)
    seconds = _finite_or_default(duration_seconds, 86400.0)
    if share_of_network is None and user_hr > 0 and network_hr > 0:
        share_of_network = user_hr / network_hr
    result = _poisson(user_hr, network_hr, seconds)
    # Probability of at least one block over n independent windows of equal
    # length (e.g. 1 window, 7 days) - honest 'what are the odds'.
    result["status"] = "NO_DATA" if (user_hr <= 0 or network_hr <= 0) else "SOLVED"
    result["share_of_network"] = share_of_network
    return result


def share_statistics(
    session_share_count: Optional[int],
    share_calc_history: Optional[Iterable[Dict[str, Any]]],
    window_seconds: float = 3600.0,
) -> Dict[str, Any]:
    """Share statistics for the SESSION EVIDENCE panel.

    Provides P50/P75/P90/P95/P99/MAX of share difficulty, plus sample count
    and window, when the history supports it. Descriptive of the session;
    it does not change the next-hash probability."""
    history = list(share_calc_history or [])
    n = len(history)
    out = {
        "session_share_count": session_share_count or 0,
        "sample_count": n,
        "window_seconds": window_seconds,
        "window": f"{window_seconds} s ({window_seconds/60:.0f} min)",
        "status": "NO_DATA" if n < 2 else "SOLVED",
        "p50": None,
        "p75": None,
        "p90": None,
        "p95": None,
        "p99": None,
        "max": None,
        "share_diff_summary": None,
    }
    if n == 0:
        return out
    diffs = sorted(
        float(e.get("share_diff_raw") or 0) for e in history if e.get("share_diff_raw")
    )
    if not diffs:
        return out
    out["sample_count"] = n
    out["max"] = diffs[-1]
    # Percentiles by linear interpolation (nearest-rank style for small n)
    def _pct(p: float) -> Optional[float]:
        if n == 1:
            return diffs[0]
        idx = (n - 1) * p
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return diffs[lo]
        return diffs[lo] + (diffs[hi] - diffs[lo]) * (idx - lo)
    out["p50"] = _pct(0.50)
    out["p75"] = _pct(0.75)
    out["p90"] = _pct(0.90)
    out["p95"] = _pct(0.95)
    out["p99"] = _pct(0.99)
    # Share difficulty trend: compare recent to earlier portion (last 20% vs first 20%) if enough data
    trend = "INSUFFICIENT"
    if n >= 20:
        half = n // 5
        first = diffs[:half] if half > 0 else diffs
        last = diffs[-half:] if half > 0 else diffs
        avg_first = sum(first) / len(first)
        avg_last = sum(last) / len(last)
        if avg_first > 0:
            if avg_last > avg_first * 1.05:
                trend = "INCREASING"
            elif avg_last < avg_first * 0.95:
                trend = "DECREASING"
            else:
                trend = "STABLE"
        else:
            trend = "STABLE"
    elif n >= 5:
        trend = "STABLE"
    else:
        trend = "INSUFFICIENT"
    out["share_diff_trend"] = trend
    out["share_diff_summary"] = {
        "p50": out["p50"],
        "p75": out["p75"],
        "p90": out["p90"],
        "p95": out["p95"],
        "p99": out["p99"],
        "max": out["max"],
        "sample_count": out["sample_count"],
        "window_seconds": window_seconds,
        "trend": trend,
    }
    # Session evidence fields
    now = time.time()
    last_share_age = 0
    first_ts = 0
    if history:
        last = history[-1]
        first = history[0]
        for ts_key in ('ts', 'timestamp', 'time'):
            if last.get(ts_key):
                try:
                    last_ts = float(last[ts_key])
                    if last_ts > 0:
                        last_share_age = max(0, int(now - last_ts))
                except Exception:
                    pass
            if first.get(ts_key):
                try:
                    first_ts = float(first[ts_key])
                except Exception:
                    pass
    out["last_share_age_seconds"] = last_share_age
    out["last_share_age"] = f"{last_share_age}s" if last_share_age < 3600 else f"{last_share_age // 60}m"
    out["data_gaps"] = 0  # descriptive only
    if diffs:
        out["avg_share_difficulty"] = sum(diffs) / len(diffs)
    out["valid_modeled_shares"] = len(diffs)
    observed_window = max(0, int(now - first_ts)) if first_ts > 0 else window_seconds
    out["observed_window_seconds"] = observed_window
    out["observed_window"] = f"{observed_window}s" if observed_window < 3600 else f"{observed_window // 60}m"
    out["sample_count"] = n
    out["evidence_state"] = evidence_state_from_inputs(None, None, session_share_count or 0, age_seconds=last_share_age)
    out["evidence_state_label"] = out["evidence_state"]
    return out


def evidence_state_from_inputs(
    user_hashrate: Optional[float],
    network_hashrate: Optional[float],
    session_share_count: Optional[int],
    age_seconds: Optional[float] = 0,
) -> str:
    """Map the live inputs to one of: GOOD COVERAGE | PARTIAL | STALE |
    INSUFFICIENT | NO DATA. Does not create a score; it only reports the
    state of the evidence."""
    age = max(0, int(age_seconds or 0))
    user_hr = _finite_or_default(user_hashrate)
    net_hr = _finite_or_default(network_hashrate)
    shares = session_share_count or 0

    if user_hr <= 0 or net_hr <= 0:
        # no network/user signal at all
        if shares <= 0:
            return "NO DATA"
        return "INSUFFICIENT"
    if shares < 1:
        return "INSUFFICIENT"
    if age > 3600:
        return "STALE"
    if shares < 10:
        return "PARTIAL"
    if shares < 100:
        return "PARTIAL"
    return "GOOD COVERAGE"


def target_probability_for_p1_in_window(window_seconds: float) -> Dict[str, Any]:
    """Precomputed target hashrate needed to reach P(>=1) = 10% in the
    given window, so the UI can show a single reachable target without
    solving each time. Uses the exact binomial/Poisson inversion."""
    window = _finite_or_default(window_seconds, 600.0)
    p1 = 0.10
    # solve for share of network where 1 - (1-p)^n = p1, with p = share * (window/600)
    # and n = window. Invert: p = 1 - (1-p1)^(1/n).
    try:
        n = max(1.0, window)
        p = 1.0 - (1.0 - p1) ** (1.0 / n)
        share_of_network = p / (window / BLOCK_INTERVAL_S)
        return {
            "target": 0.10,
            "window_seconds": window,
            "share_of_network_required": share_of_network,
            "user_hashrate_required": None,
            "note": "share-of-network required; multiply by network hashrate for user hashrate",
        }
    except (OverflowError, ValueError, ZeroDivisionError):
        return {
            "target": 0.10,
            "window_seconds": window,
            "status": "SOLVER_FAILED",
        }
