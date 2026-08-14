"""Pure computation helpers extracted from app._do_poll (Issue #135).

These blocks were originally inline inside the ~1260-line ``_do_poll``
monolith — untestable because the function only runs live with real network
access. Each function is a VERBATIM copy of the original block (zero
behavior change): same formulas, same defaults, same branches. ``_do_poll``
now calls them; the unit tests in ``tests/test_poll_compute.py`` pin their
behavior so future edits to the poll math are safe.

Only dependencies are leaf modules (``helpers``, ``services.names``) and the
stdlib — importing this module has zero side effects (no DB, no network).
"""
import logging

from helpers import parse_diff_to_float, fmt_diff, fmt_hashrate
import services.names as _names

log = logging.getLogger("cypher65.poll_compute")


def derive_network_values(bc_diff_val, bc_hashrate_val):
    """Derive (current_difficulty, net_hashrate) from blockchain.info values.

    - blockchain.info /q/hashrate returned TH/s historically, but as of
      2025-2026 it returns GH/s. Multiply by 1e9 to get H/s.
    - If hashrate is unknown/zero but difficulty is known, derive hashrate
      from the canonical Bitcoin formula: hashrate = difficulty * 2^32 / 600.
    """
    if bc_hashrate_val is not None:
        net_hashrate = float(bc_hashrate_val) * 1e9
    else:
        net_hashrate = None
    current_difficulty = float(bc_diff_val) if bc_diff_val is not None else None
    # Fallback: derive net_hashrate from difficulty + target block time
    if current_difficulty is not None and (net_hashrate is None or net_hashrate == 0):
        net_hashrate = current_difficulty * (2 ** 32) / 600
    return current_difficulty, net_hashrate


def parse_mempool_fees(mf_raw):
    """Parse mempool.space /v1/fees/recommended into a sat/vB dict.

    Keeps the numeric fields; falls back to a shape with None values when
    the upstream payload is missing/empty so downstream readers always see
    the expected keys.
    """
    mempool_fees = {}
    if isinstance(mf_raw, dict):
        for k in ("fastestFee", "halfHourFee", "hourFee", "minimumFee", "economyFee"):
            v = mf_raw.get(k)
            if isinstance(v, (int, float)):
                mempool_fees[k] = v
    if not mempool_fees:
        mempool_fees = {"fastestFee": None, "halfHourFee": None, "hourFee": None}
    return mempool_fees


def merge_btc_quotes(coingecko_quote, binance_usd_raw, binance_brl_raw):
    """Merge CoinGecko (multi-currency) with Binance real-time USD/BRL.

    Binance wins when available (faster, lower latency); CoinGecko values
    fill the rest (EUR/GBP/JPY/KRW/CNY). Returns a dict with exactly the
    keys ``usd/brl/eur/gbp/jpy/krw/cny`` (None when unknown).
    """
    binance_usd = None
    binance_brl = None
    if isinstance(binance_usd_raw, dict) and binance_usd_raw.get("price"):
        try:
            binance_usd = float(binance_usd_raw["price"])
        except (ValueError, TypeError):
            pass
    if isinstance(binance_brl_raw, dict) and binance_brl_raw.get("price"):
        try:
            binance_brl = float(binance_brl_raw["price"])
        except (ValueError, TypeError):
            pass

    btc_usd = (coingecko_quote or {}).get("bitcoin", {}).get("usd") if isinstance(coingecko_quote, dict) else None
    btc_brl = (coingecko_quote or {}).get("bitcoin", {}).get("brl") if isinstance(coingecko_quote, dict) else None
    # Prefer Binance real-time USD/BRL when available (faster, lower latency)
    if binance_usd is not None and binance_usd > 0:
        btc_usd = binance_usd
    if binance_brl is not None and binance_brl > 0:
        btc_brl = binance_brl
    return {
        "usd": btc_usd,
        "brl": btc_brl,
        "eur": (coingecko_quote or {}).get("bitcoin", {}).get("eur") if isinstance(coingecko_quote, dict) else None,
        "gbp": (coingecko_quote or {}).get("bitcoin", {}).get("gbp") if isinstance(coingecko_quote, dict) else None,
        "jpy": (coingecko_quote or {}).get("bitcoin", {}).get("jpy") if isinstance(coingecko_quote, dict) else None,
        "krw": (coingecko_quote or {}).get("bitcoin", {}).get("krw") if isinstance(coingecko_quote, dict) else None,
        "cny": (coingecko_quote or {}).get("bitcoin", {}).get("cny") if isinstance(coingecko_quote, dict) else None,
    }


