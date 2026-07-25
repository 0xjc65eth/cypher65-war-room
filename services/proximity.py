"""
CYPHER65 // Proximity meter helpers
====================================
bestDifficulty vs network difficulty, probability math, trend, hot-streak.
Extracted from app.py — imports shared state via services.state.

AUDIT 2026-07-23:
  - trend_1h_pct now uses rolling avg share difficulty (not best diff = monotonic)
  - chance_per_share uses avg_share_diff_raw from live_calc (not best diff)
  - quantum_lock assessment added (composite confidence score)
  - missing_inputs validation for every required field
  - share_calc_history deque increased from 20 → 120 entries
"""
import json
import math
import logging
import time

import services.state as state

from helpers import (
    parse_diff_to_float, fmt_diff, fmt_hashrate,
    human_int, human_secs_long, isfinite_v,
)

log = logging.getLogger("cypher65")

# ── Proximity constants ──────────────────────────────────────────────────
PROXIMITY_MILESTONES_PCT = [0.01, 0.1, 1.0, 5.0, 10.0, 25.0, 50.0, 100.0]
PROXIMITY_HOT_STREAK_THRESHOLD_PCT = 10.0  # >10% growth in rolling avg → hot streak
PROXIMITY_SAMPLE_THROTTLE_S = 60            # 1 sample/min → manageable DB size
_last_proximity_sample_ts = 0               # module-level throttle

# Quantum-lock thresholds
QUANTUM_LOCK_MIN_SHARES = 5          # minimum shares for any confidence
QUANTUM_LOCK_MIN_BEST_DIFF_T = 1.0   # minimum best diff in T for weak lock
QUANTUM_LOCK_STRONG_PCT = 1.0        # >1% of network → strong lock
QUANTUM_LOCK_MODERATE_PCT = 0.1      # >0.1% → moderate lock

_human_int = human_int
_human_secs_long = human_secs_long

# DB access is injected by app.py after import
_get_db = None


def reset_session():
    """Wipe all in-memory proximity state on address change.
    Called by app.py's _reset_session_state() to prevent data leakage
    between different wallet addresses.

    Defensive: skips if state.timeline_state is unavailable (logs at DEBUG),
    consistent with the _safe_wipe pattern in app.py."""
    global _last_proximity_sample_ts
    _last_proximity_sample_ts = 0
    # Clear all-time best diff so a new address starts fresh
    ts = getattr(state, "timeline_state", None)
    if ts is not None and isinstance(ts, dict):
        ts["all_time_best_diff_raw"] = 0.0
        log.info("[proximity] session reset — all-time best diff cleared")
    else:
        log.debug("[proximity] session reset — timeline_state unavailable, skipped")


def init(get_db_func):
    """Called by app.py to inject DB dependency and restore all-time best diff."""
    global _get_db
    _get_db = get_db_func
    _restore_all_time_best_diff()


def _restore_all_time_best_diff():
    """Restore all_time_best_diff from settings table (key `_all_time_best_diff`).
    Falls back to 0 if not set."""
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='_all_time_best_diff'")
        r = c.fetchone()
        conn.close()
        if r and r["value"]:
            try:
                v = float(r["value"])
                if v > 0:
                    state.timeline_state["all_time_best_diff_raw"] = v
            except Exception:
                pass
    except Exception:
        pass


