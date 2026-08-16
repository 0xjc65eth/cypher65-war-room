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

from helpers import (
    parse_diff_to_float,
    fmt_diff,
    fmt_hashrate,
    safe_int,
    coerce_float,
    compute_solo_probabilities,
    compute_pool_rental_break_even,
    compute_lender_profitability,
    build_decision_matrix,
)
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
        net_hashrate = current_difficulty * (2**32) / 600
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

    btc_usd = (
        (coingecko_quote or {}).get("bitcoin", {}).get("usd")
        if isinstance(coingecko_quote, dict)
        else None
    )
    btc_brl = (
        (coingecko_quote or {}).get("bitcoin", {}).get("brl")
        if isinstance(coingecko_quote, dict)
        else None
    )
    # Prefer Binance real-time USD/BRL when available (faster, lower latency)
    if binance_usd is not None and binance_usd > 0:
        btc_usd = binance_usd
    if binance_brl is not None and binance_brl > 0:
        btc_brl = binance_brl
    return {
        "usd": btc_usd,
        "brl": btc_brl,
        "eur": (
            (coingecko_quote or {}).get("bitcoin", {}).get("eur")
            if isinstance(coingecko_quote, dict)
            else None
        ),
        "gbp": (
            (coingecko_quote or {}).get("bitcoin", {}).get("gbp")
            if isinstance(coingecko_quote, dict)
            else None
        ),
        "jpy": (
            (coingecko_quote or {}).get("bitcoin", {}).get("jpy")
            if isinstance(coingecko_quote, dict)
            else None
        ),
        "krw": (
            (coingecko_quote or {}).get("bitcoin", {}).get("krw")
            if isinstance(coingecko_quote, dict)
            else None
        ),
        "cny": (
            (coingecko_quote or {}).get("bitcoin", {}).get("cny")
            if isinstance(coingecko_quote, dict)
            else None
        ),
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
    halving = {
        "height": network_height,
        "blocks_remaining": None,
        "estimated_seconds_remaining": None,
        "next_reward_btc": None,
        "epoch_label": "",
    }
    if isinstance(network_height, int):
        next_halving_h = ((network_height // 210000) + 1) * 210000
        blocks_left = max(0, next_halving_h - network_height)
        # assume 600s/block average → seconds remaining
        secs_left = blocks_left * 600
        # The reward halves from current 3.125 → 1.5625 (always halves by half).
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
                "is_primary": _names.normalize(raw_name)
                == _names.normalize(primary_name)
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
    if not all_workers or not (
        user_data and isinstance(user_data.get("workerData"), list)
    ):
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
            log.info(
                "[primary] auto-selected worker %s with HR %s (best of %d)",
                all_workers[best_idx]["name"],
                best_hr,
                len(all_workers),
            )
    elif len(all_workers) > 0 and len(user_data["workerData"]) > 0:
        # All workers idle (hr=0) — pick the first so the dashboard still
        # surfaces bestDifficulty / lastSubmission / uptime. Only when a
        # workerData entry exists to pair with (worker stays None otherwise).
        all_workers[0]["is_primary"] = True
        worker = user_data["workerData"][0]
        worker_index = 0
        log.info(
            "[primary] all workers idle — selected %s as primary (hr=0, %d total)",
            all_workers[0]["name"],
            len(all_workers),
        )
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
                log.debug(
                    "[dedup] merged %s → %s (HR %s > %s)",
                    existing.get("name"),
                    entry.get("name"),
                    incoming_hr,
                    existing_hr,
                )
        else:
            seen[key] = len(deduped)
            deduped.append(entry)
    return deduped


def compute_share_calc(
    ts, gap, share_diff_raw, current_difficulty, best_diff_str, session_share_count
):
    """Build the per-share LIVE HASH CALCULATOR payload (pure math).

    Given an accepted share (its difficulty and the gap since the previous
    share), computes the instantaneous hashrate, the per-share block
    probability and the hashes attempted — exactly what the dashboard
    exposes in real time.
    """
    hashes_attempted = share_diff_raw * (2**32)
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
        wslb = (
            pool.get("workSinceLastBlock") or 0
        )  # total integrated diff since last block
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
                luck["round_progress_pct"] = round(
                    min(100, (wslb / current_difficulty) * 100), 2
                )
        except Exception:
            pass
    except Exception:
        pass
    return luck


def fiat_convert(btc_val, btc_prices):
    """Convert a BTC value into every tracked fiat currency (rounded to 4)."""
    return {
        cur: (round(btc_val * px, 4) if px else None) for cur, px in btc_prices.items()
    }


def compute_profitability(
    worker,
    net_hashrate,
    btc_prices,
    market_cache,
    min_plausible_price,
    btc_price_cache,
    settings,
):
    """Profitability payload (3 modes: pool / solo / rental + lender).

    Verbatim extraction of the ``_do_poll`` profitability block (Issue
    #137). ``settings`` is the already-loaded settings dict (the caller
    owns the load, so the function stays pure); ``btc_prices`` maps the
    currency codes to their USD/BRL/EUR/GBP/JPY/KRW/CNY values;
    ``market_cache`` is the warm hashrate-market offer cache;
    ``min_plausible_price`` guards against unit-conversion garbage from
    the market feed; ``btc_price_cache`` supplies the stale-while-
    revalidate fallback for the USD lender rate.

    Returns ``(profitability, cur_hr, net_hr)`` — cur_hr/net_hr are
    hoisted before the try block so downstream readers (the network-share
    gauge) always see well-defined values even when this compute fails.
    """
    profitability = {}
    # Hoist cur_hr / net_hr BEFORE the try block so downstream readers
    # (network_share_gauge block) always see well-defined values even if the
    # profitability compute itself fails.
    cur_hr = float(worker.get("hashrate")) if worker and worker.get("hashrate") else 0.0
    net_hr = float(net_hashrate) if net_hashrate else 0.0
    btc_usd = btc_prices.get("USD")
    btc_brl = btc_prices.get("BRL")
    btc_eur = btc_prices.get("EUR")
    btc_gbp = btc_prices.get("GBP")
    btc_jpy = btc_prices.get("JPY")
    btc_krw = btc_prices.get("KRW")
    btc_cny = btc_prices.get("CNY")
    try:
        s = settings
        reward = coerce_float(s.get("btc_block_reward"), 3.125)
        fee = coerce_float(s.get("btc_avg_tx_fee"), 0.05)
        pool_fee_pct = coerce_float(s.get("pool_fee_pct"), 1.5)
        orphan_pct = coerce_float(s.get("orphan_rate_pct"), 0.5)
        cost_mode = s.get("cost_mode", "none")

        profitability["cost_mode"] = cost_mode
        profitability["cost_model_configured"] = cost_mode != "none"
        profitability["cost_per_kwh"] = coerce_float(s.get("power_kwh_usd"), 0.10)
        profitability["cost_label"] = (
            f"${coerce_float(s.get('rental_usd_per_th_day'),0.0):.2f}/d rental"
            if cost_mode == "rental"
            else (
                f"${coerce_float(s.get('power_kwh_usd'),0.10):.4f}/kWh power ({coerce_float(s.get('power_watts'),0.0):.0f}W)"
                if cost_mode == "power"
                else "no cost model"
            )
        )
        profitability["active_currency_val"] = s.get("active_currency", "USD")
        profitability["pool_fee_pct"] = pool_fee_pct
        profitability["orphan_pct"] = orphan_pct

        # ── Lender market rate (Scenario D) — emitted WITHOUT a worker ──
        # The rental market price only needs the warm hashrate-market cache
        # (plus btc_usd for the USD conversion) — NOT the user's hashrate.
        # Computed outside the cur_hr gate so the LEASE panel always shows the
        # real market rate even on a worker-less / cold-address server.
        lender_market_rate_btc = None
        try:
            _offers = market_cache.get("offers") or []
            _real = [
                o
                for o in _offers
                if not getattr(o, "estimated", False)
                and (getattr(o, "price_per_th_day", 0) or 0) >= min_plausible_price
            ]
            _pool = _real or [
                o
                for o in _offers
                if (getattr(o, "price_per_th_day", 0) or 0) >= min_plausible_price
            ]
            if _pool:
                lender_market_rate_btc = min(o.price_per_th_day for o in _pool)
        except Exception:
            lender_market_rate_btc = None
        # P0-5 audit (hashmarket honesty guard): a SHA-256 rental rate is
        # physically bounded — real market asks run ~10-50k sats/TH/d
        # (1e-4..5e-4 BTC). A "best price" landing outside 1e-8..1e-2 is a
        # unit-conversion bug (sats vs BTC, TH vs PH), and feeding it into
        # lender_net_usd_per_day produced absurd lease P&L (measured live:
        # $55,411/d for an 87 TH rig — 100× reality). Clamp + log instead of
        # surfacing fake money.
        if lender_market_rate_btc is not None:
            _r = float(lender_market_rate_btc)
            if _r < 1e-8 or _r > 1e-2:
                log.warning(
                    "[profitability] implausible lender market rate %.6g BTC/TH/d — ignoring (unit bug?)",
                    _r,
                )
                lender_market_rate_btc = None
        if not lender_market_rate_btc and btc_usd:
            cfg_rate_usd = coerce_float(s.get("rental_usd_per_th_day"), 0.0)
            if cfg_rate_usd > 0:
                lender_market_rate_btc = cfg_rate_usd / btc_usd
        profitability["lender_market_rate_btc_per_th_day"] = (
            round(lender_market_rate_btc, 12) if lender_market_rate_btc else None
        )
        # The USD market rate needs a BTC price. The live fetch may be briefly
        # unavailable (provider 429, throttle) — fall back to the cached quote
        # or the same hardcoded fallback the price fetch itself uses, so the
        # LEASE panel shows the real market rate instead of '—' on a cold box.
        _btc_conv = btc_usd
        if not _btc_conv:
            _cached_quote = (btc_price_cache.get("data") or {}).get("bitcoin") or {}
            _btc_conv = _cached_quote.get(
                "usd"
            )  # stale-while-revalidate: último real, nunca mock
        profitability["lender_market_rate_usd_per_th_day"] = (
            round(lender_market_rate_btc * _btc_conv, 4)
            if lender_market_rate_btc
            else None
        )

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
            # Solo variance is extreme: share_of_network is the per-BLOCK chance, and
            # with ~144 blocks/day, P(≥1 block in N days) = 1 - (1 - share)^(144·N).
            # Math extracted to helpers.compute_solo_probabilities (pure, unit-tested).
            solo_net_btc_per_day = gross_btc_per_day * (
                1 - orphan_pct / 100.0
            )  # no pool fee
            _solo = compute_solo_probabilities(share_of_network, blocks_per_day)
            solo_p_day = _solo["solo_p_day"]
            solo_p_year = _solo["solo_p_year"]
            solo_p_5year = _solo["solo_p_5year"]
            solo_expected_blocks_per_year = _solo["solo_expected_blocks_per_year"]
            solo_expected_time_to_block_days = _solo["solo_expected_time_to_block_days"]

            # ── Rental/power cost + break-even (pure, unit-tested) ──
            # Math extracted to helpers.compute_pool_rental_break_even so the
            # profitability formulas have a single source of truth.
            ths = cur_hr / 1e12
            _be = compute_pool_rental_break_even(
                ths=ths,
                pool_net_btc_per_day=pool_net_btc_per_day,
                btc_usd=btc_usd or 0,
                cost_mode=cost_mode,
                rental_usd_per_th_day=coerce_float(s.get("rental_usd_per_th_day"), 0.0),
                power_watts=coerce_float(s.get("power_watts"), 0.0),
                power_kwh_usd=coerce_float(s.get("power_kwh_usd"), 0.0),
            )
            # cost_per_day is the only cost value the payload uses
            # (rental_cost_per_day/power_cost_per_day were dead locals in the
            # original monolith too — dropped during extraction).
            cost_per_day = _be["cost_per_day"]

            def _fiat_convert(btc_val):
                return fiat_convert(btc_val, btc_prices)

            # ── Lender (Scenario D): rent OUT your own hashrate vs mining ──
            # Revenue = ths × market rental rate (BTC/TH/day); the locador keeps
            # paying electricity. lender_market_rate_btc is computed above,
            # outside the cur_hr gate (market price does not need a worker).
            # Math extracted to helpers.compute_lender_profitability (pure).
            lender_watts = coerce_float(s.get("power_watts"), 0.0)
            lender_kwh_usd = coerce_float(s.get("power_kwh_usd"), 0.10)
            lender_power_cost = (
                (lender_watts / 1000.0) * 24.0 * lender_kwh_usd
                if lender_watts > 0
                else 0.0
            )
            _lender = compute_lender_profitability(
                ths=ths,
                market_btc_per_th_day=lender_market_rate_btc or 0,
                power_cost_usd_per_day=lender_power_cost,
                pool_net_btc_per_day=pool_net_btc_per_day,
                btc_usd=btc_usd or 0,
            )
            _lender_net_btc = _lender.get("lender_net_btc_per_day")
            profitability.update(
                {
                    "lender_net_btc_per_day": _lender["lender_net_btc_per_day"],
                    "lender_net_usd_per_day": _lender["lender_net_usd_per_day"],
                    "lender_revenue_btc_per_day": _lender["lender_revenue_btc_per_day"],
                    "lender_power_cost_usd_per_day": _lender[
                        "lender_power_cost_usd_per_day"
                    ],
                    "lender_mine_net_usd_per_day": _lender[
                        "lender_mine_net_usd_per_day"
                    ],
                    "lender_vs_mining_usd_per_day": _lender[
                        "lender_vs_mining_usd_per_day"
                    ],
                    "lender_recommendation": _lender["lender_recommendation"],
                    "lender_breakeven_btc_per_th_day": _lender[
                        "lender_breakeven_btc_per_th_day"
                    ],
                    "lender_breakeven_usd_per_th_day": _lender[
                        "lender_breakeven_usd_per_th_day"
                    ],
                    "lender_fiat_per_day": (
                        _fiat_convert(_lender_net_btc)
                        if _lender_net_btc is not None
                        else {}
                    ),
                    "lender_fiat_per_month": (
                        _fiat_convert(_lender_net_btc * 30)
                        if _lender_net_btc is not None
                        else {}
                    ),
                }
            )

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
                    "pool_net_usd_per_day": (
                        round((pool_net_btc_per_day * btc_usd) - cost_per_day, 4)
                        if btc_usd
                        else None
                    ),
                    "pool_net_usd_per_month": (
                        round(((pool_net_btc_per_day * btc_usd) - cost_per_day) * 30, 2)
                        if btc_usd
                        else None
                    ),
                    # Solo mode
                    "net_btc_per_day_solo": round(solo_net_btc_per_day, 8),
                    "fiat_per_day_solo": _fiat_convert(solo_net_btc_per_day),
                    "fiat_per_month_solo": _fiat_convert(solo_net_btc_per_day * 30),
                    "solo_p_day_pct": round(solo_p_day * 100, 8),
                    "solo_p_year_pct": round(solo_p_year * 100, 4),
                    "solo_p_5year_pct": round(solo_p_5year * 100, 2),
                    "solo_expected_blocks_per_year": round(
                        solo_expected_blocks_per_year, 4
                    ),
                    "solo_expected_time_to_block_days": (
                        round(solo_expected_time_to_block_days, 1)
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
                    "fiat_per_month_rental": (
                        _fiat_convert(
                            max(
                                0,
                                pool_net_btc_per_day - (cost_per_day / (btc_usd or 1)),
                            )
                            * 30
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
                    # Cost info (cost_model_configured, cost_per_kwh, cost_label
                    # already set above; cost_per_day_usd is dynamic)
                    "cost_per_day_usd": round(cost_per_day, 4),
                    # Break-even: rental rate at which pool_net = rental_cost
                    # (computed by helpers.compute_pool_rental_break_even)
                    "break_even_rental_usd_per_th_day": _be[
                        "break_even_rental_usd_per_th_day"
                    ],
                    # General break-even cost per TH/day (always computed)
                    "breakeven_cost_per_th_day": _be["breakeven_cost_per_th_day"],
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
                    # Disclaimer
                    "disclaimer": "Estimates based on current hashrate, network difficulty, and BTC price. Actual results vary significantly due to variance, pool luck, and difficulty changes.",
                }
            )
            # P0-2: unified solo vs pool vs lease Decision Matrix (pure agg).
            # Aggregates the per-mode numbers already computed above into one
            # capital-allocation comparison for the market module panel.
            profitability["decision_matrix"] = build_decision_matrix(
                pool_net_usd_per_day=profitability.get("pool_net_usd_per_day"),
                solo_expected_time_days=profitability.get(
                    "solo_expected_time_to_block_days"
                ),
                solo_p_year_pct=profitability.get("solo_p_year_pct"),
                lender_net_usd_per_day=profitability.get("lender_net_usd_per_day"),
                lender_recommendation=profitability.get("lender_recommendation"),
                breakeven_cost_per_th_day=profitability.get(
                    "breakeven_cost_per_th_day"
                ),
            )
        else:
            profitability["unavailable_reason"] = "no hashrate or network hashrate"
    except Exception as e:
        import traceback as _tb

        log.warning("[profitability] compute error: %s\n%s", e, _tb.format_exc())
    return profitability, cur_hr, net_hr


def build_milestones(worker, timeline_state):
    """Session milestones (share counts + best-diff + uptime tiers).

    Verbatim extraction of the ``_do_poll`` milestones block (Issue #137).
    The milestones are re-derived from session counters each poll — no DB
    table needed. Returns a list of {"tier", "label", "value"} dicts.
    """
    milestones = []
    try:
        sc = timeline_state["session_share_count"]
        milestones_def = [
            (sc >= 100, "BRONZE", f"{sc} shares this session"),
            (sc >= 1000, "SILVER", f"{sc:,} shares this session"),
            (sc >= 10000, "GOLD", f"{sc:,} shares this session"),
            (
                worker and parse_diff_to_float(worker.get("bestDifficulty", "")) >= 1e9,
                "BRONZE",
                "best diff ≥ 1 G",
            ),
            (
                worker
                and parse_diff_to_float(worker.get("bestDifficulty", "")) >= 1e12,
                "SILVER",
                "best diff ≥ 1 T",
            ),
            (
                worker
                and parse_diff_to_float(worker.get("bestDifficulty", "")) >= 1e15,
                "GOLD",
                "best diff ≥ 1 P",
            ),
            (
                worker and safe_int(worker.get("uptime", 0)) >= 86400,
                "BRONZE",
                "uptime ≥ 1 day",
            ),
            (
                worker and safe_int(worker.get("uptime", 0)) >= 7 * 86400,
                "SILVER",
                "uptime ≥ 7 days",
            ),
            (
                worker and safe_int(worker.get("uptime", 0)) >= 30 * 86400,
                "GOLD",
                "uptime ≥ 30 days",
            ),
        ]
        for ok, tier, label in milestones_def:
            if ok:
                milestones.append({"tier": tier, "label": label, "value": label})
    except Exception:
        pass
    return milestones


def compute_event_stats(timeline_state, now):
    """Session + rolling event stats (pure base shape).

    Verbatim extraction of the ``_do_poll`` event-stats head (Issue #137).
    Returns ``(event_stats, hour_ago, day_ago)`` — the DB-backed counts
    (shares_last_hour/day, best_diffs_last_day) are computed by the caller
    and merged via ``event_stats.update`` to keep this function network/DB
    free and unit-testable.
    """
    hour_ago = now - 3600
    day_ago = now - 86400
    session_share_count = timeline_state["session_share_count"]
    session_best_bumps = timeline_state["session_best_diff_bumps"]
    sph = 0.0
    hist = timeline_state["share_submit_history"]
    if len(hist) >= 2 and (hist[-1] - hist[0]) > 0:
        sph = (len(hist) - 1) * (3600.0 / (hist[-1] - hist[0]))
    event_stats = {
        "session_share_count": session_share_count,
        "session_best_diff_bumps": session_best_bumps,
        "rolling_shares_per_hour": round(sph, 2),
        "last_submit_ts": timeline_state["last_submit_ts"],
        "last_share_age_s": (
            (now - timeline_state["last_submit_ts"])
            if timeline_state["last_submit_ts"]
            else None
        ),
    }
    return event_stats, hour_ago, day_ago
