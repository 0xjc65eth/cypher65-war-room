"""
CYPHER65 // P0-2 — Hash Market Decision Matrix
===============================================
Unit tests for helpers.build_decision_matrix() — the pure aggregation that
compares solo vs pool vs lease for the Decision Matrix panel in the market
module. Hermetic: no network, no DB, no app import needed.
"""
import pytest

from helpers import build_decision_matrix


class TestDecisionMatrix:
    def test_pool_wins_when_higher_usd(self):
        dm = build_decision_matrix(
            pool_net_usd_per_day=12.0,
            lender_net_usd_per_day=8.0,
            solo_expected_time_days=5000.0,
            solo_p_year_pct=1.5,
            lender_recommendation="lease",
            breakeven_cost_per_th_day=0.0004,
        )
        assert dm["best_option"] == "pool"
        assert dm["rows"]["pool"]["net_usd_per_day"] == 12.0
        assert dm["rows"]["lease"]["net_usd_per_day"] == 8.0
        assert dm["rows"]["solo"]["expected_time_days"] == 5000.0
        assert dm["breakeven_cost_per_th_day"] == 0.0004

    def test_lease_wins_when_higher_usd(self):
        dm = build_decision_matrix(
            pool_net_usd_per_day=8.0,
            lender_net_usd_per_day=15.0,
            solo_expected_time_days=900.0,
            solo_p_year_pct=8.0,
        )
        assert dm["best_option"] == "lease"
        assert "lease" in dm["recommendation"].lower()

    def test_solo_fallback_when_no_deterministic_data(self):
        dm = build_decision_matrix(solo_expected_time_days=200.0, solo_p_year_pct=20.0)
        assert dm["best_option"] == "solo"
        assert "200" in dm["recommendation"]

    def test_insufficient_when_nothing_available(self):
        dm = build_decision_matrix()
        assert dm["best_option"] == "insufficient"
        assert "not enough data" in dm["recommendation"].lower()

    def test_pool_only(self):
        dm = build_decision_matrix(pool_net_usd_per_day=5.0)
        assert dm["best_option"] == "pool"

    def test_lease_only(self):
        dm = build_decision_matrix(lender_net_usd_per_day=7.0)
        assert dm["best_option"] == "lease"

    def test_tie_breaks_to_pool(self):
        dm = build_decision_matrix(pool_net_usd_per_day=10.0, lender_net_usd_per_day=10.0)
        assert dm["best_option"] == "pool"

    def test_non_numeric_inputs_never_raise(self):
        dm = build_decision_matrix(
            pool_net_usd_per_day="nope",
            lender_net_usd_per_day=None,
            solo_expected_time_days=float("inf"),
            solo_p_year_pct=None,
            lender_recommendation=12345,
        )
        assert dm["best_option"] in ("insufficient", "solo")
        assert dm["rows"]["pool"]["net_usd_per_day"] is None

    def test_negative_usd_treated_as_numeric(self):
        # A loss-making mode is still a real number (could be a legit negative).
        dm = build_decision_matrix(pool_net_usd_per_day=-3.0, lender_net_usd_per_day=2.0)
        assert dm["best_option"] == "lease"
