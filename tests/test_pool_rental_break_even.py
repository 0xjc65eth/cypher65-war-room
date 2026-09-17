"""
Unit tests for helpers.compute_pool_rental_break_even — the pool/rental cost
model + break-even math of the profitability pipeline.

Locks the formulas against regression:
  - rental cost/day = ths × rental_usd_per_th_day   (cost_mode='rental')
  - power  cost/day = (watts / 1000) × 24 × $/kWh    (cost_mode='power')
  - cost/day        = rental + power (one branch active, mirroring app.py)
  - break_even_rental_usd_per_th_day = (pool_net_btc_per_day × btc_usd) / ths
      (only when cost_mode == 'rental' AND a BTC price exists)
  - breakeven_cost_per_th_day = same figure, same condition

Pure numerical verification — no DB, no Flask, no HTTP.
See tests/test_solo_probability.py + tests/test_lender_probability.py for the
companion approaches.

Issue #613 (MF-003/MF-004): the second half of this file exercises the FULL
formula chain (TH/s, reward, fees, BTC/USD, fixed costs) through
services.poll_compute.compute_profitability — the caller whose payload the UI
actually reads — locking the contracted rounding and the explicit
unavailability (MF-004: indisponível, nunca estimado; indisponível ≠ 0).
"""

import sys

import pytest

from helpers import compute_pool_rental_break_even

sys.path.insert(0, ".")

from services.poll_compute import compute_profitability  # noqa: E402


# ══════════════════════════════════════════════════════════════════════
# Known-value lock
# ══════════════════════════════════════════════════════════════════════

class TestKnownValues:
    """Hand-computed scenario: 10 TH, pool net 0.0005 BTC/d, BTC = $60,000.

    Break-even = (0.0005 × 60000) / 10 = $3.0 per TH/day (in all modes).
    Rental cost (rate $5/TH/d) = 10 × 5 = $50/d.
    Power cost (3000 W @ $0.10/kWh) = (3000/1000)×24×0.10 = $7.2/d.
    """

    def test_breakeven_in_none_mode(self):
        out = compute_pool_rental_break_even(
            ths=10.0, pool_net_btc_per_day=0.0005, btc_usd=60000.0,
            cost_mode="none",
        )
        # costs zero in 'none' mode
        assert out["rental_cost_per_day"] == pytest.approx(0.0, abs=1e-9)
        assert out["power_cost_per_day"] == pytest.approx(0.0, abs=1e-9)
        assert out["cost_per_day"] == pytest.approx(0.0, abs=1e-9)
        # general break-even always computed
        assert out["breakeven_cost_per_th_day"] == pytest.approx(3.0, rel=1e-4)
        # rental-specific break-even only for cost_mode='rental'
        assert out["break_even_rental_usd_per_th_day"] is None

    def test_rental_mode_cost_and_break_even(self):
        out = compute_pool_rental_break_even(
            ths=10.0, pool_net_btc_per_day=0.0005, btc_usd=60000.0,
            cost_mode="rental", rental_usd_per_th_day=5.0,
        )
        assert out["rental_cost_per_day"] == pytest.approx(50.0, rel=1e-4)
        assert out["cost_per_day"] == pytest.approx(50.0, rel=1e-4)
        assert out["break_even_rental_usd_per_th_day"] == pytest.approx(3.0, rel=1e-4)
        assert out["breakeven_cost_per_th_day"] == pytest.approx(3.0, rel=1e-4)

    def test_power_mode_cost(self):
        out = compute_pool_rental_break_even(
            ths=10.0, pool_net_btc_per_day=0.0005, btc_usd=60000.0,
            cost_mode="power", power_watts=3000.0, power_kwh_usd=0.10,
        )
        assert out["power_cost_per_day"] == pytest.approx(7.2, rel=1e-4)
        assert out["cost_per_day"] == pytest.approx(7.2, rel=1e-4)
        # general break-even still computed; rental one stays None
        assert out["breakeven_cost_per_th_day"] == pytest.approx(3.0, rel=1e-4)
        assert out["break_even_rental_usd_per_th_day"] is None


# ══════════════════════════════════════════════════════════════════════
# Insufficient-data guards
# ══════════════════════════════════════════════════════════════════════

