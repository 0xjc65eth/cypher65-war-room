"""
CYPHER65 // Block Probability Lab
==========================
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
from datetime import datetime, timezone
from typing import Dict, Any, Iterable, List, Optional

BLOCK_INTERVAL_S = 600.0


def _finite_or_default(value: float, default: float = 0.0) -> float:
    """Normalize numeric inputs without admitting booleans, NaN or Infinity."""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _poisson(user_hr: float, net_hr: float, seconds: float) -> Dict[str, Any]:
    """Core Poisson block-finding probability.

    lambda = (user_hr / net_hr) * (seconds / 600)
    P(>=1) = 1 - e^-lambda
    expected_blocks = lambda
    expected_time = 600 * net_hr / user_hr
    """
    no_data = {
        "lambda": 0.0,
        "probability_at_least_one": 0.0,
        "probability_zero": 1.0,
        "expected_blocks": 0.0,
        "expected_time_to_block_seconds": None,
        "status": "NO_DATA",
    }
    if user_hr <= 0 or net_hr <= 0 or seconds <= 0:
        return no_data
    if not (
        math.isfinite(user_hr) and math.isfinite(net_hr) and math.isfinite(seconds)
    ):
        return no_data
    lambda_rate = (user_hr / net_hr) * (seconds / BLOCK_INTERVAL_S)
    # Preserve representable results when an intermediate ratio over/underflows.
    if not math.isfinite(lambda_rate) or lambda_rate <= 0:
        try:
            lambda_rate = math.exp(
                math.log(user_hr)
                - math.log(net_hr)
                + math.log(seconds)
                - math.log(BLOCK_INTERVAL_S)
            )
        except OverflowError:
            return no_data
    if not math.isfinite(lambda_rate) or lambda_rate <= 0:
        return no_data
    prob_zero = math.exp(-lambda_rate)
    # Divide first: 600 * net_hr overflows even for equal finite rates.
    mean_interval = (net_hr / user_hr) * BLOCK_INTERVAL_S
    return {
        "lambda": lambda_rate,
        "probability_at_least_one": -math.expm1(-lambda_rate),
        "probability_zero": prob_zero,
        "expected_blocks": lambda_rate,
        "expected_time_to_block_seconds": (
            mean_interval
            if math.isfinite(mean_interval) and mean_interval > 0
            else None
        ),
        "status": "SOLVED",
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
    now = (
        int(observed_at)
        if observed_at is not None
        else int(datetime.now(timezone.utc).timestamp())
    )
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
    window = _finite_or_default(window_seconds)
    target_p = _finite_or_default(target_p)

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
        lambda_for_target = -math.log1p(-target_p)
        share_of_network_required = lambda_for_target * BLOCK_INTERVAL_S / window
        required_user_hashrate = share_of_network_required * net_hr
        if not (
            math.isfinite(share_of_network_required)
            and share_of_network_required > 0
            and math.isfinite(required_user_hashrate)
            and required_user_hashrate > 0
        ):
            raise ValueError("target result is not representable")
        return {
            "target_probability": target_p,
            "status": "SOLVED",
            "share_of_network_required": share_of_network_required,
            "required_user_hashrate": required_user_hashrate,
            "share_of_network_required_str": f"{share_of_network_required:.6g}×",
            "required_user_hashrate_str": (
                _format_hr(required_user_hashrate) if required_user_hashrate else None
            ),
        }
    except (OverflowError, ValueError, ZeroDivisionError):
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
    seconds = _finite_or_default(duration_seconds)
    if (
        user_hr <= 0
        or network_hr <= 0
        or not math.isfinite(user_hr)
        or not math.isfinite(network_hr)
        or not math.isfinite(seconds)
        or seconds <= 0
    ):
        return {
            "lambda": 0.0,
            "probability_at_least_one": 0.0,
            "probability_zero": 1.0,
            "expected_blocks": 0.0,
            "expected_time_to_block_seconds": None,
            "status": "NO_DATA",
        }
    return _poisson(user_hr, network_hr, seconds)


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
            "status": base["status"],
        },
        "scenarios": [],
        "note": "What-if on network hashrate (static user share). Not a forecast.",
    }
    for s in scenarios or []:
        nr = _finite_or_default(s.get("network_hashrate"))
        p = _poisson(base_user_hr, nr, window)
        multiplier = nr / base_network_hr if nr > 0 else None
        if multiplier is not None and not math.isfinite(multiplier):
            multiplier = None
        out["scenarios"].append(
            {
                "network_hashrate": nr,
                "network_hashrate_str": _format_hr(nr),
                "multiplier": multiplier,
                "probability_at_least_one": p["probability_at_least_one"],
                "probability_at_least_one_pct": p["probability_at_least_one"] * 100.0,
                "expected_time_to_block_seconds": p["expected_time_to_block_seconds"],
                "status": p["status"],
            }
        )
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
    if ratio is not None and not math.isfinite(ratio):
        ratio = None
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
    seconds = _finite_or_default(duration_seconds)
    if share_of_network is None and user_hr > 0 and network_hr > 0:
        share_of_network = user_hr / network_hr
    share_of_network = _finite_or_default(share_of_network, -1.0)
    if share_of_network < 0:
        share_of_network = None
    result = _poisson(user_hr, network_hr, seconds)
    # Probability of at least one block over n independent windows of equal
    # length (e.g. 1 window, 7 days) - honest 'what are the odds'.
    result["share_of_network"] = share_of_network
    return result


def valid_share_history(history):
    """Copy finite positive observations without modifying shared telemetry."""
    valid = []
    for entry in history or []:
        if not isinstance(entry, dict) or isinstance(entry.get("share_diff_raw"), bool):
            continue
        try:
            diff = float(entry.get("share_diff_raw"))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(diff) and diff > 0:
            valid.append({**entry, "share_diff_raw": diff})
    return valid


def positive_share_mean(values):
    """Mean of validated positive finite values, without sum overflow."""
    if not values:
        return None
    scale = max(values)
    return scale * (math.fsum(value / scale for value in values) / len(values))


def share_statistics(
    session_share_count: Optional[int],
    share_calc_history: Optional[Iterable[Dict[str, Any]]],
    window_seconds: float = 3600.0,
    user_hashrate: Optional[float] = None,
    network_hashrate: Optional[float] = None,
    age_seconds: Optional[float] = None,
    observed_now: Optional[float] = None,
) -> Dict[str, Any]:
    """Summarize valid share difficulties and evidence actually present.

    Percentiles sort valid difficulty values; trend preserves their original
    chronological order. Missing timestamps, gap counts, and observation
    windows remain unknown when the retained history cannot prove them.
    """
    valid_entries = valid_share_history(share_calc_history)
    chronological_diffs = [entry["share_diff_raw"] for entry in valid_entries]
    diffs = sorted(chronological_diffs)
    count = len(diffs)

    out = {
        "session_share_count": session_share_count,
        "sample_count": count,
        "window_seconds": window_seconds,
        "window": f"{window_seconds} s ({window_seconds/60:.0f} min)",
        "status": "NO_DATA" if count < 2 else "SOLVED",
        "p50": None,
        "p75": None,
        "p90": None,
        "p95": None,
        "p99": None,
        "max": diffs[-1] if diffs else None,
        "share_diff_summary": None,
    }

    def _pct(percentile: float) -> Optional[float]:
        if not count:
            return None
        if count == 1:
            return diffs[0]
        idx = (count - 1) * percentile
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return diffs[lo]
        return diffs[lo] + (diffs[hi] - diffs[lo]) * (idx - lo)

    for percentile in (50, 75, 90, 95, 99):
        out[f"p{percentile}"] = _pct(percentile / 100)

    trend = "INSUFFICIENT"
    if count >= 20:
        chunk = max(1, count // 5)
        earlier = chronological_diffs[:chunk]
        recent = chronological_diffs[-chunk:]
        avg_earlier = positive_share_mean(earlier)
        avg_recent = positive_share_mean(recent)
        ratio = avg_recent / avg_earlier
        if ratio > 1.05:
            trend = "INCREASING"
        elif ratio < 0.95:
            trend = "DECREASING"
        else:
            trend = "STABLE"
    elif count >= 5:
        trend = "STABLE"
    out["share_diff_trend"] = trend
    out["share_diff_summary"] = {
        "p50": out["p50"],
        "p75": out["p75"],
        "p90": out["p90"],
        "p95": out["p95"],
        "p99": out["p99"],
        "max": out["max"],
        "sample_count": count,
        "window_seconds": window_seconds,
        "trend": trend,
    }

    def _finite_number(value):
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    now = _finite_number(observed_now)
    now = now if now is not None and now > 0 else None
    ts_values = []
    timestamp_present = False
    for entry in valid_entries:
        for key in ("ts", "timestamp", "time"):
            if key not in entry:
                continue
            timestamp_present = True
            value = _finite_number(entry[key])
            if value is not None and value > 0 and (now is None or value <= now):
                ts_values.append(value)
            break
    # A partial, future or reversed timestamp sequence cannot prove the age
    # or span of this retained history. Never repair it with a different clock.
    temporal_valid = (
        count > 0
        and len(ts_values) == count
        and all(a <= b for a, b in zip(ts_values, ts_values[1:]))
    )
    last_age = None
    if temporal_valid and now is not None:
        last_age = int(now - ts_values[-1])
    elif count and not timestamp_present:
        fallback_age = _finite_number(age_seconds)
        if (
            fallback_age is not None
            and fallback_age >= 0
            and math.copysign(1, fallback_age) > 0
        ):
            last_age = int(fallback_age)
    observed_window = (
        int(ts_values[-1] - ts_values[0]) if temporal_valid and count >= 2 else None
    )
    out.update(
        {
            "valid_modeled_shares": count,
            "avg_share_difficulty": positive_share_mean(chronological_diffs),
            "data_gaps": None,
            "last_share_age_seconds": last_age,
            "last_share_age": (
                (f"{last_age}s" if last_age < 3600 else f"{last_age // 60}m")
                if last_age is not None
                else None
            ),
            "observed_window_seconds": observed_window,
            "observed_window": (
                (
                    f"{observed_window}s"
                    if observed_window < 3600
                    else f"{observed_window // 60}m"
                )
                if observed_window is not None
                else None
            ),
            "evidence_state": evidence_state_from_inputs(
                user_hashrate,
                network_hashrate,
                count,
                last_age,
            ),
        }
    )
    out["evidence_state_label"] = out["evidence_state"]
    return out


def evidence_state_from_inputs(
    user_hashrate: Optional[float],
    network_hashrate: Optional[float],
    session_share_count: Optional[int],
    age_seconds: Optional[float] = None,
) -> str:
    """Map the live inputs to one of: GOOD COVERAGE | PARTIAL | STALE |
    INSUFFICIENT | NO DATA. Does not create a score; it only reports the
    state of the evidence."""
    try:
        age_value = float(age_seconds) if not isinstance(age_seconds, bool) else -1
        age = (
            int(age_value)
            if math.isfinite(age_value)
            and age_value >= 0
            and math.copysign(1, age_value) > 0
            else None
        )
    except (TypeError, ValueError, OverflowError):
        age = None
    try:
        user_hr = _finite_or_default(user_hashrate)
        net_hr = _finite_or_default(network_hashrate)
    except OverflowError:
        user_hr = net_hr = 0
    if isinstance(user_hashrate, bool) or not math.isfinite(user_hr):
        user_hr = 0
    if isinstance(network_hashrate, bool) or not math.isfinite(net_hr):
        net_hr = 0
    shares = session_share_count or 0

    if user_hr <= 0 or net_hr <= 0:
        # Without measured hashrate the evidence cannot be interpreted.
        if shares <= 0:
            return "NO DATA"
        return "INSUFFICIENT"
    if shares < 1:
        return "INSUFFICIENT"
    if age is not None and age > 3600:
        return "STALE"
    if age is None:
        return "PARTIAL"
    if shares < 10:
        return "PARTIAL"
    if shares < 100:
        return "PARTIAL"
    return "GOOD COVERAGE"


def target_probability_for_p1_in_window(window_seconds: float) -> Dict[str, Any]:
    """Return the 10% target ratio under the forward model's same Poisson law.

    Example: a 600-second window requires ``-log(0.9)`` of the supplied
    network hashrate. This is a scenario, not a feasible purchase or deadline.
    """
    window = _finite_or_default(window_seconds)
    # Unit rates expose only the ratio; no network sample or fallback is added.
    solved = target_probability_solver(1.0, 1.0, 0.10, window)
    return {
        "target": 0.10,
        "window_seconds": window,
        "status": solved["status"],
        "share_of_network_required": solved["share_of_network_required"],
        "user_hashrate_required": None,
        "note": "share-of-network required; multiply by network hashrate for user hashrate",
    }
