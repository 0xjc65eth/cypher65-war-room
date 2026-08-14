"""Hermetic tests for services.poll_compute (Issue #135).

These are the pure computation blocks extracted VERBATIM from
app._do_poll — the ~1260-line poll monolith that previously had zero
unit coverage because it only runs live with real network access. The
tests pin the exact formulas so future edits to the poll math are safe.
"""
import sys

import pytest

sys.path.insert(0, ".")

from services.poll_compute import (  # noqa: E402
    derive_network_values, parse_mempool_fees, merge_btc_quotes,
    compute_halving_countdown, build_all_workers, select_primary_worker,
    dedup_workers, compute_share_calc, compute_luck_estimate, fiat_convert,
)


# ── derive_network_values ───────────────────────────────────────────────────

def test_derive_network_ghs_scaled_to_hs():
    """blockchain.info /q/hashrate returns GH/s — multiply by 1e9 for H/s."""
    diff, hr = derive_network_values(108_000_000_000_000.0, 700_000.0)
    assert diff == 108_000_000_000_000.0
    assert hr == 700_000.0 * 1e9


def test_derive_network_none_hashrate_derives_from_difficulty():
    """No hashrate source → derive from difficulty * 2^32 / 600."""
    diff, hr = derive_network_values(108_000_000_000_000.0, None)
    assert hr == 108_000_000_000_000.0 * (2 ** 32) / 600


def test_derive_network_zero_hashrate_falls_back_to_formula():
    """A hashrate of 0 (not just None) triggers the formula fallback too."""
    diff, hr = derive_network_values(108_000_000_000_000.0, 0)
    assert hr == 108_000_000_000_000.0 * (2 ** 32) / 600


def test_derive_network_both_missing():
    diff, hr = derive_network_values(None, None)
    assert diff is None
    assert hr is None


# ── parse_mempool_fees ──────────────────────────────────────────────────────

def test_mempool_fees_full_payload_keeps_numeric_fields():
    out = parse_mempool_fees({"fastestFee": 12, "halfHourFee": 8,
                              "hourFee": 5, "minimumFee": 1, "economyFee": 2})
    assert out == {"fastestFee": 12, "halfHourFee": 8,
                   "hourFee": 5, "minimumFee": 1, "economyFee": 2}


def test_mempool_fees_ignores_non_numeric_and_missing_keys():
    out = parse_mempool_fees({"fastestFee": "fast", "hourFee": None,
                              "economyFee": 3})
    # 'fast' string and None are dropped; only numeric survive.
    assert out == {"economyFee": 3}


def test_mempool_fees_empty_falls_back_to_none_shape():
    out = parse_mempool_fees({})
    assert out == {"fastestFee": None, "halfHourFee": None, "hourFee": None}
    out2 = parse_mempool_fees(None)
    assert out2 == {"fastestFee": None, "halfHourFee": None, "hourFee": None}


# ── merge_btc_quotes ────────────────────────────────────────────────────────

def test_merge_btc_coingecko_only():
    cg = {"bitcoin": {"usd": 100000, "brl": 550000, "eur": 92000,
                      "jpy": 15000000, "krw": 140000000, "cny": 720000}}
    out = merge_btc_quotes(cg, None, None)
    assert out["usd"] == 100000
    assert out["brl"] == 550000
    assert out["eur"] == 92000
    assert out["jpy"] == 15000000
    assert out["krw"] == 140000000
    assert out["cny"] == 720000


def test_merge_btc_binance_wins_for_usd_and_brl():
    cg = {"bitcoin": {"usd": 99999, "brl": 550000}}
    out = merge_btc_quotes(cg, {"price": "100500"}, {"price": "580000"})
    assert out["usd"] == 100500.0   # Binance real-time wins
    assert out["brl"] == 580000.0


def test_merge_btc_binance_bad_values_ignored():
    cg = {"bitcoin": {"usd": 100000}}
    out = merge_btc_quotes(cg, {"price": "not-a-number"}, {"price": None})
    assert out["usd"] == 100000
    assert out["brl"] is None


def test_merge_btc_binance_brl_bad_value_ignored():
    """Non-numeric BRL price raises inside the parse guard — never propagates."""
    cg = {"bitcoin": {"usd": 100000}}
    out = merge_btc_quotes(cg, {"price": "100000"}, {"price": "nope"})
    assert out["usd"] == 100000.0
    assert out["brl"] is None


