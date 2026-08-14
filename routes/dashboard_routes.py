"""
CYPHER65 // Dashboard API routes
=================================
Flask Blueprint for monitoring and analytics endpoints.
Fase 6: migrated from app.py — registered in app.py.

Routes served by this blueprint (all under /api):
  /snapshot, /history, /diff_events, /leaderboard, /share_timeline,
  /event_stats, /halving, /mempool_fees, /profitability, /network_share,
  /milestones, /workers, /monte_carlo, /proximity

Alerts (/api/alerts) are owned by routes/alerts_routes.py (alerts_bp).
"""

import json
import random
import time
import logging

from flask import Blueprint, jsonify, request

import config
import services.state as state
from services.db import get_db
from services.licensing import pro_required
from services.snapshot_enrichment import enrich_snapshot
from helpers import fmt_diff

log = logging.getLogger("cypher65.dashboard")

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api")


@dashboard_bp.route("/snapshot")
def api_snapshot():
    """Full dashboard snapshot enriched with market highlights, auto-pilot,
    command center, block-hunt and affiliate links.

    Uses the shared enrich_snapshot() from services/snapshot_enrichment.py —
    identical payload to the previous app.py version (Fase 6 · PR2). The
    axe_registry=None path skips tenant-scoping for unauthenticated access;
    for open self-host mode (default tenant) this preserves the current
    behaviour.
    """
    return jsonify(enrich_snapshot(state.latest_snapshot, axe_registry=None))


@dashboard_bp.route("/history")
def api_history():
    metric = request.args.get("metric", "worker_hashrate")
    rng = request.args.get("range", "24h")
    now = int(time.time())
    span = {
        "15m": 900,
        "1h": 3600,
        "6h": 6 * 3600,
        "24h": 86400,
        "7d": 7 * 86400,
        "30d": 30 * 86400,
        "all": 10**10,
    }.get(rng, 86400)
    since = now - span
    allowed = {
        "worker_hashrate",
        "pool_hashrate",
        "pool_work_since_last_block",
        "account_total_diff",
        "leaderboard_combined_score",
        "network_difficulty",
        "network_hashrate",
        "btc_usd",
        "worker_best_diff",
    }
    if metric not in allowed:
        return jsonify({"error": f"invalid metric {metric}"}), 400
    conn = get_db()
    c = conn.cursor()
    # bandit B608 false positive: metric validated against the allowed set
    # above (line ~73) before reaching the SQL text.
    c.execute(
        f"SELECT ts, {metric} FROM snapshots WHERE ts >= ? AND {metric} IS NOT NULL ORDER BY ts ASC",  # nosec B608
        (since,),
    )
    rows = [{"ts": r["ts"], "value": r[metric]} for r in c.fetchall()]
    conn.close()
    # Contract parity with the pre-migration app.py route: the payload key
    # is "rows" (NOT "history") — preserved so existing clients keep working.
    return jsonify({"metric": metric, "rows": rows, "range": rng})


@dashboard_bp.route("/diff_events")
def api_diff_events():
    only_mine = request.args.get("mine", "0") == "1"
    limit = int(request.args.get("limit", 30))
    conn = get_db()
    c = conn.cursor()
    if only_mine:
        c.execute(
            "SELECT * FROM highest_diff_events WHERE is_mine=1 ORDER BY block_height DESC LIMIT ?",
            (limit,),
        )
    else:
        c.execute(
            "SELECT * FROM highest_diff_events ORDER BY block_height DESC LIMIT ?",
            (limit,),
        )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"events": rows})


@dashboard_bp.route("/leaderboard")
def api_leaderboard():
    top = state.latest_snapshot.get("leaderboard_table_top_30") or []
    enriched = []
    for entry in top:
        if isinstance(entry, dict):
            entry_copy = dict(entry)
            entry_copy["is_me"] = entry_copy.get("address") == (
                state.latest_snapshot.get("address") or config.BTC_ADDRESS
            )
            enriched.append(entry_copy)
    return jsonify(
        {
            "entries": enriched,
            "total": state.latest_snapshot.get("leaderboard_total", len(top)),
            "stale_after_s": config.POLL_INTERVAL,
        }
    )


@dashboard_bp.route("/share_timeline")
def api_share_timeline():
    """Return recent share-timeline events. Newest first."""
    try:
        limit = max(1, min(int(request.args.get("limit", 80)), 500))
        event_type = request.args.get("type")
        conn = get_db()
        c = conn.cursor()
        if event_type:
            c.execute(
                "SELECT * FROM share_timeline WHERE event_type=? ORDER BY id DESC LIMIT ?",
                (event_type, limit),
            )
        else:
            c.execute(
                "SELECT * FROM share_timeline ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        for r in rows:
            try:
                if r.get("meta"):
                    r["meta"] = json.loads(r["meta"])
            except Exception:
                pass
        return jsonify({"events": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e), "events": []}), 500


@dashboard_bp.route("/event_stats")
def api_event_stats():
    snap = dict(state.latest_snapshot.get("event_stats") or {})
    snap["server_now"] = int(time.time())
    snap["poll_age_s"] = (
        snap["server_now"] - (state.latest_snapshot.get("ts") or 0)
        if state.latest_snapshot.get("ts")
        else None
    )
    return jsonify(snap)


@dashboard_bp.route("/halving")
def api_halving():
    return jsonify(state.latest_snapshot.get("halving") or {})


@dashboard_bp.route("/mempool_fees")
def api_mempool_fees():
    return jsonify(state.latest_snapshot.get("mempool_fees") or {})


@dashboard_bp.route("/profitability")
def api_profitability():
    from services.settings import load_settings

    p = dict(state.latest_snapshot.get("profitability") or {})
    p["active_currency"] = load_settings().get("active_currency", "USD")
    return jsonify(p)


