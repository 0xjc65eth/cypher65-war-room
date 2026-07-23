"""
CYPHER65 // Proximity meter helpers
====================================
bestDifficulty vs network difficulty, probability math, trend, hot-streak.
Extracted from app.py — imports shared state via services.state.
"""
import json
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
PROXIMITY_HOT_STREAK_THRESHOLD_PCT = 10.0  # >10% growth in 1h → hot streak
PROXIMITY_SAMPLE_THROTTLE_S = 60            # 1 sample/min → manageable DB size
_last_proximity_sample_ts = 0               # module-level throttle

_human_int = human_int
_human_secs_long = human_secs_long

# DB access is injected by app.py after import
_get_db = None


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


def compute_proximity(worker, current_difficulty, net_hashrate, ts):
    """Compute the full proximity meter payload for /api/proximity and
    included in /api/snapshot. Pure compute: never raises (returns {} on
    insufficient data)."""
    out = {"ts": ts}
    try:
        best_diff_raw = parse_diff_to_float(worker.get("bestDifficulty")) if worker else 0.0
        if not best_diff_raw:
            return {**out, "insufficient_data": True}
        net_diff = float(current_difficulty) if current_difficulty else 0.0
        if not net_diff:
            return {**out, "insufficient_data": True, "reason": "no network_difficulty"}

        # all-time peak (persisted across restarts)
        all_time_raw = _update_all_time_best_diff(best_diff_raw)

        pct_cur = best_diff_raw / net_diff * 100.0
        pct_all = all_time_raw / net_diff * 100.0
        distance = net_diff / best_diff_raw  # how many × smaller than a block
        worker_hps = float(worker.get("hashrate") or 0)
        expected_secs = None
        blocks_per_year = None
        if worker_hps > 0:
            hashes_per_block = net_diff * (2 ** 32)
            expected_secs = hashes_per_block / worker_hps
            seconds_per_year = 365.25 * 86400
            blocks_per_year = seconds_per_year / expected_secs

        # Trend (compare to row 1h, 6h, 24h ago)
        nearest_1h = _nearest_history_before(ts - 3600)
        nearest_6h = _nearest_history_before(ts - 6 * 3600)
        nearest_24h = _nearest_history_before(ts - 86400)
        trend_1h_pct = (
            (best_diff_raw - nearest_1h[0]) / nearest_1h[0] * 100.0
            if nearest_1h and nearest_1h[0] else 0.0
        )
        trend_6h_pct = (
            (best_diff_raw - nearest_6h[0]) / nearest_6h[0] * 100.0
            if nearest_6h and nearest_6h[0] else 0.0
        )
        trend_24h_pct = (
            (best_diff_raw - nearest_24h[0]) / nearest_24h[0] * 100.0
            if nearest_24h and nearest_24h[0] else 0.0
        )
        if trend_1h_pct >= PROXIMITY_HOT_STREAK_THRESHOLD_PCT:
            trend_label = "rising"
        elif trend_1h_pct <= -PROXIMITY_HOT_STREAK_THRESHOLD_PCT:
            trend_label = "falling"
        else:
            trend_label = "flat"

        # Next milestone ladder step above current pct_of_network
        next_ms = None
        for m in PROXIMITY_MILESTONES_PCT:
            if m > pct_cur:
                next_ms = m
                break
        if next_ms is None:
            next_ms = PROXIMITY_MILESTONES_PCT[-1]  # 100% (block found!)

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
            "chance_per_share_label": (
                f"1 in {int(round(net_diff / best_diff_raw)):,}"
                if best_diff_raw else "—"
            ),
            "trend_1h_pct": trend_1h_pct,
            "trend_6h_pct": trend_6h_pct,
            "trend_24h_pct": trend_24h_pct,
            "trend_label": trend_label,
            "hot_streak": bool(trend_1h_pct >= PROXIMITY_HOT_STREAK_THRESHOLD_PCT),
            "milestone_cur_pct": pct_cur,
            "next_milestone_pct": next_ms,
            "next_milestone_label": f"{next_ms:g}% of network difficulty",
            "milestones_achieved": [
                m for m in PROXIMITY_MILESTONES_PCT if m <= pct_all
            ],
        })

        # LIVE HASH CALCULATOR payload: latest per-share calc + cumulative stats
        try:
            sch = list(state.timeline_state.get("share_calc_history") or [])
            latest = dict(sch[-1]) if sch else None
            ticker = [dict(e) for e in sch[-8:]]  # last 8 for ticker
            session_shares = state.timeline_state.get("session_share_count", 0) or 0
            share_diff_avg = 0.0
            if sch:
                share_diff_avg = sum((e.get("share_diff_raw") or 0) for e in sch) / len(sch)
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
            out["live_calc"] = {
                "latest": latest,
                "ticker": ticker,
                "session_totals": totals,
            }
        except Exception as e:
            log.warning("[compute_proximity live_calc] error: %s", e)

        return out
    except Exception as e:
        log.warning("[compute_proximity] error: %s", e)
        return {**out, "insufficient_data": True, "error": str(e)}