def test_merge_btc_none_everywhere():
    out = merge_btc_quotes(None, None, None)
    assert out == {"usd": None, "brl": None, "eur": None, "gbp": None,
                   "jpy": None, "krw": None, "cny": None}


# ── compute_halving_countdown ───────────────────────────────────────────────

def test_halving_countdown_known_height():
    h = compute_halving_countdown(1050000)
    assert h["next_height"] == 1260000
    assert h["blocks_remaining"] == 210000
    assert h["estimated_seconds_remaining"] == 126000000
    assert h["estimated_days_remaining"] == pytest.approx(1458.3333)
    assert h["current_reward_btc"] == 1.5625  # 50 * 0.5^5
    assert h["next_reward_btc"] == 0.78125
    assert h["epoch_label"] == "#6/33"


def test_halving_countdown_unknown_height_returns_base_shape():
    h = compute_halving_countdown(None)
    assert h["height"] is None
    assert h["blocks_remaining"] is None
    assert h["next_reward_btc"] is None
    assert h["epoch_label"] == ""


# ── build_all_workers / select_primary_worker / dedup_workers ───────────────

def _user(workers):
    return {"workerData": workers}


def test_build_all_workers_marks_primary_by_name():
    workers = [{"name": "MAIN", "id": "1", "hashrate": 100},
               {"name": "backup", "id": "2", "hashrate": 50}]
    all_w, worker, idx = build_all_workers(_user(workers), "main")
    assert len(all_w) == 2
    assert all_w[0]["is_primary"] is True  # name match (case-insensitive)
    assert all_w[1]["is_primary"] is False
    assert worker == workers[0]
    assert idx == 0


def test_build_all_workers_marks_primary_by_id():
    workers = [{"name": "x", "id": "W-42", "hashrate": 100}]
    all_w, worker, idx = build_all_workers(_user(workers), "w-42")
    assert all_w[0]["is_primary"] is True
    assert worker == workers[0]
    assert idx == 0


def test_build_all_workers_no_match_and_no_worker_data():
    all_w, worker, idx = build_all_workers(_user([{"name": "a", "id": "1"}]), "nope")
    assert all_w[0]["is_primary"] is False
    assert worker is None and idx is None
    all_w2, worker2, idx2 = build_all_workers({}, "nope")
    assert all_w2 == [] and worker2 is None and idx2 is None


def test_select_primary_worker_best_hashrate_wins():
    workers = [{"name": "a", "hashrate": 10}, {"name": "b", "hashrate": 500},
               {"name": "c", "hashrate": 200}]
    all_w, _, _ = build_all_workers(_user(workers), "nope")
    all_w, worker, idx = select_primary_worker(_user(workers), all_w)
    assert idx == 1
    assert worker == workers[1]
    assert all_w[1]["is_primary"] is True


def test_select_primary_worker_all_idle_picks_first():
    workers = [{"name": "a", "hashrate": 0, "bestDifficulty": "87T"},
               {"name": "b", "hashrate": 0}]
    all_w, _, _ = build_all_workers(_user(workers), "nope")
    all_w, worker, idx = select_primary_worker(_user(workers), all_w)
    assert idx == 0
    assert worker == workers[0]
    assert all_w[0]["is_primary"] is True


def test_select_primary_worker_empty_noop():
    all_w, worker, idx = select_primary_worker(_user([]), [])
    assert all_w == [] and worker is None and idx is None


def test_dedup_workers_merges_case_insensitive_keeping_highest_hr():
    entries = [
        {"name": "CYPHERORDIFUTURE", "hashrate": 100},
        {"name": "cypherordifuture", "hashrate": 400},  # active wins
        {"name": "other", "hashrate": 50},
    ]
    out = dedup_workers(entries)
    assert len(out) == 2
    by_name = {e["name"]: e["hashrate"] for e in out}
    assert by_name.get("cypherordifuture") == 400
    assert by_name.get("other") == 50


def test_dedup_workers_keeps_empty_names_verbatim():
    entries = [{"name": "", "hashrate": 1}, {"name": "", "hashrate": 2}]
    out = dedup_workers(entries)
    assert len(out) == 2  # empty names can never be deduped


def test_dedup_workers_empty_input():
    assert dedup_workers([]) == []


# ── compute_share_calc ──────────────────────────────────────────────────────