def compute_halving_countdown(network_height):
    """Compute the Bitcoin halving countdown for a given block height.

    Halvings happen every 210000 blocks (epochs); the reward halves each
    epoch starting from 50 BTC. Returns the empty-shape dict when the height
    is unknown.
    """
    # Quirk (preserved verbatim from _do_poll): the base shape carries a
    # "height" key, but the populated shape swaps it for next_height /
    # current_height — consumers must read the populated keys when the
    # height is known.
    halving = {"height": network_height, "blocks_remaining": None,
               "estimated_seconds_remaining": None, "next_reward_btc": None,
               "epoch_label": ""}
    if isinstance(network_height, int):
        next_halving_h = ((network_height // 210000) + 1) * 210000
        blocks_left = max(0, next_halving_h - network_height)
        # assume 600s/block average → seconds remaining
        secs_left = blocks_left * 600
        # The reward halves from current 3.125 → 1.5625 (always halves by half).
        epoch_idx = (next_halving_h // 210000) - 1
        cur_reward = 50.0 * (0.5 ** epoch_idx) if epoch_idx >= 0 else 50.0
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
        }
    return halving


def build_all_workers(user_data, primary_name):
    """Build the All-Workers panel list from the pool user payload.

    Returns (all_workers, worker, worker_index): the sanitized entries, the
    primary worker dict (raw, as returned by the API), and its index. The
    primary match is by normalized name OR id against ``primary_name``.
    """
    all_workers = []
    worker = None
    worker_index = None
    if user_data and isinstance(user_data.get("workerData"), list):
        for idx, w in enumerate(user_data["workerData"]):
            raw_name = str(w.get("name", ""))
            raw_id = str(w.get("id", ""))
            clean_name = _names.sanitize(raw_name)
            clean_id = _names.sanitize(raw_id)
            entry = {
                "id": clean_id,
                "name": clean_name,
                "hashrate": w.get("hashrate"),
                "bestDifficulty": w.get("bestDifficulty", ""),
                "lastSubmission": w.get("lastSubmission"),
                "uptime": w.get("uptime"),
                "is_primary": _names.normalize(raw_name) == _names.normalize(primary_name)
                              or _names.normalize(raw_id) == _names.normalize(primary_name),
            }
            all_workers.append(entry)
            if entry["is_primary"]:
                worker = w
                worker_index = idx
    return all_workers, worker, worker_index


def select_primary_worker(user_data, all_workers):
    """Fallback primary selection when no worker matched by name/id.

    Picks the worker with the best hashrate; when ALL workers are idle
    (hr=0) picks the first so bestDifficulty/lastSubmission/uptime still
    surface on the dashboard. Mutates ``is_primary`` on the chosen entry.
    Returns (all_workers, worker, worker_index).
    """
    worker = None
    worker_index = None
    if not all_workers or not (user_data and isinstance(user_data.get("workerData"), list)):
        return all_workers, worker, worker_index
    best_idx = 0
    best_hr = 0
    for i, entry in enumerate(all_workers):
        hr = float(entry.get("hashrate") or 0)
        if hr > best_hr:
            best_hr = hr
            best_idx = i
    if best_hr > 0:
        if best_idx < len(user_data["workerData"]):
            all_workers[best_idx]["is_primary"] = True
            worker = user_data["workerData"][best_idx]
            worker_index = best_idx
            log.info("[primary] auto-selected worker %s with HR %s (best of %d)",
                     all_workers[best_idx]["name"], best_hr, len(all_workers))
    elif len(all_workers) > 0 and len(user_data["workerData"]) > 0:
        # All workers idle (hr=0) — pick the first so the dashboard still
        # surfaces bestDifficulty / lastSubmission / uptime. Only when a
        # workerData entry exists to pair with (worker stays None otherwise).
        all_workers[0]["is_primary"] = True
        worker = user_data["workerData"][0]
        worker_index = 0
        log.info("[primary] all workers idle — selected %s as primary (hr=0, %d total)",
                 all_workers[0]["name"], len(all_workers))
    return all_workers, worker, worker_index


def dedup_workers(entries):
    """Merge workers with the same normalized name (case-insensitive).

    The entry with the highest hashrate wins (active beats dead). Entries
    with an empty name are kept verbatim (no dedup possible).
    """
    if not entries:
        return entries
    seen = {}  # normalized_key -> index in deduped list
    deduped = []
    for entry in entries:
        key = _names.dedup_key(entry.get("name", "") or "")
        if not key:
            # Empty name means no dedup possible; keep verbatim
            deduped.append(entry)
            continue
        if key in seen:
            existing_idx = seen[key]
            existing = deduped[existing_idx]
            incoming_hr = entry.get("hashrate") or 0
            existing_hr = existing.get("hashrate") or 0
            if incoming_hr > existing_hr:
                deduped[existing_idx] = entry
                log.debug("[dedup] merged %s → %s (HR %s > %s)",
                          existing.get("name"), entry.get("name"),
                          incoming_hr, existing_hr)
        else:
            seen[key] = len(deduped)
            deduped.append(entry)
    return deduped


def compute_share_calc(ts, gap, share_diff_raw, current_difficulty,
                       best_diff_str, session_share_count):
    """Build the per-share LIVE HASH CALCULATOR payload (pure math).

    Given an accepted share (its difficulty and the gap since the previous
    share), computes the instantaneous hashrate, the per-share block
    probability and the hashes attempted — exactly what the dashboard
    exposes in real time.
    """
    hashes_attempted = share_diff_raw * (2 ** 32)
    p_block_this = share_diff_raw / float(current_difficulty)
    inst_hr_hps = hashes_attempted / float(gap)
    return {
        "ts": ts,
        "gap": gap,
        "share_diff_raw": share_diff_raw,
        "share_diff_str": fmt_diff(share_diff_raw),
        "hashes_attempted": hashes_attempted,
        "hashes_attempted_str": f"{hashes_attempted:.3e}",
        "p_block_this_share": p_block_this,
        "p_block_this_share_pct_str": (
            f"{p_block_this * 100:.4e}%"
            if p_block_this < 0.01
            else f"{p_block_this * 100:.4f}%"
        ),
        "instantaneous_hr_hps": inst_hr_hps,
        "instantaneous_hr_str": fmt_hashrate(inst_hr_hps),
        "best_diff_at_time": (
            parse_diff_to_float(best_diff_str) if best_diff_str else 0.0
        ),
        "best_diff_at_time_str": best_diff_str,
        "network_diff_at_time": current_difficulty,
        "network_diff_at_time_str": fmt_diff(current_difficulty),
        "session_share_count_at_time": session_share_count,
    }


def compute_luck_estimate(worker, pool, current_difficulty):
    """Compute the pool-luck estimate (fair share vs work-since-last-block).

    Returns an empty dict when inputs are missing; never raises (worst-case
    returns the base shape without the luck percentages).
    """
    luck = {}
    if not (worker and pool and current_difficulty):
        return luck
    try:
        # Each share difficulty roughly = network_diff / (pool_hashrate * target_seconds)
        # We use parasite's highest diff as pool's "best work this round"
        # and we estimate pool avg share diff = current_difficulty * 2^32 / (pool_hashrate_hs * 600) ≈ ...
        # Simpler: best_difficulty / expected_share_diff → luck ratio
        parse_diff_to_float(worker.get("bestDifficulty"))
        parse_diff_to_float(pool.get("highestDifficulty"))
        # ckpool shares are ~1M by default, but for Plebs pool may be 16k or variable.
        # We use work-since-last-block / pool hashrate to estimate "expected shares" portion
        wslb = pool.get("workSinceLastBlock") or 0  # total integrated diff since last block
        # "luck" → actual best_diff vs expected per this worker.
        # the simplest honest metric: work_since_last_block / pool_hashrate (seconds of work)
        # and our workers's hashrate / pool hashrate → fair share of WSLB.
        cur_hr = float(worker.get("hashrate") or 0)
        pool_hr = float(pool.get("hashrate") or 0)
        fair_share_wslb = (cur_hr / pool_hr) * wslb if pool_hr else 0
        expected_share_diff = current_difficulty / 65536  # rough: 1 share ≈ diff / 64k
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
                luck["round_progress_pct"] = round(min(100, (wslb / current_difficulty) * 100), 2)
        except Exception:
            pass
    except Exception:
        pass
    return luck


def fiat_convert(btc_val, btc_prices):
    """Convert a BTC value into every tracked fiat currency (rounded to 4)."""
    return {
        cur: (round(btc_val * px, 4) if px else None)
        for cur, px in btc_prices.items()
    }
