"""Issue #841: invert one Poisson model and keep its payloads JSON-safe."""

import json
import math

import pytest

from services.block_probability_lab import (
    hashpower_network_what_if,
    historical_best_share,
    model_inputs,
    probability_horizons,
    solo_model_summary,
    target_probability_for_p1_in_window,
    target_probability_solver,
)


@pytest.mark.parametrize("window", [1.0, 60.0, 600.0, 3600.0, 86400.0])
def test_ten_percent_target_round_trips_through_forward_model(window):
    result = target_probability_for_p1_in_window(window)
    share = result["share_of_network_required"]
    assert share == pytest.approx(-math.log(0.9) * 600.0 / window, rel=1e-12)
    forward = probability_horizons(share * 6e20, 6e20, window)
    assert forward["probability_at_least_one"] == pytest.approx(0.10, rel=1e-12)
    assert result["user_hashrate_required"] is None


@pytest.mark.parametrize("target", [1e-20, 0.10, 0.5, 0.99, math.nextafter(1.0, 0.0)])
def test_solver_round_trip_including_tiny_and_near_one_probabilities(target):
    result = target_probability_solver(1.0, 6e20, target, 600.0)
    assert result["status"] == "SOLVED"
    forward = probability_horizons(result["required_user_hashrate"], 6e20, 600.0)
    assert forward["probability_at_least_one"] == pytest.approx(
        target, rel=1e-12, abs=0
    )
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "target", [None, "bad", True, -1.0, 0.0, 1.0, float("nan"), float("inf")]
)
def test_impossible_or_invalid_target_is_not_solved(target):
    result = target_probability_solver(1.0, 6e20, target, 600.0)
    assert result["status"] == "INVALID_TARGET"
    assert result["required_user_hashrate"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "bad", [None, "bad", True, 0.0, -1.0, float("nan"), float("inf"), 10**400]
)
def test_invalid_window_is_not_replaced_with_a_successful_default(bad):
    for result in (
        target_probability_solver(1.0, 6e20, 0.10, bad),
        target_probability_for_p1_in_window(bad),
        probability_horizons(1.0, 6e20, bad),
        solo_model_summary(1.0, 6e20, bad),
    ):
        assert result.get("status") != "SOLVED"
        json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "bad", [None, "bad", True, 0.0, -1.0, float("nan"), float("inf"), 10**400]
)
def test_invalid_hashrate_never_masquerades_as_solved(index, bad):
    rates = [1.0, 6e20]
    rates[index] = bad
    for result in (
        probability_horizons(*rates, 600.0),
        solo_model_summary(*rates, 600.0),
        target_probability_solver(*rates, 0.10, 600.0),
    ):
        assert result["status"] != "SOLVED"
        json.dumps(result, allow_nan=False)


def test_small_positive_probability_survives_cancellation():
    result = probability_horizons(1.0, 1e20, 600.0)
    assert result["status"] == "SOLVED"
    assert result["lambda"] == pytest.approx(1e-20, rel=1e-12, abs=0)
    assert result["probability_at_least_one"] == pytest.approx(1e-20, rel=1e-12, abs=0)
    assert result["probability_at_least_one"] > 0


def test_target_ratio_display_is_dimensionless_not_a_hashrate():
    result = target_probability_solver(1.0, 6e20, 0.10, 600.0)
    assert result["share_of_network_required_str"] == "0.105361×"
    assert "H/s" not in result["share_of_network_required_str"]
    assert "PH/s" in result["required_user_hashrate_str"]


def test_equal_extreme_hashrates_do_not_overflow_mean_interval():
    result = probability_horizons(1e308, 1e308, 600.0)
    assert result["expected_time_to_block_seconds"] == pytest.approx(600.0)
    json.dumps(result, allow_nan=False)


def test_unrepresentable_mean_is_null_while_probability_remains_valid():
    result = probability_horizons(1.0, 1e308, 600.0)
    assert result["status"] == "SOLVED"
    assert result["probability_at_least_one"] > 0
    assert result["expected_time_to_block_seconds"] is None
    json.dumps(result, allow_nan=False)


def test_unrepresentable_expected_count_is_not_a_successful_zero():
    result = probability_horizons(1e308, 1e-308, 600.0)
    assert result["status"] == "NO_DATA"
    json.dumps(result, allow_nan=False)


def test_unrepresentable_target_hashrate_does_not_leak_infinity():
    result = target_probability_solver(1.0, 1e308, 0.99, 1.0)
    assert result["status"] == "SOLVER_FAILED"
    assert result["required_user_hashrate"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    ("user", "network", "duration", "expected_lambda"),
    [
        (1e308, 1e-308, 1e-308, 1e308 / 600.0),
        (1e-308, 1e308, 1e308, 1e-308 / 600.0),
    ],
)
def test_representable_count_survives_intermediate_ratio_over_or_underflow(
    user, network, duration, expected_lambda
):
    result = probability_horizons(user, network, duration)
    assert result["status"] == "SOLVED"
    assert result["lambda"] == pytest.approx(expected_lambda, rel=1e-12, abs=0)
    json.dumps(result, allow_nan=False)


def test_count_below_float_range_is_explicitly_unavailable():
    result = probability_horizons(1e-308, 1e308, 1e-308)
    assert result["status"] == "NO_DATA"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_explicit_unknown_solo_share_does_not_leak_nonfinite_values(bad):
    result = solo_model_summary(1.0, 6e20, 600.0, share_of_network=bad)
    assert result["share_of_network"] is None
    json.dumps(result, allow_nan=False)


def test_nonrepresentable_derived_share_and_best_ratio_remain_unknown():
    solo = solo_model_summary(1e308, 1e-308, 600.0)
    assert solo["share_of_network"] is None
    history = historical_best_share(1e308, 1e-308)
    assert history["best_share_target_ratio"] is None
    json.dumps({"solo": solo, "history": history}, allow_nan=False)


def test_invalid_what_if_scenario_is_not_reported_as_solved():
    result = hashpower_network_what_if(1.0, 6e20, [{"network_hashrate": float("nan")}])
    assert result["scenarios"][0]["status"] == "NO_DATA"
    assert result["scenarios"][0]["multiplier"] is None
    json.dumps(result, allow_nan=False)


def test_what_if_multiplier_overflow_is_unknown_not_infinity():
    result = hashpower_network_what_if(1.0, 1e-308, [{"network_hashrate": 1e308}])
    assert result["scenarios"][0]["multiplier"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 10**400, True])
def test_public_input_and_best_share_cards_do_not_leak_nonfinite_values(bad):
    inputs = model_inputs(bad, bad, bad, source="UNKNOWN")
    assert inputs["user_hashrate"] == 0
    assert inputs["network_hashrate"] == 0
    history = historical_best_share(bad, bad)
    assert history["status"] == "NO_DATA"
    json.dumps({"inputs": inputs, "history": history}, allow_nan=False)