def _persist_all_time_best_diff(value):
    """Best-effort write of all_time_best_diff to settings."""
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO settings(key,value,updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            ("_all_time_best_diff", str(value), int(time.time())),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[persist_all_time_best_diff] error: %s", e)


def _update_all_time_best_diff(raw_now):
    """If raw_now exceeds stored peak, bump and persist. Returns updated value."""
    if raw_now is None or raw_now <= 0:
        return state.timeline_state.get("all_time_best_diff_raw") or 0.0
    cur = state.timeline_state.get("all_time_best_diff_raw") or 0.0
    if raw_now > cur:
        state.timeline_state["all_time_best_diff_raw"] = raw_now
        _persist_all_time_best_diff(raw_now)
        return raw_now
    return cur


def _nearest_history_before(ts_target):
    """Return (best_diff_raw, network_difficulty_raw) from proximity_history
    nearest to ts_target (≤ ts_target, newest), or None."""
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute(
            "SELECT best_diff, network_difficulty FROM proximity_history "
            "WHERE ts <= ? ORDER BY ts DESC LIMIT 1",
            (int(ts_target),),
        )
        r = c.fetchone()
        conn.close()
        if r:
            return (r["best_diff"], r["network_difficulty"])
    except Exception:
        pass
    return None


def _sample_proximity(ts, best_diff_raw, current_difficulty, worker_hashrate, hot_streak):
    """Insert a proximity_history row, throttled to once per
    PROXIMITY_SAMPLE_THROTTLE_S seconds."""
    global _last_proximity_sample_ts
    if ts - _last_proximity_sample_ts < PROXIMITY_SAMPLE_THROTTLE_S:
        return
    try:
        pct = None
        if best_diff_raw and current_difficulty:
            pct = best_diff_raw / current_difficulty * 100.0
        conn = _get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO proximity_history "
            "(ts, best_diff, best_diff_str, all_time_best_diff, "
            " network_difficulty, worker_hashrate, pct_of_network, hot_streak) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                int(ts),
                best_diff_raw,
                fmt_diff(best_diff_raw) if best_diff_raw else "",
                state.timeline_state.get("all_time_best_diff_raw") or 0.0,
                current_difficulty,
                worker_hashrate,
                pct,
                1 if hot_streak else 0,
            ),
        )
        conn.commit()
        conn.close()
        _last_proximity_sample_ts = int(ts)
    except Exception as e:
        log.warning("[sample_proximity] error: %s", e)


# ── Rolling average share difficulty (trend calculation) ─────────────────


def _compute_rolling_avg_share_diffs(sch, ts_now, window_seconds=3600):
    """Compute rolling avg share difficulty over two windows:
      - 'recent': shares within window_seconds ago (default 1h)
      - 'old':    shares before that (but still from share_calc_history)

    Returns dict with:
      - recent_avg_raw:   avg share_diff_raw for recent window (or None)
      - recent_avg_str:   formatted version
      - recent_count:     number of shares in recent window
      - old_avg_raw:      avg share_diff_raw for old window (or None)
      - trend_pct:        % change from old to recent
      - trend_label:      "rising" / "falling" / "flat" / "insufficient"
      - window_seconds:   the window used
    """
    result = {
        "recent_avg_raw": None,
        "recent_avg_str": None,
        "recent_count": 0,
        "old_avg_raw": None,
        "trend_pct": 0.0,
        "trend_label": "insufficient",
        "window_seconds": window_seconds,
    }
    if not sch or len(sch) < 2:
        return result

    # Split: recent = shares within window, old = shares before that
    cutoff = ts_now - window_seconds
    recent = [e for e in sch if (e.get("ts") or 0) >= cutoff]
    old = [e for e in sch if (e.get("ts") or 0) < cutoff]

    if len(recent) < 2:
        # Not enough recent data — fall back to best-available window
        # Use the most recent half vs. the older half of all data
        mid = len(sch) // 2
        recent = list(sch)[-mid:] if mid > 0 else list(sch)
        old = list(sch)[:mid] if mid > 0 else []

    def _avg(entries):
        if not entries:
            return None
        vals = [e.get("share_diff_raw") or 0 for e in entries if e.get("share_diff_raw")]
        if not vals:
            return None
        return sum(vals) / len(vals)

    recent_avg = _avg(recent)
    old_avg = _avg(old)

    result["recent_avg_raw"] = recent_avg
    result["recent_avg_str"] = fmt_diff(recent_avg) if recent_avg else None
    result["recent_count"] = len(recent)

    if old_avg and recent_avg and old_avg > 0:
        trend_pct = (recent_avg - old_avg) / old_avg * 100.0
        result["trend_pct"] = trend_pct
        if trend_pct >= PROXIMITY_HOT_STREAK_THRESHOLD_PCT:
            result["trend_label"] = "rising"
        elif trend_pct <= -PROXIMITY_HOT_STREAK_THRESHOLD_PCT:
            result["trend_label"] = "falling"
        elif abs(trend_pct) < 1.0:
            result["trend_label"] = "flat"
        else:
            result["trend_label"] = "stable"

    return result


# ── Quantum-lock assessment ──────────────────────────────────────────────


