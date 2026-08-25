"""Contracts for mining probabilities and profitability guardrails.

These tests use pure functions only. They pin the calculator to expected-value
math and ensure unrepresentable numeric values cannot become JSON output.
"""

import math

import pytest

from helpers import compute_pool_rental_break_even
from services.probability import calculate_block_probability


def test_block_probability_matches_the_poisson_model_for_a_known_vector():
    """lambda=1 must yield P(>=1)=1-e^-1 and a 10-minute expected interval."""
    result = calculate_block_probability(
        user_hashrate=1.0e15,
        network_hashrate=1.0e15,
        duration_seconds=600,
    )

    assert result["lambda"] == pytest.approx(1.0)
    assert result["expected_blocks"] == pytest.approx(1.0)
    assert result["probability_at_least_one"] == pytest.approx(
        1 - math.exp(-1), abs=1e-6
    )
    assert result["probability_zero"] == pytest.approx(math.exp(-1), abs=1e-6)
    assert result["expected_time_to_block_seconds"] == pytest.approx(600.0)
    assert "NOT A GUARANTEE" in result["note"]


@pytest.mark.parametrize(
    "invalid_value", [0, -1, float("nan"), float("inf"), float("-inf")]
)
def test_block_probability_rejects_zero_negative_and_non_finite_inputs(invalid_value):
    result = calculate_block_probability(
        user_hashrate=invalid_value,
        network_hashrate=1.0e18,
        duration_seconds=3600,
    )

    assert result == {
        "error": "Invalid input parameters",
        "probability_at_least_one": 0.0,
        "probability_zero": 1.0,
        "expected_blocks": 0.0,
    }


def test_block_probability_rejects_overflow_before_it_reaches_the_response():
    """Extreme finite inputs may overflow intermediate math; fail closed."""
    result = calculate_block_probability(
        user_hashrate=1.0e308,
        network_hashrate=1.0e-308,
        duration_seconds=600,
    )

    assert result["error"] == "Invalid input parameters"
    assert all(
        math.isfinite(value) for value in result.values() if isinstance(value, float)
    )


def test_pool_rental_break_even_uses_income_per_th_and_never_divides_by_zero():
    """10 TH, 0.0005 BTC/day and BTC=$60k gives a $3/TH/day break-even."""
    result = compute_pool_rental_break_even(
        ths=10.0,
        pool_net_btc_per_day=0.0005,
        btc_usd=60_000.0,
        cost_mode="rental",
        rental_usd_per_th_day=5.0,
    )

    assert result["rental_cost_per_day"] == pytest.approx(50.0)
    assert result["cost_per_day"] == pytest.approx(50.0)
    assert result["break_even_rental_usd_per_th_day"] == pytest.approx(3.0)
    assert result["breakeven_cost_per_th_day"] == pytest.approx(3.0)

    zero_hashrate = compute_pool_rental_break_even(
        ths=0,
        pool_net_btc_per_day=0.0005,
        btc_usd=60_000.0,
        cost_mode="rental",
        rental_usd_per_th_day=5.0,
    )
    assert zero_hashrate["cost_per_day"] == 0.0
    assert zero_hashrate["break_even_rental_usd_per_th_day"] is None
    assert zero_hashrate["breakeven_cost_per_th_day"] is None
