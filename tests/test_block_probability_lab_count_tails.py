"""Issue #841: independent high-precision count-tail and contract regressions."""

from decimal import Decimal, localcontext
import json
import math

import pytest

from services import block_probability_lab as lab


def decimal_tail(mean: float, minimum_blocks: int) -> Decimal:
    """Independent CDF-complement oracle using 850-digit Decimal arithmetic.

    Unlike production's mode-directed, log-scaled tail, start at probability
    zero and sum the finite CDF from zero. Precision preserves the smallest
    selected tail (approximately 1e-647) before taking its complement.
    """
    with localcontext() as context:
        context.prec = 850
        rate = Decimal.from_float(mean)
        mass = (-rate).exp()
        cumulative = Decimal(0)
        for count in range(minimum_blocks):
            cumulative += mass
            mass *= rate / Decimal(count + 1)
        return +(Decimal(1) - cumulative)


@pytest.mark.parametrize(
    "mean,count",
    [
        (0.0, 0),
        (0.0, 1),
        (0.0, 10000),
        (1e-20, 1),
        (1e-20, 2),
        (1e-20, 10),
        (0.01, 2),
        (0.1, 10),
        (1.0, 2),
        (1.0, 20),
        (2.0, 2),
        (9.9, 10),
        (10.0, 10),
        (10.1, 10),
        (100.0, 90),
        (100.0, 100),
        (100.0, 120),
        (1000.0, 1000),
        (1000.0, 1100),
        (9999.0, 10000),
        (10000.0, 10000),
    ],
)
def test_count_tail_matches_independent_decimal_cdf(mean, count):
    result = lab.poisson_block_count_tail(mean, count)
    assert result["status"] == "SOLVED"
    assert result["minimum_blocks"] == count
    assert result["probability_at_least"] == pytest.approx(
        float(decimal_tail(mean, count)), rel=5e-11, abs=0
    )
    assert 0 <= result["probability_at_least"] <= 1
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("mean", [1e-20, 0.1, 1.0, 100.0, 1e308])
def test_single_count_is_stable_existing_forward_probability(mean):
    expected = -math.expm1(-mean)
    result = lab.poisson_block_count_tail(mean, 1)
    assert result["probability_at_least"] == expected
    forward = lab.probability_horizons(mean, 1, 600)
    assert forward["probability_at_least_one"] == expected


@pytest.mark.parametrize("count", [0, 1, 10, 10000])
def test_huge_finite_mean_is_solved_without_work_proportional_to_mean(count):
    result = lab.poisson_block_count_tail(1e308, count)
    assert result["status"] == "SOLVED"
    assert result["probability_at_least"] == 1


@pytest.mark.parametrize("mean,count", [(1e-100, 4), (math.ulp(0.0), 2)])
def test_positive_unrepresentable_tail_is_explicit_not_solved_zero(mean, count):
    assert decimal_tail(mean, count) > 0
    assert float(decimal_tail(mean, count)) == 0
    result = lab.poisson_block_count_tail(mean, count)
    assert result["status"] == "UNDERFLOW"
    assert result["probability_at_least"] is None
    json.dumps(result, allow_nan=False)


def test_representable_subnormal_tail_survives_log_scaled_seed():
    result = lab.poisson_block_count_tail(1e-160, 2)
    assert result["status"] == "SOLVED"
    assert result["probability_at_least"] == float(decimal_tail(1e-160, 2))
    assert result["probability_at_least"] > 0


@pytest.mark.parametrize("mean", [None, True, "1", [], -1, math.nan, math.inf, 10**400])
def test_invalid_mean_is_bounded_json_safe_not_solved(mean):
    result = lab.poisson_block_count_tail(mean, 2)
    assert result["status"] == "INVALID_INPUT"
    assert result["probability_at_least"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("count", [None, True, "2", [], -1, 1.5, math.nan, math.inf])
def test_invalid_count_is_not_silently_coerced(count):
    result = lab.poisson_block_count_tail(1.0, count)
    assert result["status"] == "INVALID_INPUT"
    assert result["minimum_blocks"] is None
    assert result["probability_at_least"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("count", [10001, 10**400])
def test_out_of_supported_count_range_is_explicit(count):
    result = lab.poisson_block_count_tail(1.0, count)
    assert result["status"] == "UNSUPPORTED_COUNT"
    assert result["minimum_blocks"] is None
    assert result["probability_at_least"] is None
    json.dumps(result, allow_nan=False)


def test_tail_is_monotone_in_mean_and_count():
    for mean in (0.01, 1, 10, 100):
        values = [
            lab.poisson_block_count_tail(mean, k)["probability_at_least"]
            for k in range(21)
        ]
        assert all(a >= b for a, b in zip(values, values[1:]))
    values = [
        lab.poisson_block_count_tail(mean, 10)["probability_at_least"]
        for mean in (0.01, 1, 10, 100)
    ]
    assert all(a <= b for a, b in zip(values, values[1:]))


def test_forward_contract_is_unchanged_and_reuses_single_tail(monkeypatch):
    calls = []
    actual = lab.poisson_block_count_tail

    def tracked(mean, count):
        calls.append((mean, count))
        return actual(mean, count)

    monkeypatch.setattr(lab, "poisson_block_count_tail", tracked)
    result = lab.probability_horizons(1, 1, 600)
    assert calls == [(1, 1)]
    assert set(result) == {
        "lambda",
        "probability_at_least_one",
        "probability_zero",
        "expected_blocks",
        "expected_time_to_block_seconds",
        "status",
    }


@pytest.mark.parametrize("mean,count", [(0.1, 2), (10.0, 10), (100.0, 110)])
def test_adjacent_tail_difference_matches_independent_probability_mass(mean, count):
    with localcontext() as context:
        context.prec = 100
        rate = Decimal.from_float(mean)
        mass = (-rate).exp() * rate**count / Decimal(math.factorial(count))
    first = lab.poisson_block_count_tail(mean, count)["probability_at_least"]
    second = lab.poisson_block_count_tail(mean, count + 1)["probability_at_least"]
    assert first - second == pytest.approx(float(mass), rel=5e-11, abs=0)


def test_iteration_budget_exhaustion_is_explicit_not_a_partial_probability(monkeypatch):
    monkeypatch.setattr(lab, "MAX_TAIL_TERMS", 1)
    result = lab.poisson_block_count_tail(1.0, 2)
    assert result["status"] == "NUMERIC_UNAVAILABLE"
    assert result["probability_at_least"] is None
    json.dumps(result, allow_nan=False)