class TestInsufficient:
    def test_zero_ths_returns_none_break_even(self):
        out = compute_pool_rental_break_even(
            ths=0.0, pool_net_btc_per_day=0.0005, btc_usd=60000.0,
            cost_mode="rental", rental_usd_per_th_day=5.0,
        )
        assert out["breakeven_cost_per_th_day"] is None
        assert out["break_even_rental_usd_per_th_day"] is None
        # cost still computed from ths=0 → 0
        assert out["cost_per_day"] == pytest.approx(0.0, abs=1e-9)

    def test_zero_btc_price_returns_none_break_even(self):
        out = compute_pool_rental_break_even(
            ths=10.0, pool_net_btc_per_day=0.0005, btc_usd=0.0,
            cost_mode="rental", rental_usd_per_th_day=5.0,
        )
        assert out["breakeven_cost_per_th_day"] is None
        assert out["break_even_rental_usd_per_th_day"] is None
        # cost still computed (independent of BTC price)
        assert out["cost_per_day"] == pytest.approx(50.0, rel=1e-4)

    def test_negative_values_safe(self):
        out = compute_pool_rental_break_even(
            ths=-5.0, pool_net_btc_per_day=-0.5, btc_usd=-1.0,
            cost_mode="rental", rental_usd_per_th_day=-2.0,
        )
        # ths <= 0 → break-evens None; cost math guarded (no crash)
        assert out["breakeven_cost_per_th_day"] is None
        assert out["break_even_rental_usd_per_th_day"] is None

    def test_none_values_safe(self):
        out = compute_pool_rental_break_even(
            ths=None, pool_net_btc_per_day=None, btc_usd=None,
            cost_mode=None, rental_usd_per_th_day=None,
            power_watts=None, power_kwh_usd=None,
        )
        assert out["cost_per_day"] == pytest.approx(0.0, abs=1e-9)
        assert out["breakeven_cost_per_th_day"] is None
        assert out["break_even_rental_usd_per_th_day"] is None

    def test_unknown_cost_mode_treated_as_none(self):
        out = compute_pool_rental_break_even(
            ths=10.0, pool_net_btc_per_day=0.0005, btc_usd=60000.0,
            cost_mode="bogus", rental_usd_per_th_day=5.0, power_watts=3000.0,
        )
        # neither rental nor power branch applies → zero cost, breakeven still OK
        assert out["cost_per_day"] == pytest.approx(0.0, abs=1e-9)
        assert out["breakeven_cost_per_th_day"] == pytest.approx(3.0, rel=1e-4)


# ══════════════════════════════════════════════════════════════════════
# Issue #613 · MF-003: full-formula vectors (TH/s, reward, fees, BTC/USD,
# fixed costs) through services.poll_compute.compute_profitability — the
# caller whose payload the UI actually reads. Locks the contracted
# ROUNDING, not just the raw value.
# ══════════════════════════════════════════════════════════════════════


def _prices(usd=100000.0, brl=550000.0):
    return {"USD": usd, "BRL": brl, "EUR": 92000, "GBP": 79000,
            "JPY": 15000000, "KRW": 140000000, "CNY": 720000}


def _settings(usd=100000.0, **over):
    s = {
        "cost_mode": "rental", "rental_usd_per_th_day": 0.02,
        "power_kwh_usd": 0.0, "power_watts": 0,
        "btc_block_reward": 3.125, "btc_avg_tx_fee": 0.05,
        "pool_fee_pct": 1.5, "orphan_rate_pct": 0.5,
        "active_currency": "USD",
    }
    s.update(over)
    return s


