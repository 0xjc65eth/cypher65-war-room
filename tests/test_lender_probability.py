"""
Unit tests for helpers.compute_lender_profitability — Scenario D of the
profitability pipeline: rent OUT your own hashrate vs mining directly.

Locks the formulas against regression:
  - revenue_btc = ths × market_btc_per_th_day
  - net_btc     = revenue − power cost (in BTC)
  - net_usd     = net_btc × btc_usd
  - vs_mining   = lender net USD − mining net USD (positive → lease)
  - recommendation = lease | mine | equal | insufficient
  - breakeven rate (BTC/TH/d) = (mining_btc + power_btc) / ths

Pure numerical verification — no DB, no Flask, no HTTP.
See tests/test_solo_probability.py for the companion approach.
"""

import pytest

from helpers import compute_lender_profitability


# ══════════════════════════════════════════════════════════════════════
# Known-value lock
# ══════════════════════════════════════════════════════════════════════

class TestKnownValues:
    """Hand-computed scenario: 10 TH, rate 0.000010 BTC/TH/d, power $2.4/d,
    mining net 0.000050 BTC/d, BTC = $60,000.

    Power is paid in BOTH scenarios (the rigs run either way), so it cancels
    in the comparison: lease net − mine net = revenue − mining income.
    """

    def test_revenue_and_net_btc(self):
        out = compute_lender_profitability(
            ths=10.0,
            market_btc_per_th_day=0.000010,
            power_cost_usd_per_day=2.4,
            pool_net_btc_per_day=0.000050,
            btc_usd=60000.0,
        )
        # revenue = 10 × 1e-5 = 1e-4 BTC/d; power = 2.4/60000 = 4e-5 BTC/d
        assert out["lender_revenue_btc_per_day"] == pytest.approx(1e-4, rel=1e-6)
        assert out["lender_net_btc_per_day"] == pytest.approx(6e-5, rel=1e-6)
        assert out["lender_power_cost_usd_per_day"] == pytest.approx(2.4, rel=1e-6)

    def test_net_usd_and_vs_mining(self):
        out = compute_lender_profitability(
            ths=10.0,
            market_btc_per_th_day=0.000010,
            power_cost_usd_per_day=2.4,
            pool_net_btc_per_day=0.000050,
            btc_usd=60000.0,
        )
        # lease net  = (1e-4 − 4e-5) × 60000 = $3.6/d
        # mine  net  = (5e-5 − 4e-5) × 60000 = $0.6/d
        # vs_mining  = 3.6 − 0.6 = $3.0/d (power cancels → revenue−mining)
        assert out["lender_net_usd_per_day"] == pytest.approx(3.6, rel=1e-4)
        assert out["lender_mine_net_usd_per_day"] == pytest.approx(0.6, rel=1e-4)
        assert out["lender_vs_mining_usd_per_day"] == pytest.approx(3.0, rel=1e-4)
        assert out["lender_recommendation"] == "lease"

    def test_breakeven_rate(self):
        out = compute_lender_profitability(
            ths=10.0,
            market_btc_per_th_day=0.000010,
            power_cost_usd_per_day=2.4,
            pool_net_btc_per_day=0.000050,
            btc_usd=60000.0,
        )
        # Power cancels → breakeven = mining income / ths = 5e-5 / 10 = 5e-6
        assert out["lender_breakeven_btc_per_th_day"] == pytest.approx(5e-6, rel=1e-6)
        assert out["lender_breakeven_usd_per_th_day"] == pytest.approx(0.30, rel=1e-4)


# ══════════════════════════════════════════════════════════════════════
# Recommendation matrix
# ══════════════════════════════════════════════════════════════════════

class TestRecommendation:
    def test_lease_when_rate_beats_mining(self):
        out = compute_lender_profitability(
            ths=10.0, market_btc_per_th_day=0.000020,
            power_cost_usd_per_day=2.4, pool_net_btc_per_day=0.000050,
            btc_usd=60000.0,
        )
        assert out["lender_recommendation"] == "lease"
        assert out["lender_vs_mining_usd_per_day"] > 0

    def test_mine_when_rate_below_mining(self):
        out = compute_lender_profitability(
            ths=10.0, market_btc_per_th_day=0.000004,
            power_cost_usd_per_day=2.4, pool_net_btc_per_day=0.000050,
            btc_usd=60000.0,
        )
        assert out["lender_recommendation"] == "mine"
        assert out["lender_vs_mining_usd_per_day"] < 0

    def test_equal_at_breakeven(self):
        out = compute_lender_profitability(
            ths=10.0, market_btc_per_th_day=5e-6,
            power_cost_usd_per_day=2.4, pool_net_btc_per_day=0.000050,
            btc_usd=60000.0,
        )
        assert out["lender_recommendation"] == "equal"
        assert abs(out["lender_vs_mining_usd_per_day"]) < 0.005


# ══════════════════════════════════════════════════════════════════════
# Insufficient-data guards
# ══════════════════════════════════════════════════════════════════════

class TestInsufficient:
    def test_zero_thashrate(self):
        out = compute_lender_profitability(
            ths=0.0, market_btc_per_th_day=0.000010,
            power_cost_usd_per_day=2.4, pool_net_btc_per_day=0.000050,
            btc_usd=60000.0,
        )
        assert out["lender_recommendation"] == "insufficient"
        assert out["lender_net_btc_per_day"] is None

    def test_zero_market_rate(self):
        out = compute_lender_profitability(
            ths=10.0, market_btc_per_th_day=0.0,
            power_cost_usd_per_day=2.4, pool_net_btc_per_day=0.000050,
            btc_usd=60000.0,
        )
        assert out["lender_recommendation"] == "insufficient"
        assert out["lender_net_btc_per_day"] is None

    def test_negative_values_safe(self):
        out = compute_lender_profitability(
            ths=-5.0, market_btc_per_th_day=-1.0,
            power_cost_usd_per_day=-1.0, pool_net_btc_per_day=-1.0,
            btc_usd=-1.0,
        )
        assert out["lender_recommendation"] == "insufficient"

    def test_none_values_safe(self):
        out = compute_lender_profitability(
            ths=None, market_btc_per_th_day=None,
            power_cost_usd_per_day=None, pool_net_btc_per_day=None,
            btc_usd=None,
        )
        assert out["lender_recommendation"] == "insufficient"

    def test_no_btc_price_returns_usd_none_but_btc_net(self):
        """Without a BTC price, USD fields are None but BTC math still works."""
        out = compute_lender_profitability(
            ths=10.0, market_btc_per_th_day=0.000010,
            power_cost_usd_per_day=0.0, pool_net_btc_per_day=0.000050,
            btc_usd=0.0,
        )
        assert out["lender_net_btc_per_day"] == pytest.approx(1e-4, rel=1e-6)
        assert out["lender_net_usd_per_day"] is None
        assert out["lender_recommendation"] == "insufficient"


# ══════════════════════════════════════════════════════════════════════
# Zero-cost sanity
# ══════════════════════════════════════════════════════════════════════

class TestZeroCost:
    def test_no_power_cost_net_equals_revenue(self):
        out = compute_lender_profitability(
            ths=5.0, market_btc_per_th_day=0.000002,
            power_cost_usd_per_day=0.0, pool_net_btc_per_day=0.000001,
            btc_usd=100000.0,
        )
        assert out["lender_net_btc_per_day"] == pytest.approx(1e-5, rel=1e-6)
        assert out["lender_net_usd_per_day"] == pytest.approx(1.0, rel=1e-4)
        # net 1.0 vs mining 0.1 → lease
        assert out["lender_recommendation"] == "lease"