def _compute_quantum_lock(pct_cur, best_diff_raw, net_diff, sch, session_shares, trend_pct, worker_hps):
    """Assess mining operation "lock" — a composite confidence score.
    Components:
      1. share_density:  how many shares observed (proxy for work done)
      2. proximity:      current pct_of_network (how close to block)
      3. avg_share_power: avg share diff relative to best diff
      4. momentum:       trend direction

    Returns dict with status, score (0-100), label, and components.
    """
    # Fallback defaults
    lock = {
        "status": "NO_DATA",
        "score": 0,
        "label": "awaiting share data — submit share to compute quantum lock",
        "components": {"shares": 0, "proximity": 0, "power": 0, "momentum": 0},
        "confidence": "NONE",
        "assessed_at": int(time.time()),
    }

    if not best_diff_raw or not net_diff or session_shares < 1:
        return lock

    # 1. Share density score (0-30)
    #    More shares = better statistical confidence
    sch_count = len(sch) if sch else 0
    actual_shares = max(session_shares, sch_count)
    if actual_shares >= 1000:
        density_score = 30
    elif actual_shares >= 100:
        density_score = 20
    elif actual_shares >= QUANTUM_LOCK_MIN_SHARES:
        density_score = 10
    else:
        density_score = 5

    # 2. Proximity score (0-40)
    #    Higher pct_of_network = closer to block = stronger lock
    if pct_cur >= QUANTUM_LOCK_STRONG_PCT:
        prox_score = 40
    elif pct_cur >= QUANTUM_LOCK_MODERATE_PCT:
        prox_score = 30
    elif pct_cur >= 0.01:
        prox_score = 15
    elif pct_cur > 0:
        prox_score = 5
    else:
        prox_score = 0

    # 3. Share power score (0-20)
    #    Avg share diff / best diff → if shares are near best, strong
    if sch and best_diff_raw > 0:
        avg_share = sum((e.get("share_diff_raw") or 0) for e in sch) / len(sch)
        power_ratio = avg_share / best_diff_raw if best_diff_raw > 0 else 0
        if power_ratio >= 0.5:
            power_score = 20
        elif power_ratio >= 0.25:
            power_score = 15
        elif power_ratio >= 0.1:
            power_score = 10
        elif power_ratio >= 0.01:
            power_score = 5
        else:
            power_score = 2
    else:
        power_score = 0

    # 4. Momentum score (0-10)
    if trend_pct >= PROXIMITY_HOT_STREAK_THRESHOLD_PCT:
        momentum_score = 10
    elif trend_pct >= 5:
        momentum_score = 7
    elif trend_pct > 0:
        momentum_score = 3
    elif abs(trend_pct) < 1:
        momentum_score = 5  # stable = good
    else:
        momentum_score = 1  # falling

    total_score = density_score + prox_score + power_score + momentum_score

    # Status label
    if total_score >= 75:
        status = "STRONG_LOCK"
        label = "Strong quantum lock — statistically tracking at high confidence"
        confidence = "HIGH"
    elif total_score >= 50:
        status = "MODERATE_LOCK"
        label = "Moderate quantum lock — building statistical significance"
        confidence = "MEDIUM"
    elif total_score >= 25:
        status = "WEAK_LOCK"
        label = "Weak quantum lock — early stage, needs more shares"
        confidence = "LOW"
    elif total_score >= 5:
        status = "TRACKING"
        label = "Tracking — insufficient data for meaningful assessment"
        confidence = "VERY_LOW"
    else:
        status = "NO_DATA"
        label = "No data — submit a share to begin quantum lock assessment"
        confidence = "NONE"

    return {
        "status": status,
        "score": total_score,
        "label": label,
        "confidence": confidence,
        "components": {
            "shares": density_score,
            "proximity": prox_score,
            "power": power_score,
            "momentum": momentum_score,
        },
        "assessed_at": int(time.time()),
        "details": {
            "proximity_pct": pct_cur,
            "share_count": actual_shares,
            "trend_pct": trend_pct,
        },
    }


# ── Public compute entry point ──────────────────────────────────────────