class TestFullFormulaVector:
    """Hand-computed scenario: 100 TH, 5 EH/s network, reward 3.125+0.05,
    pool fee 1.5%, orphan 0.5%, rental $0.02/TH/d, BTC=$100k.

    share       = 100e12 / 5e18      = 2e-5
    gross       = 2e-5 × 144 × 3.175  = 0.009144 BTC/d
    pool_net    = gross × 0.985 × 0.995 = 0.0089618058 BTC/d
    cost        = 100 × 0.02          = $2.00/d
    pool_net_usd= 0.0089618058×1e5-2  = $894.18058/d
    breakeven   = 0.0089618058×1e5/100 = $8.9618058/TH/d
    """

    WORKER = {"hashrate": 100e12}
    NET = 5e18

    def test_btc_btc_and_gross_lock(self):
        p, ch, nh = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        assert ch == 100e12 and nh == 5e18
        assert p["gross_btc_per_day"] == pytest.approx(0.009144, abs=1e-12)
        # round(·,8) of the exact 0.0089618058 → 0.00896181 (9th digit is 5)
        assert p["net_btc_per_day_pool"] == round(2e-5 * 144 * 3.175 * 0.985 * 0.995, 8)

    def test_contracted_rounding_lock(self):
        """The payload rounds BTC to 8 and USD to 4 — lock the ROUNDED value,
        not just the raw one (MF-003: 'arredondamento contratado')."""
        p, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        raw_pool_net = 2e-5 * 144 * 3.175 * 0.985 * 0.995
        assert p["net_btc_per_day_pool"] == round(raw_pool_net, 8)
        assert p["gross_btc_per_day"] == round(2e-5 * 144 * 3.175, 8)
        assert p["pool_net_usd_per_day"] == round(raw_pool_net * 1e5 - 2.0, 4)
        assert p["cost_per_day_usd"] == round(2.0, 4)

    def test_cost_and_breakeven_via_callers_helper(self):
        """compute_profitability must route the cost model through
        helpers.compute_pool_rental_break_even — same contract, same numbers."""
        p, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        assert p["cost_mode"] == "rental"
        assert p["cost_model_configured"] is True
        assert p["cost_per_day_usd"] == pytest.approx(2.0, abs=1e-9)
        be = 0.0089618058 * 1e5 / 100.0
        assert p["breakeven_cost_per_th_day"] == pytest.approx(round(be, 4), abs=1e-9)
        # rental mode is the ONLY mode that emits the rental break-even
        assert p["break_even_rental_usd_per_th_day"] == pytest.approx(round(be, 4), abs=1e-9)

    def test_fiat_follows_contracted_rounding_4(self):
        """fiat_* fields are round(btc × quote, 4) — exact decimal check."""
        p, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        pool_net = 2e-5 * 144 * 3.175 * 0.985 * 0.995
        assert p["fiat_per_day_pool"]["USD"] == round(pool_net * 100000.0, 4)
        assert p["fiat_per_day_pool"]["BRL"] == round(pool_net * 550000.0, 4)
        # windows: 1/7/30 as labeled in the disclaimer
        assert p["fiat_per_week_pool"]["USD"] == round(pool_net * 7 * 100000.0, 4)
        assert p["fiat_per_month_pool"]["USD"] == round(pool_net * 30 * 100000.0, 4)

    def test_power_mode_vector(self):
        """3000 W @ $0.10/kWh = $7.20/d — cost enters the net USD, breakeven
        per-TH reflects income only (power cost is NOT divided by ths here)."""
        p, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None},
            _settings(cost_mode="power", power_watts=3000, power_kwh_usd=0.10),
        )
        assert p["cost_per_day_usd"] == pytest.approx(7.2, abs=1e-9)
        assert "3000W" in p["cost_label"]
        pool_net = 2e-5 * 144 * 3.175 * 0.985 * 0.995
        assert p["pool_net_usd_per_day"] == round(pool_net * 1e5 - 7.2, 4)
        # power mode does NOT emit the rental-specific break-even
        assert p["break_even_rental_usd_per_th_day"] is None
        assert p["breakeven_cost_per_th_day"] == pytest.approx(
            round(pool_net * 1e5 / 100.0, 4), abs=1e-9)


class TestFeeSensitivity:
    """Fees/reward/btc price must actually move the numbers (guards a
    constant-folded or hard-coded payload passing the fixed vectors)."""

    WORKER = {"hashrate": 100e12}
    NET = 5e18

    def test_pool_fee_changes_net_btc(self):
        base, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        higher, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(pool_fee_pct=3.0),
        )
        assert higher["net_btc_per_day_pool"] < base["net_btc_per_day_pool"]
        # lock against the RAW formula (base is rounded to 8 — multiplying the
        # rounded value would drift the tolerance beyond the rounding itself)
        assert higher["net_btc_per_day_pool"] == round(0.009144 * (1 - 0.03) * 0.995, 8)

    def test_btc_price_moves_usd_but_not_btc(self):
        base, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(usd=100000.0), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        doubled, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(usd=200000.0), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        assert base["net_btc_per_day_pool"] == doubled["net_btc_per_day_pool"]
        assert doubled["pool_net_usd_per_day"] == pytest.approx(
            base["pool_net_usd_per_day"] * 2 + 2.0, rel=1e-9)


