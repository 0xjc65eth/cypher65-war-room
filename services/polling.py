"""
CYPHER65 // Polling worker  ⚠ LEGACY MODULE ⚠
================================================
**DO NOT USE THIS MODULE IN PRODUCTION.**

The canonical polling path is:
  - `app.py::poll_once()`  (the real poll loop that feeds the dashboard)
  - `services/user_polling.py::_build_snapshot()`  (per-session snapshots)

This file is a HISTORICAL copy extracted from app.py and is imported ONLY
by the test suite (`test_polling_integration.py`, `test_polling.py`,
`test_risk_formulas.py`). It is retained for two reasons:
  1. The pure risk-score helpers `_cv_to_score` / `_pool_cv` / `_solo_cv` /
     `_rental_cv` are unit-tested here (module-level, no I/O).
  2. The legacy `poll_once` integration contract is still covered.

⚠ DRIFT WARNING: the profitability/solo math in `poll_once()` below is a
STALE COPY that has already diverged from the canonical implementation
(e.g. Poisson `1 - e^-λ` here vs `1 - (1-share)^(144·N)` in app.py/helpers.py;
`(btc_usd or 0)` instead of the null-safe guards). **Never** edit the math
here expecting it to affect production — the source of truth is
`app.py` + `helpers.py` (`compute_solo_probabilities`,
`compute_lender_profitability`, `compute_pool_rental_break_even`).
"""

import json
import math
import time
import sqlite3
import collections
import logging
import concurrent.futures

import services.state as state
import services.proximity as proximity
import services.names as names  # name normalization + sanitization

from helpers import (
    parse_diff_to_float,
    fmt_diff,
    fmt_hashrate,
    fmt_uptime,
    fmt_age,
    safe_int,
    safe_num_from_str,
    coerce_float,
    coerce_int,
    human_int,
    human_secs_long,
    isfinite_v,
    make_memory_alert,
    derive_worker_hashrate,
)

log = logging.getLogger("cypher65")

# Config is injected by app.py after import
config = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Risk score helpers (module-level for testability)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _cv_to_score(cv: float) -> int:
    """Normalise a coefficient of variation (CV) to a risk score 1–10.

    Formula: score = clamp(log10(CV) × 3 + 5, 1, 10)

    Parameters
    ----------
    cv : float
        Coefficient of variation (σ/μ). Must be ≥ 0.

    Returns
    -------
    int
        Risk score in [1, 10]. 1 = lowest risk, 10 = highest.

    Examples
    --------
    >>> _cv_to_score(0.01)
    1
    >>> _cv_to_score(0.1)
    2
    >>> _cv_to_score(1.0)
    5
    >>> _cv_to_score(10.0)
    8
    >>> _cv_to_score(100.0)
    10
    >>> _cv_to_score(0.001)
    1
    """
    if cv >= 100:
        return 10
    if cv <= 0.01:
        return 1
    return max(1, min(10, round(math.log10(max(cv, 0.01)) * 3 + 5)))


def _pool_cv(share_of_network: float) -> float:
    """Coefficient of variation for pool mining daily revenue.

    Pool mining is a Poisson process with λ = share_of_network × 144
    (expected blocks per day). For a Poisson, σ = √λ and μ = λ, so
    CV = 1/√λ.

    Parameters
    ----------
    share_of_network : float
        The miner's fraction of total network hashrate.

    Returns
    -------
    float
        Coefficient of variation. Smaller = lower variance.
    """
    λ = max(share_of_network * 144.0, 1e-12)
    return 1.0 / math.sqrt(λ)


def _solo_cv(solo_p_day: float) -> float:
    """Coefficient of variation for solo mining daily revenue.

    Solo mining is a Bernoulli trial per day with P(at least 1 block) = p,
    μ = p, σ = √(p(1-p)), so CV = √((1-p)/p).

    Parameters
    ----------
    solo_p_day : float
        Probability of finding at least one block in a day.

    Returns
    -------
    float
        Coefficient of variation. Extreme for small p.
    """
    if solo_p_day <= 0:
        return 999.0
    return math.sqrt((1 - solo_p_day) / solo_p_day)


def _rental_cv(pool_cv: float) -> float:
    """Coefficient of variation for rental mining daily revenue.

    Approximate as 2× the pool CV to account for rental price
    exposure on top of pool variance.

    Parameters
    ----------
    pool_cv : float
        CV from :func:`_pool_cv` for the same hashrate.

    Returns
    -------
    float
        Coefficient of variation for rental mining.
    """
    return pool_cv * 2.0 if pool_cv else 999.0