def compute_proximity(worker, current_difficulty, net_hashrate, ts):
    """Compute the full proximity meter payload for /api/proximity and
    included in /api/snapshot. Pure compute: never raises (returns {} on
    insufficient data)."""
    out = {"ts": ts}
    # Collect missing inputs for validation
    missing_inputs = []

    try:
        best_diff_raw = parse_diff_to_float(worker.get("bestDifficulty")) if worker else None
        if not best_diff_raw:
            missing_inputs.append("worker.bestDifficulty")

        net_diff = float(current_difficulty) if current_difficulty else None
        if not net_diff:
            missing_inputs.append("network.difficulty")

        worker_hps = float(worker.get("hashrate") or 0) if worker else 0
        if not worker_hps:
            missing_inputs.append("worker.hashrate")

        if missing_inputs:
            return {
                **out,
                "insufficient_data": True,
                "missing_inputs": missing_inputs,
                "reason": f"Missing: {', '.join(missing_inputs)}",
            }

        # All required inputs present — proceed
        best_diff_raw = best_diff_raw or 0.0
        net_diff = net_diff or 0.0

        # all-time peak (persisted across restarts)
        all_time_raw = _update_all_time_best_diff(best_diff_raw)

        pct_cur = best_diff_raw / net_diff * 100.0
        pct_all = all_time_raw / net_diff * 100.0
        distance = net_diff / best_diff_raw  # how many × smaller than a block

        expected_secs = None
        blocks_per_year = None
        if worker_hps > 0:
            hashes_per_block = net_diff * (2 ** 32)
            expected_secs = hashes_per_block / worker_hps
            seconds_per_year = 365.25 * 86400
            blocks_per_year = seconds_per_year / expected_secs

        # ── Trend: rolling avg share difficulty (NOT best diff) ──────
        sch = list(state.timeline_state.get("share_calc_history") or [])
        rolling = _compute_rolling_avg_share_diffs(sch, ts, window_seconds=3600)

        # Use rolling trend as primary, best-diff trend as fallback when no share data
        if rolling["trend_label"] != "insufficient" and rolling["trend_pct"] != 0:
            trend_1h_pct = rolling["trend_pct"]
            trend_label = rolling["trend_label"]
            hot_streak = bool(trend_1h_pct >= PROXIMITY_HOT_STREAK_THRESHOLD_PCT)
        else:
            # Fallback: best-diff trend (monotonic, only meaningful on new best)
            nearest_1h = _nearest_history_before(ts - 3600)
            trend_1h_pct = (
                (best_diff_raw - nearest_1h[0]) / nearest_1h[0] * 100.0
                if nearest_1h and nearest_1h[0] else 0.0
            )
            if trend_1h_pct >= PROXIMITY_HOT_STREAK_THRESHOLD_PCT:
                trend_label = "rising"
            elif trend_1h_pct <= -PROXIMITY_HOT_STREAK_THRESHOLD_PCT:
                trend_label = "falling"
            else:
                trend_label = "flat"
            hot_streak = bool(trend_1h_pct >= PROXIMITY_HOT_STREAK_THRESHOLD_PCT)

        # ── Next milestone ladder step ───────────────────────────────
        next_ms = None
        for m in PROXIMITY_MILESTONES_PCT:
            if m > pct_cur:
                next_ms = m
                break
        if next_ms is None:
            next_ms = PROXIMITY_MILESTONES_PCT[-1]

        # ── CHANCE per share: use avg_share_diff_raw when available ──
        avg_share_diff_raw = None
        if sch:
            avg_share_diff_raw = sum((e.get("share_diff_raw") or 0) for e in sch) / len(sch)

        chance_per_share_raw = avg_share_diff_raw if avg_share_diff_raw and avg_share_diff_raw > 0 else best_diff_raw
        if chance_per_share_raw and net_diff:
            chance_per_share_in = int(round(net_diff / chance_per_share_raw))
            chance_per_share_label = f"1 in {chance_per_share_in:,}"
            chance_source = "avg" if avg_share_diff_raw and avg_share_diff_raw > 0 else "best"
        else:
            chance_per_share_label = "—"
            chance_source = "none"

        # ── Quantum-lock assessment ──────────────────────────────────
        session_shares = state.timeline_state.get("session_share_count", 0) or 0
        quantum_lock = _compute_quantum_lock(
            pct_cur, best_diff_raw, net_diff,
            sch, session_shares, trend_1h_pct, worker_hps,
        )

        out.update({
            "best_diff_str": fmt_diff(best_diff_raw),
            "best_diff_raw": best_diff_raw,
            "all_time_best_diff_str": fmt_diff(all_time_raw),
            "all_time_best_diff_raw": all_time_raw,
            "network_difficulty_str": fmt_diff(net_diff),
            "network_difficulty_raw": net_diff,
            "worker_hashrate_ths": worker_hps / 1e12 if worker_hps else 0.0,
            "pct_of_network_cur": pct_cur,
            "pct_of_network_all_time": pct_all,
            "distance_factor": distance,
            "distance_label": (
                "~" + _human_int(distance) + "× smaller than a block"
                if distance >= 1000
                else f"{distance:.2f}× smaller than a block"
            ),
            "expected_time_secs": expected_secs,
            "expected_time_human": _human_secs_long(expected_secs) if expected_secs else "—",
            "blocks_per_year": blocks_per_year,
            "chance_per_share_label": chance_per_share_label,
            "chance_per_share_raw": chance_per_share_raw,
            "chance_per_share_source": chance_source,
            "trend_1h_pct": trend_1h_pct,
            "trend_label": trend_label,
            "trend_rolling": rolling,  # expose raw rolling data for frontend
            "hot_streak": hot_streak,
            "milestone_cur_pct": pct_cur,
            "next_milestone_pct": next_ms,
            "next_milestone_label": f"{next_ms:g}% of network difficulty",
            "milestones_achieved": [
                m for m in PROXIMITY_MILESTONES_PCT if m <= pct_all
            ],
            "quantum_lock": quantum_lock,
        })

        # LIVE HASH CALCULATOR payload: latest per-share calc + cumulative stats + charts
        try:
            latest = dict(sch[-1]) if sch else None
            ticker = [dict(e) for e in sch[-12:]]  # last 12 for ticker + sparkline charts
            share_diff_avg = avg_share_diff_raw or 0.0
            totals = {
                "shares_so_far": session_shares,
                "shares_in_ticker": len(sch),
                "avg_share_diff_raw": share_diff_avg,
                "avg_share_diff_str": fmt_diff(share_diff_avg) if share_diff_avg else "—",
            }
            if share_diff_avg and net_diff:
                p_per_share = share_diff_avg / net_diff
                shares_per_block = net_diff / share_diff_avg
                totals["avg_p_block_per_share"] = p_per_share
                totals["p_per_share_pct_str"] = (
                    f"{p_per_share * 100:.4e}%"
                    if p_per_share < 0.01
                    else f"{p_per_share * 100:.4f}%"
                )
                totals["shares_per_block_expected"] = shares_per_block
                totals["shares_per_block_expected_str"] = f"{int(shares_per_block):,}"
                if session_shares > 0:
                    cum_p = 1 - (1 - p_per_share) ** session_shares
                    totals["cum_p_block"] = cum_p
                    totals["cum_p_block_pct_str"] = (
                        f"{cum_p * 100:.4e}%"
                        if cum_p < 0.01
                        else f"{cum_p * 100:.4f}%"
                    )
                    expected_blocks = session_shares * p_per_share
                    totals["expected_blocks"] = expected_blocks
                    totals["expected_blocks_str"] = f"{expected_blocks:.4e}"
                # Expected time per share at this avg diff / hashrate
                if worker_hps > 0:
                    expected_time_per_share = (share_diff_avg * (2 ** 32)) / worker_hps
                    totals["expected_time_per_share_s"] = expected_time_per_share
                    totals["expected_time_per_share_str"] = _human_secs_long(expected_time_per_share)

            # ── Charts data: cumulative P(block) progression ──
            # Uses EACH share's actual p_block_this_share (not a constant average)
            # for a didactic chart showing real variance in share quality.
            charts_data = {"cumulative_timeline": [], "consistency_check": {}}
            if sch and share_diff_avg and net_diff:
                cum_so_far = 0.0
                for idx, e in enumerate(sch):
                    p_this = e.get("p_block_this_share") or 0
                    cum_so_far = 1 - (1 - cum_so_far) * (1 - p_this)
                    charts_data["cumulative_timeline"].append({
                        "share_idx": (session_shares - len(sch) + idx + 1),
                        "cum_p_block": cum_so_far,
                        "p_this_share": p_this,
                    })

                # ── Consistency check ──
                # Verify three cross-field relationships:
                # 1. cum_p ≈ 1 - e^(-expected_blocks)  [Poisson approximation for small p]
                # 2. avg instantaneous HR ≈ worker hashrate
                # 3. avg share difficulty × shares_per_second ≈ worker hashrate
                cc = {"status": "CONSISTENT", "checks": []}

                # Check 1: cum_p vs expected_blocks Poisson approximation
                if expected_blocks is not None and expected_blocks > 0:
                    poisson_approx = 1 - math.exp(-expected_blocks)
                    deviation = abs(cum_so_far - poisson_approx) / max(cum_so_far, 1e-30) * 100
                    if deviation > 5:
                        cc["checks"].append({
                            "check": "cum_p_vs_poisson",
                            "status": "WARN",
                            "detail": f"cum_p ({cum_so_far:.6e}) vs Poisson ({poisson_approx:.6e}) dev {deviation:.1f}%",
                        })
                    else:
                        cc["checks"].append({
                            "check": "cum_p_vs_poisson",
                            "status": "PASS",
                            "detail": f"cum_p={cum_so_far:.6e} ≈ 1-e^(-λ)={poisson_approx:.6e} (dev {deviation:.2f}%)",
                        })

                # Check 2: avg inst HR vs worker hashrate
                inst_hrs = [e.get("instantaneous_hr_hps") or 0 for e in sch if e.get("instantaneous_hr_hps")]
                if inst_hrs and worker_hps > 0:
                    avg_inst_hr = sum(inst_hrs) / len(inst_hrs)
                    hr_deviation = abs(avg_inst_hr - worker_hps) / max(worker_hps, 1) * 100
                    if hr_deviation > 50:
                        cc["checks"].append({
                            "check": "avg_inst_hr_vs_worker_hr",
                            "status": "WARN",
                            "detail": f"avg inst HR ({fmt_hashrate(avg_inst_hr)}) vs worker HR ({fmt_hashrate(worker_hps)}) dev {hr_deviation:.0f}%",
                        })
                    else:
                        cc["checks"].append({
                            "check": "avg_inst_hr_vs_worker_hr",
                            "status": "PASS",
                            "detail": f"avg inst HR {fmt_hashrate(avg_inst_hr)} ≈ worker HR {fmt_hashrate(worker_hps)}",
                        })

                # Check 3: implied hashrate from share diff × gap vs worker hashrate
                gaps = [e.get("gap") for e in sch if e.get("gap") and e.get("gap") > 0]
                raw_diffs = [e.get("share_diff_raw") for e in sch if e.get("share_diff_raw") and e.get("share_diff_raw") > 0]
                if gaps and raw_diffs and len(gaps) == len(raw_diffs) and worker_hps > 0:
                    implied_hrs = [(raw_diffs[i] * (2 ** 32)) / gaps[i] for i in range(len(gaps))]
                    avg_implied_hr = sum(implied_hrs) / len(implied_hrs)
                    impl_dev = abs(avg_implied_hr - worker_hps) / max(worker_hps, 1) * 100
                    if impl_dev > 50:
                        cc["checks"].append({
                            "check": "implied_hr_vs_worker_hr",
                            "status": "WARN",
                            "detail": f"implied from diff×gap ({fmt_hashrate(avg_implied_hr)}) vs worker ({fmt_hashrate(worker_hps)}) dev {impl_dev:.0f}%",
                        })
                    else:
                        cc["checks"].append({
                            "check": "implied_hr_vs_worker_hr",
                            "status": "PASS",
                            "detail": f"implied HR {fmt_hashrate(avg_implied_hr)} ≈ worker HR {fmt_hashrate(worker_hps)}",
                        })

                if all(c["status"] == "PASS" for c in cc["checks"]):
                    cc["status"] = "CONSISTENT"
                elif any(c["status"] == "WARN" for c in cc["checks"]):
                    cc["status"] = "INCONSISTENT"
                charts_data["consistency_check"] = cc

            out["live_calc"] = {
                "latest": latest,
                "ticker": ticker,
                "session_totals": totals,
                "charts_data": charts_data,
            }
        except Exception as e:
            log.warning("[compute_proximity live_calc] error: %s", e)

        return out
    except Exception as e:
        log.warning("[compute_proximity] error: %s", e)
        return {
            **out,
            "insufficient_data": True,
            "missing_inputs": missing_inputs or ["unknown"],
            "error": str(e),
        }