@dashboard_bp.route("/network_share")
def api_network_share():
    return jsonify(state.latest_snapshot.get("network_share_gauge") or {})


@dashboard_bp.route("/milestones")
def api_milestones():
    return jsonify({"milestones": state.latest_snapshot.get("milestones") or []})


@dashboard_bp.route("/workers")
def api_workers():
    """Return all workers from the connected wallet's workerData."""
    return jsonify({"workers": state.latest_snapshot.get("all_workers") or []})


@dashboard_bp.route("/monte_carlo")
@pro_required
def api_monte_carlo():
    """Monte Carlo simulation engine.
    Accepts ?hours=N (default 24) and ?runs=N (default 10000).
    Simulates block-finding probability over the specified period using
    the current worker hashrate and network difficulty.
    Returns: distribution of blocks found across N runs, percentiles,
    and key probability stats. All clearly labeled as SIMULATED."""
    hours = request.args.get("hours", 24, type=int)
    runs = request.args.get("runs", 10000, type=int)
    # Clamp params
    hours = max(1, min(hours, 8760))  # 1h .. 1year
    runs = max(100, min(runs, 100000))

    worker = state.latest_snapshot.get("worker") or {}
    net_diff = (state.latest_snapshot.get("network") or {}).get("difficulty")
    cur_hr = float(worker.get("hashrate") or 0)

    if not cur_hr or not net_diff:
        return jsonify({"error": "insufficient data", "status": "SIMULATED"})

    # Expected blocks in period: hashrate / (difficulty * 2^32) * seconds
    hashes_per_block = float(net_diff) * (2**32)
    seconds = hours * 3600.0
    expected_blocks = cur_hr * seconds / hashes_per_block

    # Monte Carlo: Poisson process for block finding
    distribution = [0] * (min(int(expected_blocks * 5) + 5, 5000))
    for _ in range(runs):
        blocks = 0
        t = 0.0
        rate = cur_hr / hashes_per_block  # blocks per second
        while t < seconds:
            t += random.expovariate(rate)
            if t < seconds:
                blocks += 1
        if blocks >= len(distribution):
            distribution.extend([0] * (blocks - len(distribution) + 10))
        distribution[blocks] += 1

    # Compute median and p90
    cum = 0
    median_blocks = 0
    p90_blocks = 0
    for k, count in enumerate(distribution):
        cum += count
        if cum >= runs / 2 and median_blocks == 0 and k > 0:
            median_blocks = k
        if cum >= runs * 0.9 and p90_blocks == 0:
            p90_blocks = k
        if median_blocks and p90_blocks:
            break
    if median_blocks == 0:
        median_blocks = 0
    if p90_blocks == 0:
        p90_blocks = len(distribution) - 1 if distribution else 0

    # Build result
    dist_pct = []
    cumulative = 0.0
    for k, count in enumerate(distribution):
        if count > 0 or k <= int(expected_blocks) + 2:
            pct = round(count / runs * 100, 4)
            cumulative += pct
            dist_pct.append(
                {
                    "blocks": k,
                    "count": count,
                    "pct": pct,
                    "cumulative_pct": round(cumulative, 4),
                    "bar": "█" * max(1, int(pct * 2)),
                }
            )

    p_zero = distribution[0] / runs * 100 if len(distribution) > 0 else 100.0

    return jsonify(
        {
            "status": "SIMULATED",
            "params": {"hours": hours, "runs": runs},
            "inputs": {
                "worker_hashrate_hs": cur_hr,
                "worker_hashrate_ths": round(cur_hr / 1e12, 2),
                "network_difficulty": net_diff,
                "network_difficulty_str": fmt_diff(net_diff),
            },
            "results": {
                "expected_blocks": round(expected_blocks, 6),
                "expected_blocks_str": f"{expected_blocks:.6f}",
                "p_zero_blocks_pct": round(p_zero, 4),
                "p_at_least_one_block_pct": round(100 - p_zero, 4),
                "median_blocks": median_blocks,
                "p90_blocks": p90_blocks,
                "distribution": dist_pct[:20],  # top 20 outcomes
            },
            "disclaimer": "MONTE CARLO SIMULATION — results are statistical estimates based on current hashrate and difficulty. Actual mining outcomes are governed by random chance and may differ significantly.",
        }
    )


@dashboard_bp.route("/proximity")
@pro_required
def api_proximity():
    """Returns the current proximity meter payload PLUS a 24h history slice
    for the front-end mini-chart. History is read from the proximity_history
    DB table (sampled once per minute by poll_once)."""
    base = dict(state.latest_snapshot.get("proximity") or {})
    history_24h = []
    try:
        conn = get_db()
        c = conn.cursor()
        cutoff = int(time.time()) - 86400
        c.execute(
            "SELECT ts, best_diff, all_time_best_diff, network_difficulty, "
            "worker_hashrate, pct_of_network, hot_streak "
            "FROM proximity_history WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,),
        )
        for r in c.fetchall():
            history_24h.append(
                {
                    "ts": r["ts"],
                    "best_diff_raw": r["best_diff"],
                    "all_time_best_diff_raw": r["all_time_best_diff"],
                    "network_difficulty_raw": r["network_difficulty"],
                    "worker_hashrate": r["worker_hashrate"],
                    "pct_of_network": r["pct_of_network"],
                    "hot_streak": bool(r["hot_streak"]),
                }
            )
        conn.close()
    except Exception as e:
        log.warning("[api/proximity history] error: %s", e)
    base["history_24h"] = history_24h
    base["history_count"] = len(history_24h)
    return jsonify(base)