def test_share_calc_full_payload():
    out = compute_share_calc(
        ts=1000, gap=60, share_diff_raw=1_000_000.0,
        current_difficulty=108_000_000_000_000.0,
        best_diff_str="87.1T", session_share_count=3,
    )
    assert out["ts"] == 1000
    assert out["gap"] == 60
    assert out["share_diff_raw"] == 1_000_000.0
    assert out["hashes_attempted"] == 1_000_000.0 * (2 ** 32)
    assert out["instantaneous_hr_hps"] == pytest.approx(
        (1_000_000.0 * (2 ** 32)) / 60)
    assert out["best_diff_at_time_str"] == "87.1T"
    assert out["best_diff_at_time"] > 0
    assert out["network_diff_at_time"] == 108_000_000_000_000.0
    assert out["session_share_count_at_time"] == 3
    assert "%" in out["p_block_this_share_pct_str"]
    assert out["share_diff_str"]  # formatted


def test_share_calc_empty_best_diff():
    out = compute_share_calc(1, 60, 1.0, 108e12, "", 0)
    assert out["best_diff_at_time"] == 0.0
    assert out["best_diff_at_time_str"] == ""
    # None best_diff behaves like empty (0.0 / None, mirroring the original
    # worker.get() semantics at the call site).
    out2 = compute_share_calc(1, 60, 1.0, 108e12, None, 0)
    assert out2["best_diff_at_time"] == 0.0
    assert out2["best_diff_at_time_str"] is None


# ── compute_luck_estimate ───────────────────────────────────────────────────

def test_luck_estimate_full():
    worker = {"bestDifficulty": "87.1T", "hashrate": 100e12}
    pool = {"highestDifficulty": "900T", "workSinceLastBlock": 5e15,
            "hashrate": 5000e12}
    luck = compute_luck_estimate(worker, pool, 108e12)
    assert luck["pool_work_since_last_block"] == 5e15
    assert luck["worker_share_of_pool_pct"] == pytest.approx(2.0)
    assert luck["fair_share_diff_since_last_block"] == pytest.approx(
        (100e12 / 5000e12) * 5e15)
    assert "pool_luck_pct" in luck
    assert "round_progress_pct" in luck


def test_luck_estimate_empty_inputs():
    assert compute_luck_estimate(None, {}, 1) == {}
    assert compute_luck_estimate({}, None, 1) == {}
    assert compute_luck_estimate({}, {}, None) == {}


def test_luck_estimate_zero_pool_hashrate_no_division_error():
    worker = {"bestDifficulty": "1T", "hashrate": 100e12}
    pool = {"highestDifficulty": "1T", "workSinceLastBlock": 1e15,
            "hashrate": 0}
    luck = compute_luck_estimate(worker, pool, 108e12)
    assert luck["worker_share_of_pool_pct"] == 0
    assert luck["fair_share_diff_since_last_block"] == 0
    # No pool_luck_pct key: the inner guard needs pool_hr truthy.
    assert "pool_luck_pct" not in luck


def test_luck_estimate_inner_guard_exception_is_swallowed():
    """A Decimal difficulty passes the outer math (Decimal / int) but breaks
    the inner float * Decimal — the inner guard swallows it and the base
    shape survives."""
    from decimal import Decimal
    worker = {"bestDifficulty": "1T", "hashrate": 100e12}
    pool = {"highestDifficulty": "1T", "workSinceLastBlock": 1e15,
            "hashrate": 5000e12}
    luck = compute_luck_estimate(worker, pool, Decimal("108e12"))
    assert luck["pool_work_since_last_block"] == 1e15
    assert "pool_luck_pct" not in luck  # inner branch blew up → swallowed


def test_luck_estimate_outer_exception_returns_empty():
    """A non-numeric worker hashrate raises inside the outer try — the
    function degrades to {} instead of propagating."""
    worker = {"bestDifficulty": "1T", "hashrate": "NaN-ish"}
    pool = {"highestDifficulty": "1T", "workSinceLastBlock": 1e15,
            "hashrate": 5000e12}
    assert compute_luck_estimate(worker, pool, 108e12) == {}


# ── fiat_convert ────────────────────────────────────────────────────────────

def test_fiat_convert_rounds_to_4_and_skips_none():
    out = fiat_convert(0.5, {"USD": 100000, "BRL": 550000, "EUR": None})
    assert out == {"USD": 50000.0, "BRL": 275000.0, "EUR": None}


def test_fiat_convert_zero_value():
    assert fiat_convert(0.0, {"USD": 100000}) == {"USD": 0.0}

