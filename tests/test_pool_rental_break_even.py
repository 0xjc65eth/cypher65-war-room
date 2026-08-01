"""
Unit tests for helpers.compute_pool_rental_break_even — the pool/rental cost
model + break-even math of the profitability pipeline.

Locks the formulas against regression:
  - rental cost/day = ths × rental_usd_per_th_day   (cost_mode='rental')
  - power  cost/day = (watts / 1000) × 24 × $/kWh    (cost_mode='power')
  - cost/day        = rental + power (one branch active, mirroring app.py)
  - break_even_rental_usd_per_th_day = (pool_net_btc_per_day × btc_usd) / ths
      (only when cost_mode == 'rental' AND a BTC price exists)
  - breakeven_cost_per_th_day = same figure, always when price + ths > 0

Pure numerical verification — no DB, no Flask, no HTTP.
See tests/test_solo_probability.py + tests/test_lender_probability.py for the
companion approaches.
"""

import pytest

from helpers import compute_pool_rental_break_even


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