def init(cfg):
    """Called by app.py to inject config dependencies."""
    global config
    config = cfg


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Polling worker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def poll_once():
    # state._next_memory_alert_id is mutated only inside _make_memory_alert (which
    # declares its own `global`); no need to redeclare here.

    # ── Guard: skip wallet-specific fetches if no address configured ──
    # When BTC_ADDRESS is empty (no wallet connected), only fetch public data
    # (pool stats, network, BTC price). This prevents continuous 404 noise
    # from stale or empty-address API calls.
    has_wallet = bool(config.BTC_ADDRESS and config.BTC_ADDRESS.strip())
    if not has_wallet:
        # Only log once every 30 polls (~7.5 min) to avoid log spam
        if not hasattr(poll_once, "_no_wallet_log_count"):
            poll_once._no_wallet_log_count = 0
        poll_once._no_wallet_log_count += 1
        if poll_once._no_wallet_log_count % 30 == 1:
            log.info("[poll] No wallet configured — fetching only public data")

    prev_worker = state.latest_snapshot.get("worker") or {}
    prev_pool = state.latest_snapshot.get("pool") or {}

    # ━━ Fetch (parallel) ━━
    # Wallet-specific endpoints are skipped when no address is configured.
    fetch_specs = [
        ("pool", f"{config.PARASITE_API}/pool-stats", 10),
        ("net_height", f"{config.MEMPOOL_API}/blocks/tip/height", 6),
        ("mempool_fee", f"{config.MEMPOOL_API}/v1/fees/recommended", 6),
        (
            "btc",
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,brl,eur,gbp",
            6,
        ),
    ]

    # Only add wallet-specific fetches if we have an address
    if has_wallet:
        fetch_specs.extend(
            [
                ("user", f"{config.PARASITE_API}/user/{config.BTC_ADDRESS}", 10),
                ("account", f"{config.PARASITE_API}/account/{config.BTC_ADDRESS}", 10),
                ("leaderboard", f"{config.PARASITE_API}/leaderboard?limit=30", 10),
                (
                    "highest",
                    f"{config.PARASITE_API}/highest-diff?type=user-diffs&address={config.BTC_ADDRESS}&limit=30",
                    10,
                ),
            ]
        )

    # blockchain.info /q/* endpoints return PLAIN TEXT (not JSON), so they
    # live in a separate text-fetch fan-out below. mempool.space /v1/difficulty
    # has been deprecated (~Oct 2024) and returns 404; blockchain.info is the
    # most reliable public source for current_difficulty + network hashrate as
    # of late 2024 / 2025 / 2026.
    bc_specs = [
        ("bc_diff", "https://blockchain.info/q/getdifficulty", 8),
        ("bc_hashrate", "https://blockchain.info/q/hashrate", 8),
    ]
    bc_results = {key: None for key, _, _ in bc_specs}

    results = {key: None for key, _, _ in fetch_specs}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_key = {
            executor.submit(config.fetch_json, url, timeout): key
            for key, url, timeout in fetch_specs
        }
        # No outer timeout: each fetch_json belongs to a request with its own
        # per-endpoint timeout (≤10s). Worst-case poll wall = max(latencies),
        # well below config.POLL_INTERVAL=15s. As_completed(timeout=None) prevents the
        # secondary wait-for-shutdown blowout flagged by the code reviewer.
        for fut in concurrent.futures.as_completed(future_to_key):
            key = future_to_key[fut]
            try:
                results[key] = fut.result()
            except Exception as e:
                log.warning("[pool] future %s raised: %s", key, e)
                results[key] = None

    # ━━ Blockchain.info /q/* fallback fan-out (plain-text responses) ━━
    # blockchain.info endpoints return raw text like "154824667684575552"
    # instead of JSON, so they go through fetch_text instead of fetch_json.
    # Keeps wall-clock ~max(latency): both calls in parallel.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as bc_executor:
        bc_futures = {
            bc_executor.submit(config.fetch_text, url, timeout): key
            for key, url, timeout in bc_specs
        }
        for fut in concurrent.futures.as_completed(bc_futures):
            key = bc_futures[fut]
            try:
                bc_results[key] = fut.result()
            except Exception as e:
                log.warning("[pool] bc text future %s raised: %s", key, e)
                bc_results[key] = None

    user = results.get("user")
    pool = results["pool"]

    # ── FASE 1 FIX: Pool API failure fallback ──
    # When the pool-stats endpoint fails (timeout, 5xx, rate limit),
    # pool arrives as None. Fall back to prev_pool with a _stale flag
    # so the frontend shows stale-but-valid data instead of a blank panel.
    if not isinstance(pool, dict) and isinstance(prev_pool, dict) and prev_pool:
        pool = dict(prev_pool)
        pool["_stale"] = True
        pool["_stale_since_ts"] = int(time.time())

    account_data = results.get("account")
    leaderboard = results.get("leaderboard") or []
    highest = results.get("highest") or []

    # ── Wallet-not-found rate-limited warning ──
    # When a wallet address is configured but the pool returns no worker data
    # (either 404 or empty user object), warn once then suppress for 60 polls
    # (~15 min) to prevent log flooding. The warning re-fires after the cooldown.
    if has_wallet and user is None:
        if not hasattr(poll_once, "_wallet_404_count"):
            poll_once._wallet_404_count = 0
        poll_once._wallet_404_count += 1
        if poll_once._wallet_404_count == 1 or poll_once._wallet_404_count % 60 == 0:
            addr_short = (
                config.BTC_ADDRESS[:10] + "…" + config.BTC_ADDRESS[-6:]
                if len(config.BTC_ADDRESS) > 16
                else config.BTC_ADDRESS
            )
            log.warning(
                "[poll] Wallet %s not found on pool (poll #%d). Suppressing further warnings for ~15 min.",
                addr_short,
                poll_once._wallet_404_count,
            )
    elif has_wallet and user is not None:
        # Reset counter when wallet data returns successfully
        if hasattr(poll_once, "_wallet_404_count"):
            poll_once._wallet_404_count = 0

    # Network (mempool.space) — /v1/difficulty is preferred; fall back to
    # /v1/difficulty-adjustment embedded value, then to blockchain.info
    # /q/* endpoints (which return plain text integers and are still online).
    # Finally, if current_difficulty is known but net_hashrate isn't, compute
    # it from the canonical Bitcoin formula: hashrate = difficulty * 2^32 / 600.
    network_height_data = results["net_height"]
    # blockchain.info is the primary source for difficulty + hashrate (mempool.space
    # /v1/difficulty was deprecated Oct 2024 and always returns 404).
    bc_diff_val = safe_num_from_str(bc_results.get("bc_diff"))
    bc_hashrate_val = safe_num_from_str(bc_results.get("bc_hashrate"))
    if bc_hashrate_val is not None:
        # blockchain.info /q/hashrate returned TH/s historically, but as of
        # 2025-2026 it returns GH/s. Multiply by 1e9 to get H/s.
        net_hashrate = float(bc_hashrate_val) * 1e9
    else:
        net_hashrate = None
    network_height = (
        network_height_data if isinstance(network_height_data, int) else None
    )
    # Difficulty: use blockchain.info /q/getdifficulty as primary source
    current_difficulty = float(bc_diff_val) if bc_diff_val is not None else None
    # Safety: if difficulty is zero/negative after all fallbacks, use default (126.23T)
    # and emit a warning so operators know the API returned bad data.
    DEFAULT_DIFFICULTY = 126231507121868.0  # ~126.23T — typical late-2025 value
    if current_difficulty is not None and current_difficulty <= 0:
        log.warning(
            "[poll] network difficulty is %.4e (invalid) — falling back to default %.4e",
            current_difficulty,
            DEFAULT_DIFFICULTY,
        )
        current_difficulty = DEFAULT_DIFFICULTY
    # Fallback: derive net_hashrate from difficulty + target block time
    if current_difficulty is not None and (net_hashrate is None or net_hashrate == 0):
        net_hashrate = current_difficulty * (2**32) / 600

    # BTC price (CoinGecko) — com cache de 5 min para evitar 429 rate limit
    _now = int(time.time())
    btc_quote = results["btc"]
    # Se a API retornou dados, atualiza o cache
    if isinstance(btc_quote, dict) and btc_quote.get("bitcoin"):
        state.btc_price_cache["data"] = btc_quote
        state.btc_price_cache["ts"] = _now
    # Se falhou (429 etc), usa cache se ainda válido (< 5 min)
    elif (
        _now - state.btc_price_cache["ts"] < state.BTC_PRICE_CACHE_TTL
        and state.btc_price_cache["data"]
    ):
        btc_quote = state.btc_price_cache["data"]
    else:
        btc_quote = None
    btc_usd = (
        (btc_quote or {}).get("bitcoin", {}).get("usd")
        if isinstance(btc_quote, dict)
        else None
    )
    btc_brl = (
        (btc_quote or {}).get("bitcoin", {}).get("brl")
        if isinstance(btc_quote, dict)
        else None
    )
    btc_eur = (
        (btc_quote or {}).get("bitcoin", {}).get("eur")
        if isinstance(btc_quote, dict)
        else None
    )
    btc_gbp = (
        (btc_quote or {}).get("bitcoin", {}).get("gbp")
        if isinstance(btc_quote, dict)
        else None
    )

    # Mempool fees (sat/vB) — for "what fee should I include if I want fast"
    mf_raw = results["mempool_fee"]
    mempool_fees = {}
    if isinstance(mf_raw, dict):
        for k in ("fastestFee", "halfHourFee", "hourFee", "minimumFee", "economyFee"):
            v = mf_raw.get(k)
            if isinstance(v, (int, float)):
                mempool_fees[k] = v
    if not mempool_fees:
        mempool_fees = {"fastestFee": None, "halfHourFee": None, "hourFee": None}

    # ━━ Halving countdown ──
    # Blockchain-based: halvings every 210,000 blocks. Uses rolling avg block
    # time from the last 144 blocks (∼24h) when available, falls back to 600s.
    halving = {
        "height": network_height,
        "blocks_remaining": None,
        "estimated_seconds_remaining": None,
        "next_reward_btc": None,
        "epoch_label": "",
    }
    # Compute rolling average block time from recent snapshots
    rolling_avg_block_time_s = 600.0
    if isinstance(network_height, int):
        try:
            conn = config.get_db()
            c = conn.cursor()
            c.execute(
                "SELECT ts, network_height FROM snapshots WHERE network_height IS NOT NULL "
                "ORDER BY ts DESC LIMIT 2"
            )
            rows = c.fetchall()
            conn.close()
            if len(rows) >= 2:
                # Heights and timestamps from two polls
                h1, h2 = rows[0]["network_height"], rows[1]["network_height"]
                t1, t2 = rows[0]["ts"], rows[1]["ts"]
                if h2 > h1 and t2 > t1:
                    # Block height increase per second → extrapolate to seconds per block
                    blocks_per_sec = (h2 - h1) / (t2 - t1)
                    if blocks_per_sec > 0:
                        rolling_avg_block_time_s = 1.0 / blocks_per_sec
                    # Clamp to realistic range (300s-3600s)
                    rolling_avg_block_time_s = max(
                        300.0, min(3600.0, rolling_avg_block_time_s)
                    )
        except Exception:
            pass

        next_halving_h = ((network_height // 210000) + 1) * 210000
        blocks_left = max(0, next_halving_h - network_height)
        secs_left = blocks_left * rolling_avg_block_time_s
        epoch_idx = (next_halving_h // 210000) - 1
        cur_reward = 50.0 * (0.5**epoch_idx) if epoch_idx >= 0 else 50.0
        next_reward = cur_reward * 0.5
        halving = {
            "next_height": next_halving_h,
            "current_height": network_height,
            "blocks_remaining": blocks_left,
            "estimated_seconds_remaining": secs_left,
            "estimated_days_remaining": secs_left / 86400.0,
            "current_reward_btc": cur_reward,
            "next_reward_btc": next_reward,
            "epoch_label": f"#{epoch_idx + 1}/33",
            "pct_complete": round((network_height % 210000) / 210000.0 * 100, 2),
            "avg_block_time_s": round(rolling_avg_block_time_s, 1),
        }

    # ━━ Also capture ALL workers from workerData for the All Workers panel ━━
    all_workers = []
    worker = None
    worker_index = None
    # Track best worker candidate for dynamic primary selection
    best_candidate = None
    best_score = -1
    session_shares = state.timeline_state.get("session_share_count", 0)
    session_bumps = state.timeline_state.get("session_best_diff_bumps", 0)
    if user and isinstance(user.get("workerData"), list):
        for idx, w in enumerate(user["workerData"]):
            # Estimate rejection rate from share submission deltas
            # If pool saw fewer best-diff bumps than shares submitted, some shares may be rejected/stale
            wr_best = w.get("bestDifficulty", "")
            wr_best_val = (
                parse_diff_to_float(wr_best)
                if isinstance(wr_best, str)
                else float(wr_best or 0)
            )
            wr_uptime = w.get("uptime", 0) or 0
            wr_last_sub = w.get("lastSubmission")
            wr_now = int(time.time())
            last_share_ago = (wr_now - int(wr_last_sub)) if wr_last_sub else None
            # Dynamic primary scoring: hashrate (TH/s) + recency bonus
            # Score = hashrate_THs + (3600 / max(last_share_ago_s, 60))
            # Workers with hashrate > 0 AND recent submissions score highest
            wr_hr = float(w.get("hashrate") or 0)
            wr_hr_ths = wr_hr / 1e12
            recency_bonus = 0.0
            if last_share_ago is not None and last_share_ago > 0:
                recency_bonus = 3600.0 / max(last_share_ago, 60)
            score = wr_hr_ths + recency_bonus
            if score > best_score:
                best_score = score
                best_candidate = (idx, w)
            # Rejection rate estimate: if few bumps vs session shares, some % are stale/rejected
            rejection_pct = None
            if session_shares > 10 and session_bumps >= 0:
                rejection_pct = round(
                    (1 - session_bumps / max(session_shares, 1)) * 100, 1
                )
            # Average hashrate from share history (if available)
            avg_hr = float(w.get("hashrate") or 0)
            hist = state.timeline_state.get("share_submit_history", [])
            if len(hist) >= 2 and (hist[-1] - hist[0]) > 0:
                span = hist[-1] - hist[0]
                sph = (len(hist) - 1) * (3600.0 / span)
            else:
                sph = 0.0
            clean_name = names.sanitize(str(w.get("name", "") or ""))
            clean_id = names.sanitize(str(w.get("id", "") or ""))
            entry = {
                "id": clean_id,
                "name": clean_name,
                "hashrate": w.get("hashrate"),
                "bestDifficulty": wr_best,
                "bestDifficultyVal": wr_best_val,
                "lastSubmission": wr_last_sub,
                "uptime": wr_uptime,
                "is_primary": False,  # Set dynamically below after scoring all workers
                # Deep metrics
                "rejectionRatePct": rejection_pct,
                "rejectionRateLabel": (
                    f"{rejection_pct}%" if rejection_pct is not None else "—"
                ),
                "temperature": "NOT AVAILABLE",
                "temperatureLabel": "NOT AVAILABLE",
                "powerWatts": "NOT AVAILABLE",
                "powerWattsLabel": "NOT AVAILABLE",
                "fanSpeed": "NOT AVAILABLE",
                "fanSpeedLabel": "NOT AVAILABLE",
                "hardwareErrors": "NOT AVAILABLE",
                "hardwareErrorsLabel": "NOT AVAILABLE",
                "lastShareAgo": last_share_ago,
                "lastShareAgoLabel": fmt_age(wr_last_sub) if wr_last_sub else "—",
                "sharesPerHour": round(sph, 1),
                "avgHashrateHps": avg_hr,
                "avgHashrateLabel": fmt_hashrate(avg_hr) if avg_hr else "—",
                "state": (
                    "HASHING"
                    if w.get("hashrate")
                    else ("ONLINE" if wr_last_sub else "IDLE")
                ),
            }
            all_workers.append(entry)

        # ── Dedup workers by normalized name ──
    # Workers with the same normalized name (e.g. CYPHERORDIFUTURE vs cypherordifuture)
    # are merged: keep the entry with highest hashrate (most recent/active).
    seen = {}
    deduped = []
    for entry in all_workers:
        key = names.dedup_key(entry.get("name", "")) or names.dedup_key(
            entry.get("id", "")
        )
        if not key:
            deduped.append(entry)
            continue
        existing = seen.get(key)
        if existing is None:
            seen[key] = entry
            deduped.append(entry)
        else:
            # Merge: keep the one with higher hashrate (active beats dead)
            existing_hr = float(existing.get("hashrate") or 0)
            incoming_hr = float(entry.get("hashrate") or 0)
            if incoming_hr > existing_hr:
                # Replace the existing entry with the incoming one
                deduped[deduped.index(existing)] = entry
                seen[key] = entry
                log.info(
                    "[dedup] Merged worker '%s' into '%s' (hashrate %.0f > %.0f)",
                    entry.get("name", "?"),
                    existing.get("name", "?"),
                    incoming_hr,
                    existing_hr,
                )
    if len(deduped) < len(all_workers):
        log.info(
            "[dedup] Reduced %d workers → %d by normalized name merging",
            len(all_workers),
            len(deduped),
        )
        all_workers = deduped

    # ── Dynamic primary worker selection ──
    # After scoring all workers, mark the best candidate as primary.
    # Falls back to WORKER_NAME match if no worker has hashrate or recency.
    if best_candidate is not None:
        best_idx, best_w = best_candidate
        all_workers[best_idx]["is_primary"] = True
        worker = best_w
        worker_index = best_idx
    elif all_workers:
        # Fallback: match by WORKER_NAME (static, for empty wallets)
        for idx, entry in enumerate(all_workers):
            normalized_worker_name = names.normalize(config.WORKER_NAME)
            if (
                names.normalize(entry.get("name", "")) == normalized_worker_name
                or names.normalize(entry.get("id", "")) == normalized_worker_name
            ):
                entry["is_primary"] = True
                worker = (
                    user["workerData"][idx]
                    if idx < len(user.get("workerData", []))
                    else None
                )
                worker_index = idx
                break

    # ── FASE 1 FIX: Worker API failure fallback ──
    # When the user/wallet endpoint fails, worker is None.
    # Fall back to prev_worker with a _stale flag so the frontend
    # shows stale-but-valid data instead of blank panels.
    if worker is None and isinstance(prev_worker, dict) and prev_worker.get("name"):
        worker = dict(prev_worker)
        worker["_stale"] = True
        worker["_stale_since_ts"] = int(time.time())

    # ── DIAGNOSTIC: Worker null despite all_workers having entries ──
    # If worker is still None but all_workers has entries, log a warning
    # and use the first available worker as the primary. This prevents the
    # frontend from showing blank panels when the scoring/match fails.
    if worker is None and all_workers:
        log.warning(
            "[poll] Worker is None but all_workers has %d entries — falling back to first worker: %s",
            len(all_workers),
            all_workers[0].get("name", "?"),
        )
        # Use the first worker as primary fallback
        all_workers[0]["is_primary"] = True
        idx = 0
        # Try to get the raw worker data from the API response
        if (
            user
            and isinstance(user.get("workerData"), list)
            and idx < len(user["workerData"])
        ):
            worker = user["workerData"][idx]
        else:
            # Fall back to the enriched all_workers entry as a dict
            worker = dict(all_workers[0])
        worker_index = idx

    # ── Override user_aggregate.workers with our own count ──
    # The pool API may report workers=0 even when workerData has entries.
    # Count workers with hashrate > 0 as the real active count.
    if isinstance(user, dict):
        wd = user.get("workerData") or []
        active_count = sum(
            1
            for w in wd
            if isinstance(w, dict) and coerce_float(w.get("hashrate"), 0) > 0
        )
        user["workers"] = active_count

    # ━━ Leaderboard lookup ━━
    leaderboard_entry = None
    for entry in leaderboard:
        if entry.get("address") == config.BTC_ADDRESS:
            leaderboard_entry = entry
            break

    # Also fallback: search case-insensitive / substr
    if not leaderboard_entry:
        addr_short = config.BTC_ADDRESS[-8:].lower()
        for entry in leaderboard:
            if addr_short in str(entry.get("address", "")).lower():
                leaderboard_entry = entry
                break  # ━━ Account unpack ━━
    account = account_data.get("account") if isinstance(account_data, dict) else None
    lightning = (
        account_data.get("lightning") if isinstance(account_data, dict) else None
    )
    meta = account.get("metadata", {}) if isinstance(account, dict) else {}

    # Merge leaderboard data into account so frontend doesn't need two objects
    if isinstance(account, dict) and leaderboard_entry:
        account["diffRank"] = leaderboard_entry.get("diff_rank")
        account["loyaltyRank"] = leaderboard_entry.get("loyalty_rank")
        account["combinedScore"] = leaderboard_entry.get("combined_score")
        account["blocksFound"] = meta.get("block_count") or leaderboard_entry.get(
            "blocks_found"
        )
        account["highestBlock"] = meta.get("highest_blockheight")
        # Ensure key aliases exist for frontend
        if (
            account.get("total_diff") is not None
            and account.get("totalDifficulty") is None
        ):
            account["totalDifficulty"] = account["total_diff"]

    ts = int(time.time())

    # ━━ Share timeline delta detection ━━
    # Every real share submitted by the worker changes worker.lastSubmission.
    # Every new best share changes worker.bestDifficulty.
    # We track deltas across polls as proxy "share events" — the closest
    # signal the public API gives us to per-share logs.
    timeline_events = []

    # FIRST-POLL GUARD: the very first poll after process start captures the
    # current observed values as "baseline" without emitting fake SHARE_FOUND /
    # BEST_DIFF_BUMP events. Subsequent polls fire only on real deltas.
    if not state.timeline_state.get("_primed"):
        if worker:
            try:
                ls_int = int(worker.get("lastSubmission") or 0)
            except Exception:
                ls_int = 0
            state.timeline_state["last_submit_ts"] = ls_int or 0
            state.timeline_state["last_best_diff_str"] = (
                worker.get("bestDifficulty") or ""
            )
            # seed the rolling share-rate history so sph is meaningful from poll 2
            if ls_int:
                state.timeline_state["share_submit_history"].append(ls_int)
        state.timeline_state["_primed"] = True
        fresh_bump_detected = False
    else:
        fresh_bump_detected = False
        if worker:
            ls = worker.get("lastSubmission")
            try:
                ls_int = int(ls) if ls else 0
            except Exception:
                ls_int = 0
            if ls_int and ls_int != state.timeline_state["last_submit_ts"]:
                gap = (
                    (ls_int - state.timeline_state["last_submit_ts"])
                    if state.timeline_state["last_submit_ts"]
                    else 0
                )
                state.timeline_state["last_submit_ts"] = ls_int
                state.timeline_state["share_submit_history"].append(ls_int)
                state.timeline_state["session_share_count"] += 1
                sph = 0.0
                hist = state.timeline_state["share_submit_history"]
                if len(hist) >= 2:
                    span = hist[-1] - hist[0]
                    if span > 0:
                        sph = (len(hist) - 1) * (3600.0 / span)
                timeline_events.append(
                    (
                        ts,
                        "SHARE_FOUND",
                        "INFO",
                        f"{(config.WORKER_NAME or 'worker').upper()} share validated by pool (gap Δ{gap}s)",
                        json.dumps({"gap": gap, "shares_per_hour": round(sph, 2)}),
                    )
                )

                # Per-share LIVE HASH CALCULATOR: compute the math that the
                # dashboard exposes in real time (see also live_calc payload
                # in _compute_proximity for cumulative stats).
                #
                # parasite.space exposes worker.difficulty (current vardiff
                # target). When that's missing, fall back to best_diff / 2
                # (vardiff typically doubles after every accepted share).
                share_diff_raw = 0.0
                try:
                    d = worker.get("difficulty")
                    if isinstance(d, (int, float)) and d > 0:
                        share_diff_raw = float(d)
                    elif isinstance(d, str) and d:
                        share_diff_raw = parse_diff_to_float(d)
                    if not share_diff_raw and worker.get("bestDifficulty"):
                        share_diff_raw = (
                            parse_diff_to_float(worker.get("bestDifficulty")) / 2.0
                        )
                except Exception:
                    share_diff_raw = 0.0
                if share_diff_raw and current_difficulty and gap and gap > 0:
                    hashes_attempted = share_diff_raw * (2**32)
                    p_block_this = share_diff_raw / float(current_difficulty)
                    inst_hr_hps = hashes_attempted / float(gap)
                    # Determine source: CALCULATED when worker.difficulty is available,
                    # ESTIMATED when falling back to bestDifficulty/2
                    _share_source = "CALCULATED"
                    d = worker.get("difficulty")
                    if not (isinstance(d, (int, float)) and d > 0) and not (
                        isinstance(d, str) and d
                    ):
                        _share_source = "ESTIMATED"
                    share_calc = {
                        "ts": ts,
                        "gap": gap,
                        "share_diff_raw": share_diff_raw,
                        "share_diff_str": fmt_diff(share_diff_raw),
                        "hashes_attempted": hashes_attempted,
                        "hashes_attempted_str": f"{hashes_attempted:.3e}",
                        "source": _share_source,
                        "p_block_this_share": p_block_this,
                        "p_block_this_share_pct_str": (
                            f"{p_block_this * 100:.4e}%"
                            if p_block_this < 0.01
                            else f"{p_block_this * 100:.4f}%"
                        ),
                        "instantaneous_hr_hps": inst_hr_hps,
                        "instantaneous_hr_str": fmt_hashrate(inst_hr_hps),
                        "best_diff_at_time": (
                            parse_diff_to_float(worker.get("bestDifficulty"))
                            if worker and worker.get("bestDifficulty")
                            else 0.0
                        ),
                        "best_diff_at_time_str": (
                            worker.get("bestDifficulty") if worker else ""
                        ),
                        "network_diff_at_time": current_difficulty,
                        "network_diff_at_time_str": fmt_diff(current_difficulty),
                        "session_share_count_at_time": state.timeline_state[
                            "session_share_count"
                        ],
                    }
                    state.timeline_state["share_calc_history"].append(share_calc)

            best_diff_str = worker.get("bestDifficulty") or ""
            if (
                best_diff_str
                and best_diff_str != state.timeline_state["last_best_diff_str"]
            ):
                # IMPORTANT: capture old strings/values BEFORE mutating state,
                # so meta payload reports the true "from→to" transition.
                old_str = state.timeline_state["last_best_diff_str"]
                old_val = parse_diff_to_float(old_str)
                new_val = parse_diff_to_float(best_diff_str)
                pct = ((new_val - old_val) / old_val * 100) if old_val else 0.0
                state.timeline_state["last_best_diff_str"] = best_diff_str
                state.timeline_state["session_best_diff_bumps"] += 1
                fresh_bump_detected = True
                pct_txt = f"+{pct:.1f}%" if pct else "first"
                timeline_events.append(
                    (
                        ts,
                        "BEST_DIFF_BUMP",
                        "GOLD",
                        f"{(config.WORKER_NAME or 'worker').upper()} best difficulty raised to {best_diff_str} ({pct_txt})",
                        json.dumps(
                            {
                                "from": old_str or "0",
                                "to": best_diff_str,
                                "pct": round(pct, 2),
                            }
                        ),
                    )
                )

    if pool:
        cur_wslb = pool.get("workSinceLastBlock") or 0
        if prev_pool and prev_pool.get("workSinceLastBlock") is not None and cur_wslb:
            cur_wslb_f = float(cur_wslb)
            prev_wslb_f = float(prev_pool.get("workSinceLastBlock") or 0)
            wslb_delta = cur_wslb_f - prev_wslb_f
            # if pool accumulated more than 1e10 share-diff worth of work since last poll,
            # surface it as a WORK_DELTA milestone
            if abs(wslb_delta) > 1e10:
                timeline_events.append(
                    (
                        ts,
                        "WORK_DELTA",
                        "INFO",
                        f"Pool accumulated +{fmt_diff(wslb_delta)} work since last poll ({fmt_diff(cur_wslb_f)} total)",
                        json.dumps({"delta": wslb_delta, "total": cur_wslb_f}),
                    )
                )

    # ━━ FENIX E1 (P1): derive worker hashrate when the pool reports 0 ━━
    # Same contract as app.py:_do_poll — the public API sometimes reports
    # worker hashrate as 0 even while shares flow. Fall back to the per-share
    # instantaneous hashrate math (share_calc_history) or the pool
    # workSinceLastBlock delta, and write the derived value into the worker
    # dict so the snapshot row, /api/snapshot worker payload, KPI cards and
    # proximity meter all show a real number instead of 0/—.
    if worker:
        _reported_hr = float(worker.get("hashrate") or 0)
        if _reported_hr <= 0:
            _prev_ts = (
                state.latest_snapshot.get("ts")
                if isinstance(state.latest_snapshot, dict)
                else 0
            )
            _elapsed_s = (ts - _prev_ts) if _prev_ts else float(config.POLL_INTERVAL)
            _derived_hr, _hr_source = derive_worker_hashrate(
                share_calc_history=state.timeline_state.get("share_calc_history") or [],
                prev_pool=prev_pool,
                pool=pool,
                elapsed_s=_elapsed_s,
            )
            if _derived_hr > 0:
                worker["hashrate"] = _derived_hr
                worker["hashrate_source"] = _hr_source
                worker["hashrate_derived"] = True
                # mirror into the fleet panel's primary worker entry — match by
                # the is_primary flag (robust to dedup index shifts)
                for _entry in all_workers:
                    if _entry.get("is_primary"):
                        _entry["hashrate"] = _derived_hr
                        _entry["hashrate_source"] = _hr_source
                        break
                log.info(
                    "[poll] worker %s hashrate derived from %s: %s H/s (pool reported 0)",
                    worker.get("name") or "?",
                    _hr_source,
                    fmt_hashrate(_derived_hr),
                )

    # ━━ Persist snapshot ━━
    try:
        conn = config.get_db()
        c = conn.cursor()
        c.execute(
            """INSERT INTO snapshots
            (ts, worker_hashrate, worker_best_diff, worker_last_submit, worker_uptime, worker_status,
             pool_hashrate, pool_workers, pool_users, pool_highest_diff, pool_last_block_height,
             pool_last_block_time, pool_work_since_last_block,
             account_total_diff, account_block_count, account_highest_block,
             leaderboard_rank, leaderboard_diff_rank, leaderboard_loyalty_rank, leaderboard_combined_score,
             network_height, network_difficulty, network_hashrate,
             btc_usd, btc_brl)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ts,
                worker.get("hashrate") if worker else None,
                worker.get("bestDifficulty") if worker else None,
                worker.get("lastSubmission") if worker else None,
                worker.get("uptime") if worker else None,
                "online" if worker else "missing",
                pool.get("hashrate") if pool else None,
                pool.get("workers") if pool else None,
                pool.get("users") if pool else None,
                pool.get("highestDifficulty") if pool else None,
                pool.get("lastBlockHeight") if pool else None,
                pool.get("lastBlockTime") if pool else None,
                pool.get("workSinceLastBlock") if pool else None,
                account.get("total_diff") if isinstance(account, dict) else None,
                meta.get("block_count") if isinstance(meta, dict) else None,
                meta.get("highest_blockheight") if isinstance(meta, dict) else None,
                (
                    (leaderboard.index(leaderboard_entry) + 1)
                    if leaderboard_entry
                    else None
                ),
                leaderboard_entry.get("diff_rank") if leaderboard_entry else None,
                leaderboard_entry.get("loyalty_rank") if leaderboard_entry else None,
                leaderboard_entry.get("combined_score") if leaderboard_entry else None,
                network_height,
                current_difficulty,
                net_hashrate,
                btc_usd,
                btc_brl,
            ),
        )

        # ━━ High-diff events ━━
        if isinstance(highest, list):
            for ev in highest[:30]:
                bh = ev.get("block_height")
                c.execute(
                    "SELECT 1 FROM highest_diff_events WHERE block_height=?", (bh,)
                )
                if not c.fetchone():
                    top_addr = ev.get("top_diff_address") or ev.get("address") or ""
                    is_mine = config.BTC_ADDRESS in top_addr
                    c.execute(
                        """INSERT INTO highest_diff_events
                        (ts, block_height, top_diff_address, difficulty, claimed, block_timestamp, is_mine)
                        VALUES (?,?,?,?,?,?,?)""",
                        (
                            ts,
                            bh,
                            top_addr,
                            str(ev.get("difficulty", "")),
                            1 if ev.get("claimed") else 0,
                            ev.get("block_timestamp"),
                            1 if is_mine else 0,
                        ),
                    )

        # ━━ Share timeline events ━━
        for ev in timeline_events:
            try:
                c.execute(
                    """INSERT INTO share_timeline
                    (ts, event_type, severity, message, meta) VALUES (?,?,?,?,?)""",
                    ev,
                )
            except Exception as e:
                log.warning("[share_timeline insert] error: %s", e)
        conn.commit()
        # ── Persist succeeded → clear failure state, surface SUCCESS alert ──
        if state.persist_consec_failures > 0:
            state.memory_critical_alerts.append(
                config.make_memory_alert(
                    ts,
                    "SUCCESS",
                    "disk_write_recovered",
                    f"SQLite writes recovered after {state.persist_consec_failures} consecutive "
                    f"poll failures; history persistence restored.",
                )
            )
            state.persist_consec_failures = 0
    except Exception as e:
        log.error("[persist] error: %s", e)
        state.persist_consec_failures += 1
        # Escalate at ladder steps so we don't flood the alerts panel.
        if state.persist_consec_failures in state.PERSIST_FAILURE_LADDER:
            degraded_s = state.persist_consec_failures * config.POLL_INTERVAL
            state.memory_critical_alerts.append(
                config.make_memory_alert(
                    ts,
                    "CRIT",
                    "disk_write_failure",
                    f"SQLite write failing — {state.persist_consec_failures} consecutive poll "
                    f"failures (~{degraded_s}s degraded). Live UI continues; "
                    f"history persistence OFF until disk recovers.",
                )
            )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # ── Anomaly detection ──
    settings_s = config.load_settings()
    stale_min = coerce_int(settings_s.get("stale_share_minutes"), 5)
    hr_drop_pct = coerce_float(settings_s.get("hashrate_drop_pct"), 50.0)
    alerts = []

    # ── Alert deduplication ──
    # Track event signatures across polls so the same "pool new high diff 87.1T"
    # never fires twice. Signature = (category, identifier) where identifier is
    # the unique value (block_hash, highest_diff_str, etc.)
    if not hasattr(poll_once, "_alert_seen"):
        poll_once._alert_seen = (
            set()
        )  # set of (category, identifier) seen across restarts
    alert_seen = poll_once._alert_seen

    if worker:
        ls = worker.get("lastSubmission")
        if ls and (ts - int(ls)) > stale_min * 60:
            sev = "WARN" if (ts - int(ls)) <= stale_min * 120 else "CRIT"
            sig = ("stale_submission", str(ls))
            if sig not in alert_seen:
                alerts.append(
                    (
                        sev,
                        "stale_submission",
                        f"{(config.WORKER_NAME or 'worker').upper()} last submit {int((ts - int(ls)) / 60)}min ago (threshold {stale_min}m)",
                    )
                )
                alert_seen.add(sig)
        prev_hr = float(prev_worker.get("hashrate") or 0)
        cur_hr = float(worker.get("hashrate") or 0)
        if prev_hr > 0 and cur_hr < (1 - hr_drop_pct / 100.0) * prev_hr:
            sig = ("hashrate_drop", f"{prev_hr:.0f}->{cur_hr:.0f}")
            if sig not in alert_seen:
                alerts.append(
                    (
                        "WARN",
                        "hashrate_drop",
                        f"{(config.WORKER_NAME or 'worker').upper()} hashrate dropped from {fmt_hashrate(prev_hr)} to {fmt_hashrate(cur_hr)} (-{hr_drop_pct:.0f}%)",
                    )
                )
                alert_seen.add(sig)
    else:
        sig = ("worker_offline", "1")
        if sig not in alert_seen:
            alerts.append(
                (
                    "CRIT",
                    "worker_offline",
                    f"{(config.WORKER_NAME or 'worker').upper()} not found in workerData",
                )
            )
            alert_seen.add(sig)

    if pool:
        cur_high = str(pool.get("highestDifficulty") or "")
        if cur_high and cur_high != str(prev_pool.get("highestDifficulty") or ""):
            sig = ("new_high_diff", cur_high)
            if sig not in alert_seen:
                alerts.append(
                    ("GOLD", "new_high_diff", f"Pool new highest diff: {cur_high}")
                )
                alert_seen.add(sig)
        cur_block_hash = str(pool.get("lastBlockHash") or "")
        prev_block_hash = str(prev_pool.get("lastBlockHash") or "")
        if cur_block_hash and cur_block_hash != prev_block_hash:
            sig = ("new_block", cur_block_hash)
            if sig not in alert_seen:
                alerts.append(
                    ("GOLD", "new_block", f"Pool found block: {cur_block_hash[:16]}…")
                )
                alert_seen.add(sig)

    # dedication / continuity - only fire once per uptime milestone
    if worker and isinstance(worker.get("uptime"), int):
        up = worker["uptime"]
        if up > 0 and up % 86400 < 90:  # crossed the day boundary
            day_num = up // 86400
            sig = ("uptime_milestone", str(day_num))
            if sig not in alert_seen:
                alerts.append(
                    (
                        "INFO",
                        "uptime",
                        f"{(config.WORKER_NAME or 'worker').upper()} uptime crossed {fmt_uptime(up)}",
                    )
                )
                alert_seen.add(sig)

    # GC old signatures (keep last 1000)
    if len(alert_seen) > 1000:
        poll_once._alert_seen = set(list(alert_seen)[-500:])

    if alerts:
        try:
            conn = config.get_db()
            c = conn.cursor()
            for sev, cat, msg in alerts:
                c.execute(
                    "INSERT INTO alerts (ts, severity, category, message) VALUES (?,?,?,?)",
                    (ts, sev, cat, msg),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("[alert persist] error: %s", e)

    # ━━ Webhook fire (Discord/Telegram) via shared notify helper ━━
    # Phase D: deduplicated — uses the same severity-thresholded notifier the
    # AlertEngine calls through its webhook_callback (single source of truth
    # for the severity ranking, in services.push_notifier).
    try:
        from services.push_notifier import send_webhook_for_alert as _send_wh

        s = settings_s
        url = (s.get("webhook_url") or "").strip()
        if url:
            min_sev = s.get("webhook_min_severity", "WARN")
            for sev, cat, msg in alerts:
                _send_wh(
                    url=url,
                    severity=sev,
                    category=cat,
                    message=msg,
                    ts=ts,
                    worker=config.WORKER_NAME,
                    address=config.BTC_ADDRESS,
                    min_severity=min_sev,
                )
    except Exception as e:
        log.warning("[webhook block] error: %s", e)

    # ━━ Compute luck estimate ━━
    luck = {}
    if worker and pool and current_difficulty:
        try:
            # Each share difficulty roughly = network_diff / (pool_hashrate * target_seconds)
            # We use parasite's highest diff as pool's "best work this round"
            # and we estimate pool avg share diff = current_difficulty * 2^32 / (pool_hashrate_hs * 600) ≈ ...
            # Simpler: best_difficulty / expected_share_diff → luck ratio
            worker_best = parse_diff_to_float(worker.get("bestDifficulty"))
            pool_best = parse_diff_to_float(pool.get("highestDifficulty"))
            # ckpool shares are ~1M by default, but for Plebs pool may be 16k or variable.
            # We use work-since-last-block / pool hashrate to estimate "expected shares" portion
            wslb = (
                pool.get("workSinceLastBlock") or 0
            )  # total integrated diff since last block
            # "luck" → actual best_diff vs expected per this worker.
            # the simplest honest metric: work_since_last_block / pool_hashrate (seconds of work)
            # and our workers's hashrate / pool hashrate → fair share of WSLB.
            cur_hr = float(worker.get("hashrate") or 0)
            pool_hr = float(pool.get("hashrate") or 0)
            fair_share_wslb = (cur_hr / pool_hr) * wslb if pool_hr else 0
            expected_share_diff = (
                current_difficulty / 65536
            )  # rough: 1 share ≈ diff / 64k
            luck = {
                "fair_share_diff_since_last_block": fair_share_wslb,
                "pool_work_since_last_block": wslb,
                "expected_share_diff_estimate": expected_share_diff,
                "worker_share_of_pool_pct": (cur_hr / pool_hr * 100) if pool_hr else 0,
            }
            # pool-luck % — work-on-block progress vs expected by share contribution
            # expected: wslb should equal network_diff when fair share arrives
            try:
                if wslb and current_difficulty and cur_hr and pool_hr:
                    expected_wslb = (cur_hr / pool_hr) * current_difficulty
                    pool_luck_pct = (expected_wslb / wslb * 100.0) if wslb else 0.0
                    luck["pool_luck_pct"] = round(pool_luck_pct, 2)
                if wslb and current_difficulty:
                    luck["round_progress_pct"] = round(
                        min(100, (wslb / current_difficulty) * 100), 2
                    )
            except Exception:
                pass
        except Exception:
            pass

    # ━━ Profitability (real-time, settings-driven, 3 modes) ━━
    #
    # Formulas (Bitcoin consensus + pool economics):
    #
    #   Network hashrate ≈ network_difficulty × 2^32 / 600  [H/s]
    #   Expected blocks/day = your_H/s / net_H/s × 144
    #   Net BTC/day (pool) = expected_blocks × (block_reward + avg_fee) × (1 - pool_fee/100) × (1 - orphan/100)
    #   Net BTC/day (solo) = expected_blocks × (block_reward + avg_fee) × (1 - orphan/100)
    #   Net BTC/day (rental) = net_btc_pool - rental_cost
    #   Hashrate from shares: H = (shares / Δt) × share_diff × 2^32
    #
    # ⚠ LEGACY: this profitability math is a STALE COPY — see the module
    # docstring. The canonical implementation lives in app.py + helpers.py
    # (compute_solo_probabilities / compute_lender_profitability /
    # compute_pool_rental_break_even). Do not fix drift here.
    profitability = {}
    # Hoist cur_hr / net_hr BEFORE the try block so downstream readers
    # (network_share_gauge block) always see well-defined values even if the
    # profitability compute itself fails.
    cur_hr = float(worker.get("hashrate")) if worker and worker.get("hashrate") else 0.0
    net_hr = float(net_hashrate) if net_hashrate else 0.0
    try:
        s = config.load_settings()
        reward = coerce_float(s.get("btc_block_reward"), 3.125)
        fee = coerce_float(s.get("btc_avg_tx_fee"), 0.05)
        pool_fee_pct = max(0, min(100, coerce_float(s.get("pool_fee_pct"), 1.5)))
        orphan_pct = max(0, min(100, coerce_float(s.get("orphan_rate_pct"), 0.5)))
        cost_mode = s.get("cost_mode", "none")
        btc_prices = {"USD": btc_usd, "BRL": btc_brl, "EUR": btc_eur, "GBP": btc_gbp}

        profitability["cost_mode"] = cost_mode
        profitability["active_currency_val"] = s.get("active_currency", "USD")
        profitability["pool_fee_pct"] = pool_fee_pct
        profitability["orphan_pct"] = orphan_pct

        if cur_hr > 0 and net_hr > 0:
            share_of_network = cur_hr / net_hr
            blocks_per_day = 144.0
            total_reward_per_block = reward + fee

            # ── Pool mining (PPS/FPPS approximated) ──
            # Expected blocks = your_share × total_blocks
            # Net after pool fee & orphan
            gross_btc_per_day = (
                share_of_network * blocks_per_day * total_reward_per_block
            )
            pool_net_btc_per_day = (
                gross_btc_per_day
                * (1 - pool_fee_pct / 100.0)
                * (1 - orphan_pct / 100.0)
            )

            # ── Solo mining ──
            # Same formula but no pool fee. Expected blocks PER YEAR = your_share × 144 × 365
            # Solo variance is extreme: P(at least one block in N days) = 1 - e^(-λ)
            # where λ = share_of_network × blocks_per_day (Poisson, each block is independent)
            solo_net_btc_per_day = gross_btc_per_day * (
                1 - orphan_pct / 100.0
            )  # no pool fee
            # CORRECTED: P(≥1 block in a day) uses Poisson(λ) where λ = share_of_network × 144
            blocks_per_day_float = 144.0
            λ_daily = share_of_network * blocks_per_day_float
            solo_p_day = 1 - math.exp(-λ_daily) if λ_daily > 0 else 0.0
            solo_p_year = 1 - math.exp(-λ_daily * 365) if λ_daily > 0 else 0.0
            solo_p_5year = 1 - math.exp(-λ_daily * 365 * 5) if λ_daily > 0 else 0.0
            solo_expected_blocks_per_year = (
                λ_daily * 365
            )  # correct: expected value of Poisson
            solo_expected_time_to_block_days = 1.0 / λ_daily if λ_daily > 0 else None

            # ── Rental cost ──
            ths = cur_hr / 1e12
            rental_cost_per_day = 0.0
            power_cost_per_day = 0.0
            if cost_mode == "rental":
                rental_cost_per_day = ths * coerce_float(
                    s.get("rental_usd_per_th_day"), 0.0
                )
            elif cost_mode == "power":
                watts = coerce_float(s.get("power_watts"), 0.0)
                kwh_rate_usd = coerce_float(s.get("power_kwh_usd"), 0.0)
                power_cost_per_day = (watts / 1000.0) * 24.0 * kwh_rate_usd

            # ── Net after cost ──
            cost_per_day = rental_cost_per_day + power_cost_per_day

            def _fiat_convert(btc_val):
                return {
                    cur: (round(btc_val * px, 4) if px else None)
                    for cur, px in btc_prices.items()
                }

            # ── Risk-adjusted comparison across all 3 modes ──
            pool_net_usd_daily = pool_net_btc_per_day * (btc_usd or 0) if btc_usd else 0
            solo_net_usd_daily = (
                (solo_net_btc_per_day - (cost_per_day / (btc_usd or 1)))
                * (btc_usd or 0)
                if btc_usd
                else 0
            )
            rental_net_usd_daily = pool_net_usd_daily - cost_per_day

            # ── Quantitative risk scores (module-level helpers) ──
            pool_cv = _pool_cv(share_of_network)
            solo_cv = _solo_cv(solo_p_day)
            rental_cv = _rental_cv(pool_cv) if pool_cv else 999.0

            pool_risk_score = _cv_to_score(pool_cv)
            solo_risk_score = _cv_to_score(solo_cv)
            rental_risk_score = _cv_to_score(rental_cv)

            comparison = {
                "pool": {
                    "label": "\u26cf POOL",
                    "net_btc_daily": round(pool_net_btc_per_day, 8),
                    "net_usd_daily": round(pool_net_usd_daily, 2),
                    "risk_score": pool_risk_score,
                    "cv": round(pool_cv, 4),
                    "variance": "LOW \u2014 steady daily BTC from pool shares",
                    "best_for": "Everyday mining \u2014 most capital efficient",
                },
                "solo": {
                    "label": "\u2600 SOLO",
                    "net_btc_daily": round(solo_net_btc_per_day, 8),
                    "net_usd_daily": round(solo_net_usd_daily, 2),
                    "risk_score": solo_risk_score,
                    "cv": round(solo_cv, 4),
                    "variance": "EXTREME \u2014 lottery-like (0 BTC or full block)",
                    "best_for": "Jackpot chasers with low time preference",
                },
                "rental": {
                    "label": "RENTAL",
                    "net_btc_daily": (
                        round(pool_net_btc_per_day - (cost_per_day / (btc_usd or 1)), 8)
                        if btc_usd
                        else None
                    ),
                    "net_usd_daily": round(rental_net_usd_daily, 2),
                    "risk_score": rental_risk_score,
                    "cv": round(rental_cv, 4),
                    "variance": "MODERATE \u2014 pool variance + rental price exposure",
                    "best_for": "Testing hashrate without hardware commitment",
                },
            }

            # Pool mining output
            profitability.update(
                {
                    "share_of_network_pct": round(share_of_network * 100, 8),
                    "gross_btc_per_day": round(gross_btc_per_day, 8),
                    # Pool mode (default, what the user is using)
                    "mode": cost_mode if cost_mode != "none" else "pool",
                    "net_btc_per_day_pool": round(pool_net_btc_per_day, 8),
                    "fiat_per_day_pool": _fiat_convert(pool_net_btc_per_day),
                    "fiat_per_week_pool": _fiat_convert(pool_net_btc_per_day * 7),
                    "fiat_per_month_pool": _fiat_convert(pool_net_btc_per_day * 30),
                    "pool_net_usd_per_day": round(
                        (pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day, 4
                    ),
                    "pool_net_usd_per_month": round(
                        ((pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day) * 30, 2
                    ),
                    # Solo mode
                    "net_btc_per_day_solo": round(solo_net_btc_per_day, 8),
                    "fiat_per_day_solo": _fiat_convert(solo_net_btc_per_day),
                    "solo_p_day_pct": round(solo_p_day * 100, 6),
                    "solo_p_year_pct": round(solo_p_year * 100, 4),
                    "solo_p_5year_pct": round(solo_p_5year * 100, 2),
                    "solo_expected_blocks_per_year": round(
                        solo_expected_blocks_per_year, 4
                    ),
                    "solo_expected_time_to_block_days": (
                        round(solo_expected_time_to_block_days, 2)
                        if solo_expected_time_to_block_days
                        else None
                    ),
                    # Rental mode (cost subtracted)
                    "net_btc_per_day_rental": (
                        round(pool_net_btc_per_day - (cost_per_day / (btc_usd or 1)), 8)
                        if btc_usd
                        else None
                    ),
                    "fiat_per_day_rental": (
                        _fiat_convert(
                            max(
                                0,
                                pool_net_btc_per_day - (cost_per_day / (btc_usd or 1)),
                            )
                        )
                        if btc_usd
                        else None
                    ),
                    "rental_net_btc_per_day": round(
                        pool_net_btc_per_day, 8
                    ),  # gross pool BTC
                    "rental_net_usd_per_day": round(
                        (pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day, 4
                    ),
                    "rental_net_usd_per_month": round(
                        ((pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day) * 30, 2
                    ),
                    # Cost info
                    "cost_per_day_usd": round(cost_per_day, 4),
                    "cost_label": (
                        f"${rental_cost_per_day:.2f}/d rental ({ths:.2f} TH/s × ${coerce_float(s.get('rental_usd_per_th_day'),0.0):.4f})"
                        if cost_mode == "rental"
                        else (
                            f"${power_cost_per_day:.2f}/d power ({coerce_float(s.get('power_watts'),0.0):.0f}W × 24h × ${coerce_float(s.get('power_kwh_usd'),0.10):.4f}/kWh)"
                            if cost_mode == "power"
                            else "."
                        )
                    ),
                    # Break-even: rental rate at which pool_net = rental_cost
                    "break_even_rental_usd_per_th_day": (
                        round(
                            (pool_net_btc_per_day * (btc_usd or 0)) / max(ths, 1e-12), 4
                        )
                        if cost_mode == "rental" and btc_usd and ths > 0
                        else None
                    ),
                    # Effective BTC/TH/s/day (marginal)
                    "effective_btc_per_th_per_day": round(
                        (1.0 / 1e12 / net_hr)
                        * blocks_per_day
                        * total_reward_per_block
                        * (1 - pool_fee_pct / 100.0)
                        * (1 - orphan_pct / 100.0),
                        10,
                    ),
                    # Pool fee info
                    "pool_fee_info": f"Pool fee: {pool_fee_pct}% · Orphan rate: {orphan_pct}% · Reward: {reward}+{fee} BTC/block",
                    # Risk comparison across modes
                    "risk_comparison": comparison,
                    # Disclaimer
                    "disclaimer": "Estimates based on current hashrate, network difficulty, and BTC price. Actual results vary significantly due to variance, pool luck, and difficulty changes.",
                }
            )
        else:
            profitability["unavailable_reason"] = "no hashrate or network hashrate"
    except Exception as e:
        log.warning("[profitability] compute error: %s", e)

    # ━━ Milestones — only REAL, verifiable achievements from pool API data ━━
    # Sources: worker data (bestDifficulty, uptime), account meta (block_count,
    # total_diff), leaderboard (diff_rank, loyalty_rank), session counters.
    # NO projected/fake milestones. Each is gated on actual observed data.
    milestones = []
    try:
        sc = state.timeline_state["session_share_count"]
        best_diff_raw = (
            parse_diff_to_float(worker.get("bestDifficulty", "")) if worker else 0.0
        )
        uptime_s = safe_int(worker.get("uptime", 0)) if worker else 0

        # ── Account-level milestones (from pool API) ──
        block_count = meta.get("block_count") if isinstance(meta, dict) else None
        total_diff_raw = (
            account.get("total_diff") or account.get("totalDifficulty")
            if isinstance(account, dict)
            else None
        )
        total_diff_val = (
            parse_diff_to_float(str(total_diff_raw)) if total_diff_raw else 0.0
        )
        lb_rank = (
            (leaderboard.index(leaderboard_entry) + 1) if leaderboard_entry else None
        )

        # Blocks found (highest tier — pool-verified)
        if block_count and int(block_count) >= 1:
            milestones.append(
                {
                    "tier": "GOLD",
                    "label": f"{int(block_count)} block{'s' if int(block_count) > 1 else ''} mined",
                    "value": f"blocks_found:{block_count}",
                }
            )
        if block_count and int(block_count) >= 2:
            milestones.append(
                {
                    "tier": "GOLD",
                    "label": f"{int(block_count)} blocks confirmed on-chain",
                    "value": f"blocks_found:{block_count}",
                }
            )

        # Total difficulty contributed (lifetime from pool API)
        if total_diff_val >= 1e12:  # ≥ 1T
            diff_fmt = fmt_diff(total_diff_val)
            milestones.append(
                {
                    "tier": "BRONZE",
                    "label": f"total work: {diff_fmt}",
                    "value": f"total_diff:{total_diff_val:.2e}",
                }
            )
        if total_diff_val >= 1e15:  # ≥ 1P
            milestones.append(
                {
                    "tier": "SILVER",
                    "label": f"total work: {fmt_diff(total_diff_val)}",
                    "value": f"total_diff:{total_diff_val:.2e}",
                }
            )

        # Leaderboard ranking
        if lb_rank and lb_rank <= 3:
            milestones.append(
                {
                    "tier": "GOLD",
                    "label": f"top {lb_rank} on leaderboard",
                    "value": f"lb_rank:{lb_rank}",
                }
            )
        elif lb_rank and lb_rank <= 10:
            milestones.append(
                {
                    "tier": "SILVER",
                    "label": f"top {lb_rank} on leaderboard",
                    "value": f"lb_rank:{lb_rank}",
                }
            )
        elif lb_rank and lb_rank <= 25:
            milestones.append(
                {
                    "tier": "BRONZE",
                    "label": f"top {lb_rank} on leaderboard",
                    "value": f"lb_rank:{lb_rank}",
                }
            )

        # ── Session milestones ──
        if sc >= 10:
            milestones.append(
                {
                    "tier": "BRONZE",
                    "label": f"{sc} shares this session",
                    "value": f"session_shares:{sc}",
                }
            )
        if sc >= 100:
            milestones.append(
                {
                    "tier": "BRONZE",
                    "label": f"{sc} shares this session",
                    "value": f"session_shares:{sc}",
                }
            )
        if sc >= 1000:
            milestones.append(
                {
                    "tier": "SILVER",
                    "label": f"{sc:,} shares this session",
                    "value": f"session_shares:{sc}",
                }
            )
        if sc >= 10000:
            milestones.append(
                {
                    "tier": "GOLD",
                    "label": f"{sc:,} shares this session",
                    "value": f"session_shares:{sc}",
                }
            )

        # ── Best difficulty milestones (pool-verified) ──
        if best_diff_raw >= 1e6:  # ≥ 1M
            milestones.append(
                {
                    "tier": "BRONZE",
                    "label": f"best diff: {fmt_diff(best_diff_raw)}",
                    "value": f"best_diff:{best_diff_raw:.2e}",
                }
            )
        if best_diff_raw >= 1e9:  # ≥ 1G
            milestones.append(
                {
                    "tier": "BRONZE",
                    "label": f"best diff: {fmt_diff(best_diff_raw)}",
                    "value": f"best_diff:{best_diff_raw:.2e}",
                }
            )
        if best_diff_raw >= 1e12:  # ≥ 1T
            milestones.append(
                {
                    "tier": "SILVER",
                    "label": f"best diff: {fmt_diff(best_diff_raw)}",
                    "value": f"best_diff:{best_diff_raw:.2e}",
                }
            )
        if best_diff_raw >= 1e14:  # ≥ 100T
            milestones.append(
                {
                    "tier": "SILVER",
                    "label": f"best diff: {fmt_diff(best_diff_raw)}",
                    "value": f"best_diff:{best_diff_raw:.2e}",
                }
            )
        if best_diff_raw >= 1e15:  # ≥ 1P
            milestones.append(
                {
                    "tier": "GOLD",
                    "label": f"best diff: {fmt_diff(best_diff_raw)}",
                    "value": f"best_diff:{best_diff_raw:.2e}",
                }
            )

        # ── Uptime milestones (continuous miner operation) ──
        if uptime_s >= 3600:  # ≥ 1 hour
            milestones.append(
                {
                    "tier": "BRONZE",
                    "label": "1 hour uptime",
                    "value": f"uptime:{uptime_s}",
                }
            )
        if uptime_s >= 86400:  # ≥ 1 day
            milestones.append(
                {
                    "tier": "BRONZE",
                    "label": "1 day uptime",
                    "value": f"uptime:{uptime_s}",
                }
            )
        if uptime_s >= 7 * 86400:  # ≥ 7 days
            milestones.append(
                {
                    "tier": "SILVER",
                    "label": "7 days uptime",
                    "value": f"uptime:{uptime_s}",
                }
            )
        if uptime_s >= 30 * 86400:  # ≥ 30 days
            milestones.append(
                {
                    "tier": "GOLD",
                    "label": "30 days uptime",
                    "value": f"uptime:{uptime_s}",
                }
            )

        # ── High-diff events (user had highest diff on a block) ──
        if isinstance(highest, list):
            mine_count = sum(
                1
                for ev in highest
                if config.BTC_ADDRESS
                in (ev.get("top_diff_address") or ev.get("address") or "")
            )
            if mine_count >= 1:
                milestones.append(
                    {
                        "tier": "SILVER",
                        "label": f"{mine_count} high-diff event{'s' if mine_count > 1 else ''}",
                        "value": f"high_diff_events:{mine_count}",
                    }
                )
            if mine_count >= 10:
                milestones.append(
                    {
                        "tier": "GOLD",
                        "label": f"{mine_count} high-diff events",
                        "value": f"high_diff_events:{mine_count}",
                    }
                )

    except Exception:
        pass

    # ━━ Proximity meter (best_diff vs network_diff, probability, trend) ━━
    prox = proximity.compute_proximity(worker, current_difficulty, net_hashrate, ts)
    try:
        proximity._sample_proximity(
            ts,
            prox.get("best_diff_raw") or 0.0,
            prox.get("network_difficulty_raw") or 0.0,
            worker.get("hashrate") if worker else 0.0,
            prox.get("hot_streak", False),
        )
    except Exception as e:
        log.warning("[sample_proximity] error: %s", e)

    # Hot-streak detection: build the alert dict NOW so it's available when
    # the inject block (placed after the alerts_recent DB read) runs. Capture
    # as a local dict; persistence + render-inject happen downstream.
    hot_streak_alert = None
    if (
        fresh_bump_detected
        and prox
        and prox.get("hot_streak")
        and prox.get("best_diff_str")
        and prox.get("trend_1h_pct") is not None
    ):
        hot_streak_alert = {
            "ts": ts,
            "severity": "SUCCESS",
            "category": "hot_streak",
            "message": (
                f"{(config.WORKER_NAME or 'worker').upper()} best-diff HOT STREAK: {prox['best_diff_str']} "
                f"(+{prox['trend_1h_pct']:.1f}% in 1h) — keep going!"
            ),
        }

    # ━━ Worker-share-of-network gauge (server-side compute; client renders) ━━
    network_share_gauge = {
        "worker_pct": None,
        "pool_pct": None,
        "label": "",
        "pool_hr": None,
        "net_hr": None,
        "worker_share_of_pool_pct": None,
        "has_data": False,
    }
    try:
        if worker and net_hr and cur_hr:
            w_pct = round(cur_hr / net_hr * 100, 6)
            p_hr = float(pool.get("hashrate") or 0) if pool else 0.0
            p_pct = round(p_hr / net_hr * 100, 4) if p_hr > 0 else None
            w_pool_pct = round(cur_hr / p_hr * 100, 4) if p_hr > 0 else None
            network_share_gauge = {
                "worker_pct": w_pct,
                "pool_pct": p_pct,
                "worker_share_of_pool_pct": w_pool_pct,
                "pool_hr": round(p_hr, 2),
                "net_hr": round(net_hr, 2),
                "has_data": True,
                "label": (
                    f"worker = {w_pct:.6f}% of network \u00b7 pool = {p_pct or 0:.4f}% of network"
                    if p_pct
                    else f"worker = {w_pct:.6f}% of network"
                ),
            }
    except Exception:
        pass

    # ━━ Recent alerts ━━
    recent_alerts = []
    try:
        conn = config.get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT 12")
        recent_alerts = [dict(r) for r in c.fetchall()]
        conn.close()
    except Exception:
        pass
    # Merge in-memory CRIT/SUCCESS alerts (disk-watchdog). Each in-memory alert
    # already carries a stable id assigned by _make_memory_alert, so
    # JS renderAlerts sees them as same-item across polls and does NOT re-fire
    # logMessage events. Entries sort above DB alerts naturally because they're
    # prepended to the list.
    if state.memory_critical_alerts:
        in_mem = state.memory_critical_alerts[-12:]
        recent_alerts = in_mem + recent_alerts
        # Cap so renderers don't get flooded; SUCCESS alerts auto-clear on next good persist.
        if len(state.memory_critical_alerts) > 24:
            state.memory_critical_alerts = state.memory_critical_alerts[
                -24:
            ]  # GC oldest

    # ━━ Hot-streak inject (post-DB-read so it lands at top of alerts_recent)
    # Persist directly to alerts DB AND prepend to recent_alerts so the panel
    # shows it this poll. Without the direct INSERT the alerts DB write block
    # (earlier in poll_once) would miss the proximity-driven tuple. We use
    # _make_memory_alert for a stable id so JS prevAlerts-filter dedupes
    # correctly on subsequent polls (no logMessage re-firing).
    if hot_streak_alert is not None:
        try:
            conn = config.get_db()
            c = conn.cursor()
            c.execute(
                "INSERT INTO alerts (ts, severity, category, message) VALUES (?,?,?,?)",
                (
                    hot_streak_alert["ts"],
                    hot_streak_alert["severity"],
                    hot_streak_alert["category"],
                    hot_streak_alert["message"],
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("[hot_streak alert persist] error: %s", e)
        mem_hs = config.make_memory_alert(
            hot_streak_alert["ts"],
            hot_streak_alert["severity"],
            hot_streak_alert["category"],
            hot_streak_alert["message"],
        )
        # Prepend so it appears at the top of the panel. DO NOT also push to
        # state.memory_critical_alerts — the existing in_mem prepend block + DB
        # SELECT (which now includes this row) would duplicate the entry on
        # the next poll.
        recent_alerts = [mem_hs] + recent_alerts

    # ━━ Recent timeline events ━━
    timeline_recent = []
    try:
        conn = config.get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM share_timeline ORDER BY id DESC LIMIT 80")
        timeline_recent = [dict(r) for r in c.fetchall()]
        conn.close()
    except Exception:
        pass

    # ━━ Event stats (session + rolling windows) ━━
    now = int(time.time())
    hour_ago = now - 3600
    day_ago = now - 86400
    session_share_count = state.timeline_state["session_share_count"]
    session_best_bumps = state.timeline_state["session_best_diff_bumps"]
    sph = 0.0
    hist = state.timeline_state["share_submit_history"]
    if len(hist) >= 2 and (hist[-1] - hist[0]) > 0:
        sph = (len(hist) - 1) * (3600.0 / (hist[-1] - hist[0]))
    event_stats = {
        "session_share_count": session_share_count,
        "session_best_diff_bumps": session_best_bumps,
        "rolling_shares_per_hour": round(sph, 2),
        "last_submit_ts": state.timeline_state["last_submit_ts"],
        "last_share_age_s": (
            (now - state.timeline_state["last_submit_ts"])
            if state.timeline_state["last_submit_ts"]
            else None
        ),
    }
    try:
        conn = config.get_db()
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM share_timeline WHERE ts >= ? AND event_type='SHARE_FOUND'",
            (hour_ago,),
        )
        r = c.fetchone()
        shares_last_hour = r[0] if r else 0
        c.execute(
            "SELECT COUNT(*) FROM share_timeline WHERE ts >= ? AND event_type='SHARE_FOUND'",
            (day_ago,),
        )
        r = c.fetchone()
        shares_last_day = r[0] if r else 0
        c.execute(
            "SELECT COUNT(*) FROM share_timeline WHERE event_type='BEST_DIFF_BUMP' AND ts >= ?",
            (day_ago,),
        )
        r = c.fetchone()
        best_diffs_last_day = r[0] if r else 0
        conn.close()
        event_stats.update(
            {
                "db_shares_last_hour": shares_last_hour,
                "db_shares_last_day": shares_last_day,
                "db_best_diffs_last_day": best_diffs_last_day,
            }
        )
    except Exception:
        pass

    # ━━ Hot-streak alert (proximity-driven, fresh-bump gated) ━━
    # Already captured above (right after proximity compute). Here we just
    # route it: direct DB INSERT for persistence + prepend to recent_alerts
    # so the panel shows it THIS poll. We deliberately do NOT push to
    # state.memory_critical_alerts: the existing `in_mem` prepend block runs every
    # poll, and the DB SELECT also returns the INSERTed row — pushing the
    # memory alert would DUPLICATE the entry on poll N+1.

    # ── Enrich pool with computed fields ──
    pool_enriched = dict(pool) if isinstance(pool, dict) else {}
    if current_difficulty and pool and pool.get("workSinceLastBlock"):
        wslb = float(pool.get("workSinceLastBlock")) or 0
        if current_difficulty > 0:
            work_pct = min(100.0, wslb / float(current_difficulty) * 100.0)
            pool_enriched["workPct"] = round(work_pct, 4)
            pool_enriched["workStr"] = fmt_diff(wslb)
        # Expected blocks: time until expected block found given pool hashrate
        pool_hr = float(pool.get("hashrate") or 0)
        if pool_hr > 0:
            secs_per_block = (float(current_difficulty) * (2**32)) / pool_hr
            pool_enriched["expectedSecondsPerBlock"] = secs_per_block

    state.latest_snapshot = {
        "ts": ts,
        "btc_address": config.BTC_ADDRESS,
        "worker": worker,
        "worker_index": worker_index,
        "user_aggregate": user,
        "pool": pool_enriched if isinstance(pool, dict) else pool,
        "account": account,
        "account_meta": meta,
        "lightning": lightning,
        "leaderboard_entry": leaderboard_entry,
        "leaderboard_total": len(leaderboard),
        "highest_diffs": highest[:20] if isinstance(highest, list) else [],
        "network": {
            "height": network_height,
            "difficulty": current_difficulty,
            "hashrate": net_hashrate,
        },
        "btc_price": {"usd": btc_usd, "brl": btc_brl, "eur": btc_eur, "gbp": btc_gbp},
        "luck_estimate": luck,
        "halving": halving,
        "mempool_fees": mempool_fees,
        "profitability": profitability,
        "milestones": milestones,
        "proximity": prox,
        "network_share_gauge": network_share_gauge,
        "alerts_recent": recent_alerts,
        "timeline_recent": timeline_recent[:60],
        "event_stats": event_stats,
        "timeline_last_n": timeline_events[-30:],  # brand-new this poll; for live log
        "leaderboard_table_top_30": (
            leaderboard[:30] if isinstance(leaderboard, list) else []
        ),
        "all_workers": all_workers,
    }


def purge_old():
    cutoff = int(time.time()) - 30 * 86400
    try:
        conn = config.get_db()
        c = conn.cursor()
        c.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
        c.execute("DELETE FROM alerts WHERE ts < ?", (cutoff,))
        c.execute("DELETE FROM share_timeline WHERE ts < ?", (cutoff,))
        c.execute("DELETE FROM proximity_history WHERE ts < ?", (cutoff,))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[purge] error: %s", e)


def poll_loop():
    cleanup_every = max(60, int(86400 / config.POLL_INTERVAL))  # ~once a day
    n = 0
    while True:
        try:
            poll_once()
            n += 1
            if n >= cleanup_every:
                purge_old()
                n = 0
        except Exception as e:
            log.error("[poll_loop] error: %s", e)
        time.sleep(config.POLL_INTERVAL)
