"""Focused tests for services/block_probability_lab.py.

Formula correctness: Poisson lambda = (user_hr/net_hr) * (t/600), P(>=1) =
1 - e^-lambda, expected_time = 600 * net_hr / user_hr.

Zero vs unknown: invalid/negative/non-finite inputs -> NO_DATA/NaN-free
payloads (never Infinity/NaN).
Live vs fallback: provenance labels LIVE | DERIVED | FALLBACK | MANUAL |
STALE | UNKNOWN are normalized, never invented.
Stale vs current: age_seconds drives STALE vs LIVE/GOOD COVERAGE.
Measured vs estimated: best_share is a RECORD, never an odds change.
Window comparability: what-if keeps the same user share, only network
changes, so window is comparable across scenarios.
Unit conversion: hashes/600 s, TH/s vs PH/s formatting.
Missing-data behavior: None/0 for missing inputs -> UNKNOWN/NO DATA, not 0
as a healthy value.
Frontend semantics: evidence_state is one of GOOD COVERAGE | PARTIAL |
STALE | INSUFFICIENT | NO DATA with no score.
"""

import math

import pytest

from services.block_probability_lab import (
    evidence_state_from_inputs,
    hashpower_network_what_if,
    historical_best_share,
    model_inputs,
    probability_horizons,
    share_statistics,
    solo_model_summary,
    target_probability_for_p1_in_window,
    target_probability_solver,
)


class TestPoissonCore:
    def test_poisson_lambda_and_probability(self):
        # 10% of network, 600 s window (1 block interval)
        user = 0.10 * 6e20
        net = 6e20
        t = 600.0
        lam = (user / net) * (t / 600.0)
        p = 1.0 - math.exp(-lam)
        r = probability_horizons(user_hr=user, network_hr=net, duration_seconds=t)
        assert r["lambda"] == pytest.approx(lam, rel=1e-9)
        assert r["probability_at_least_one"] == pytest.approx(p, rel=1e-9)

    def test_zero_user_hashrate_is_no_data(self):
        r = probability_horizons(user_hr=0, network_hr=6e20, duration_seconds=86400)
        assert r["status"] == "NO_DATA"
        assert r["probability_at_least_one"] == 0.0

    def test_negative_and_nonfinite_are_no_data(self):
        for bad in (-1, float("nan"), float("inf")):
            r = probability_horizons(user_hr=bad, network_hr=6e20, duration_seconds=86400)
            assert r["status"] == "NO_DATA"
            assert math.isfinite(r["probability_at_least_one"])


class TestTargetSolver:
    def test_invalid_target(self):
        r = target_probability_solver(user_hr=1e11, net_hr=6e20, target_p=1.0, window_seconds=3600)
        assert r["status"] == "INVALID_TARGET"

    def test_10_percent_in_one_hour(self):
        # user=10% share, target 10%, window 1h
        r = target_probability_solver(user_hr=1e11, net_hr=6e20, target_p=0.10, window_seconds=3600)
        assert r["status"] == "SOLVED"
        # verify by plugging the required hashrate back into the window
        p = probability_horizons(
            user_hr=r["required_user_hashrate"], network_hr=6e20, duration_seconds=3600
        )
        assert p["probability_at_least_one"] == pytest.approx(0.10, abs=1e-6)

    def test_zero_or_negative_window(self):
        r = target_probability_solver(user_hr=1e11, net_hr=6e20, target_p=0.50, window_seconds=0)
        assert r["status"] == "INSUFFICIENT_INPUTS"


class TestTargetP1Window:
    def test_known_value(self):
        r = target_probability_for_p1_in_window(600.0)
        assert r["target"] == 0.10
        assert r["share_of_network_required"] > 0
        # user_hashrate_required is None (needs network); share must be positive
        assert r["user_hashrate_required"] is None