class TestInsufficientDataNoEstimates:
    """Issue #613 · MF-004: missing inputs must yield EXPLICIT unavailability —
    never a zero masquerading as money and never an invented estimate.

    The 'no estimates' criterion: fiat fields keyed to a currency WITHOUT a
    quote come out null (unknown), never 0.0 (known-zero) and never a number
    derived from a price the system does not have.
    """

    WORKER = {"hashrate": 100e12}
    NET = 5e18

    def test_missing_fiat_quote_is_null_not_zero(self):
        """BRL quote missing → fiat BRL = None (unavailable), while USD (with
        quote) still computes. None is 'unknown', 0.0 would be a lie."""
        prices = _prices()
        prices["BRL"] = None
        p, _, _ = compute_profitability(
            self.WORKER, self.NET, prices, {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        assert p["fiat_per_day_pool"]["BRL"] is None
        assert p["fiat_per_day_pool"]["USD"] is not None

    def test_no_btc_price_fiat_fields_are_unavailable_not_estimated(self):
        """No USD quote at all → every USD field is None. The BTC math (which
        does not need a price) still holds; break-even needs the price and is
        declared unavailable, never estimated."""
        p, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(usd=None), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        pool_net = 2e-5 * 144 * 3.175 * 0.985 * 0.995
        assert p["net_btc_per_day_pool"] == round(pool_net, 8)  # price-free math holds
        assert p["pool_net_usd_per_day"] is None
        assert p["pool_net_usd_per_month"] is None
        assert p["rental_net_usd_per_day"] is None
        assert p["rental_net_usd_per_month"] is None
        assert p["break_even_rental_usd_per_th_day"] is None
        assert p["breakeven_cost_per_th_day"] is None

    def test_zero_network_hashrate_disables_rental_btc_fields(self):
        """net=0 → unavailable branch: cur_hr is still hoisted (gauge), the
        payload declares the reason, and rental BTC fields are absent
        (never defaulted to 0 — absence is the honest signal)."""
        p, ch, nh = compute_profitability(
            self.WORKER, 0, _prices(), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        assert ch == 100e12 and nh == 0.0
        assert p["unavailable_reason"] == "no hashrate or network hashrate"
        assert "net_btc_per_day_rental" not in p
        assert "gross_btc_per_day" not in p

    def test_zero_worker_hashrate_same_unavailable_branch(self):
        p, ch, _ = compute_profitability(
            {"hashrate": 0}, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        assert ch == 0.0
        assert p["unavailable_reason"] == "no hashrate or network hashrate"

    def test_zero_cost_inputs_no_division_and_no_estimate(self):
        """MF-004 third input: cost 0 (rental rate 0, or 0 W) → cost_per_day
        is exactly 0 and the USD net equals the gross conversion — no
        division by zero anywhere on the path."""
        pool_net = 2e-5 * 144 * 3.175 * 0.985 * 0.995
        p, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None},
            _settings(cost_mode="rental", rental_usd_per_th_day=0.0),
        )
        assert p["cost_per_day_usd"] == 0.0
        assert p["pool_net_usd_per_day"] == round(pool_net * 1e5, 4)
        p2, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None},
            _settings(cost_mode="power", power_watts=0, power_kwh_usd=0.10),
        )
        assert p2["cost_per_day_usd"] == 0.0
        assert p2["pool_net_usd_per_day"] == round(pool_net * 1e5, 4)

    def test_stale_price_cache_used_for_usd_never_invented(self):
        """Live quote gone but the price cache holds the last REAL quote →
        the lender USD rate uses it (stale-while-revalidate). An EMPTY cache
        → None. Neither path estimates."""
        class _Offer:
            price_per_th_day = 2e-4
        stale, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(usd=None), {"offers": [_Offer()]},
            1e-8, {"ts": 100, "data": {"bitcoin": {"usd": 90000}}}, _settings(),
        )
        assert stale["lender_market_rate_usd_per_th_day"] == pytest.approx(18.0, rel=1e-6)
        cold, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(usd=None), {"offers": [_Offer()]},
            1e-8, {"ts": 0, "data": None}, _settings(),
        )
        assert cold["lender_market_rate_usd_per_th_day"] is None

    def test_payload_with_full_data_is_json_serializable_and_finite(self):
        """The happy-path payload must serialize cleanly (MF-002 contract
        extended to the MF-003 surface): no NaN/Infinity anywhere."""
        import json
        import math

        def _check(node):
            if isinstance(node, float):
                assert math.isfinite(node), f"non-finite: {node}"
            elif isinstance(node, dict):
                for v in node.values():
                    _check(v)
            elif isinstance(node, (list, tuple)):
                for v in node:
                    _check(v)

        p, _, _ = compute_profitability(
            self.WORKER, self.NET, _prices(), {}, 1e-8,
            {"ts": 0, "data": None}, _settings(),
        )
        _check(p)
        json.dumps(p, allow_nan=False)