class TestWhatIf:
    def test_comparable_window(self):
        base = 6e20
        what = hashpower_network_what_if(
            base_user_hr=1e11,
            base_network_hr=base,
            scenarios=[{"network_hashrate": 6e20}, {"network_hashrate": 1.2e20}],
        )
        assert what["base"]["network_hashrate"] == base
        assert len(what["scenarios"]) == 2
        # same user, same window -> comparable across scenarios
        assert what["scenarios"][0]["expected_time_to_block_seconds"] > what["scenarios"][1][
            "expected_time_to_block_seconds"
        ]

    def test_missing_inputs(self):
        r = hashpower_network_what_if(base_user_hr=0, base_network_hr=6e20)
        assert r["scenarios"] == []


class TestHistoricalBestShare:
    def test_ratio(self):
        r = historical_best_share(best_diff_raw=5e13, network_difficulty=1e14)
        assert r["best_share_target_ratio"] == pytest.approx(0.5)
        assert r["status"] == "SOLVED"

    def test_no_data(self):
        r = historical_best_share(best_diff_raw=0, network_difficulty=1e14)
        assert r["status"] == "NO_DATA"


class TestSoloModelSummary:
    def test_solo_probability(self):
        r = solo_model_summary(
            user_hr=1e11, network_hr=6e20, duration_seconds=86400
        )
        assert r["status"] == "SOLVED"
        assert r["share_of_network"] == pytest.approx(1e11 / 6e20, rel=1e-9)

    def test_zero_network_is_no_data(self):
        r = solo_model_summary(user_hr=1e11, network_hr=0, duration_seconds=86400)
        assert r["status"] == "NO_DATA"


class TestShareStatistics:
    def test_percentiles(self):
        history = [
            {"share_diff_raw": 40e12},
            {"share_diff_raw": 50e12},
            {"share_diff_raw": 60e12},
        ]
        r = share_statistics(session_share_count=100, share_calc_history=history)
        assert r["sample_count"] == 3
        assert r["p50"] == 50e12
        assert r["max"] == 60e12

    def test_no_data(self):
        r = share_statistics(session_share_count=0, share_calc_history=[])
        assert r["sample_count"] == 0
        assert r["status"] == "NO_DATA"


class TestEvidenceState:
    def test_no_data(self):
        assert evidence_state_from_inputs(0, 6e20, 0) == "NO DATA"

    def test_insufficient(self):
        assert evidence_state_from_inputs(1e11, 6e20, 0) == "INSUFFICIENT"

    def test_stale(self):
        assert evidence_state_from_inputs(1e11, 6e20, 500, age_seconds=7200) == "STALE"

    def test_partial(self):
        assert evidence_state_from_inputs(1e11, 6e20, 50, age_seconds=0) == "PARTIAL"

    def test_good_coverage(self):
        assert evidence_state_from_inputs(1e11, 6e20, 500, age_seconds=0) == "GOOD COVERAGE"


class TestModelInputsProvenance:
    def test_valid_sources(self):
        for src, exp in [
            ("LIVE", "LIVE"),
            ("DERIVED", "DERIVED"),
            ("FALLBACK", "FALLBACK"),
            ("MANUAL", "MANUAL"),
            ("STALE", "STALE"),
            ("UNKNOWN", "UNKNOWN"),
        ]:
            r = model_inputs(
                user_hashrate=1e11,
                network_hashrate=6e20,
                network_difficulty=1e14,
                source=src,
            )
            assert r["network_hashrate_source"] == exp
            assert r["state"] == exp

    def test_invalid_source_normalizes_to_unknown(self):
        r = model_inputs(
            user_hashrate=1e11,
            network_hashrate=6e20,
            network_difficulty=1e14,
            source="GARBAGE",
        )
        assert r["network_hashrate_source"] == "UNKNOWN"

    def test_missing_network_hashrate_is_zero_not_default(self):
        r = model_inputs(
            user_hashrate=1e11,
            network_hashrate=0,
            network_difficulty=1e14,
            source="UNKNOWN",
        )
        assert r["network_hashrate"] == 0
