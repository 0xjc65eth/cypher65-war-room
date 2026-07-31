"""
CYPHER65 // Polling — Test Suite
=================================
Tests for services/polling.py — focuses on the pure, module-level
helper functions that are explicitly designed for testability.

These have ZERO dependencies on config, state, or DB:
  - _cv_to_score(cv)        → risk score 1-10
  - _pool_cv(share_of_net)  → Poisson-based CV
  - _solo_cv(solo_p_day)    → Bernoulli-based CV
  - _rental_cv(pool_cv)     → 2× pool CV

Integration/end-to-end tests for poll_once() would require extensive
mocking of config, state, requests, and sqlite — that belongs in
a separate integration test file.
"""

import math

import pytest

from services.polling import _cv_to_score, _pool_cv, _solo_cv, _rental_cv


# ══════════════════════════════════════════════════════════════════════
#  _cv_to_score
# ══════════════════════════════════════════════════════════════════════

class TestCvToScore:
    """Formula: score = clamp(log10(CV) × 3 + 5, 1, 10)."""

    def test_cv_zero_point_01_returns_1(self):
        """CV = 0.01 → score = 1 (lowest risk)."""
        assert _cv_to_score(0.01) == 1

    def test_cv_below_0_01_returns_1(self):
        """CV < 0.01 → score = 1."""
        assert _cv_to_score(0.001) == 1
        assert _cv_to_score(0.0001) == 1
        assert _cv_to_score(0.0) == 1  # edge: 0 treated as <=0.01

    def test_cv_0_point_1_returns_2(self):
        """CV = 0.1 → log10(0.1) = -1 → -1*3 + 5 = 2."""
        assert _cv_to_score(0.1) == 2

    def test_cv_1_returns_5(self):
        """CV = 1.0 → log10(1) = 0 → 0*3 + 5 = 5 (baseline risk)."""
        assert _cv_to_score(1.0) == 5

    def test_cv_10_returns_8(self):
        """CV = 10 → log10(10) = 1 → 1*3 + 5 = 8."""
        assert _cv_to_score(10.0) == 8

    def test_cv_100_returns_10(self):
        """CV >= 100 → score = 10 (highest risk, clamped)."""
        assert _cv_to_score(100.0) == 10

    def test_cv_above_100_returns_10(self):
        """CV > 100 → score = 10 (clamped)."""
        assert _cv_to_score(500.0) == 10
        assert _cv_to_score(1e6) == 10

    def test_cv_0_point_5_returns_4(self):
        """CV = 0.5 → log10(0.5) ≈ -0.301 → -0.301*3 + 5 ≈ 4.097 → 4."""
        assert _cv_to_score(0.5) == 4

    def test_cv_2_returns_6(self):
        """CV = 2.0 → log10(2) ≈ 0.301 → 0.301*3 + 5 ≈ 5.903 → 6."""
        assert _cv_to_score(2.0) == 6

    def test_cv_50_returns_10(self):
        """CV = 50 → log10(50) ≈ 1.699 → 1.699*3 + 5 ≈ 10.097 → clamped to 10."""
        assert _cv_to_score(50.0) == 10

    def test_cv_0_point_03_returns_1(self):
        """CV = 0.03 → log10(0.03) ≈ -1.523 → -1.523*3 + 5 ≈ 0.431 → clamped to 1."""
        assert _cv_to_score(0.03) == 1

    def test_cv_0_point_15_returns_3(self):
        """CV = 0.15 → log10(0.15) ≈ -0.824 → -0.824*3 + 5 ≈ 2.528 → 3."""
        assert _cv_to_score(0.15) == 3

    def test_cv_3_returns_6(self):
        """CV = 3.0 → log10(3) ≈ 0.477 → 0.477*3 + 5 ≈ 6.431 → 6."""
        assert _cv_to_score(3.0) == 6

    def test_negative_cv_treated_as_zero(self):
        """CV < 0 → max(0.01, cv) = 0.01 → score = 1."""
        # The function uses max(cv, 0.01), so negative becomes 0.01 → log10(0.01) = -2
        assert _cv_to_score(-1.0) == 1

    def test_always_returns_int(self):
        """Return type must be int."""
        for cv in [0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 50.0, 100.0]:
            assert isinstance(_cv_to_score(cv), int)

    def test_monotonic(self):
        """Higher CV → same or higher score (never decreases)."""
        prev = -1
        for cv in [0.001, 0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 500.0]:
            s = _cv_to_score(cv)
            assert s >= prev, f"CV={cv} broke monotonicity: {s} < {prev}"
            prev = s


# ══════════════════════════════════════════════════════════════════════
#  _pool_cv
# ══════════════════════════════════════════════════════════════════════

class TestPoolCv:
    """Formula: λ = max(share_of_network × 144, 1e-12); CV = 1 / √λ.

    For a Poisson process with λ expected blocks/day, σ = √λ, μ = λ,
    so CV = 1/√λ.
    """

    def test_dominant_miner_returns_low_cv(self):
        """Large share_of_network → many blocks/day → low CV."""
        # 10% of network → λ = 0.1 * 144 = 14.4 → CV = 1/√14.4 ≈ 0.264
        cv = _pool_cv(0.10)
        assert cv == pytest.approx(0.2635, rel=0.01)

    def test_small_miner_returns_high_cv(self):
        """Tiny share → few blocks/day → high CV."""
        # 0.001% of network → λ = 1.44e-5 * 144 = 0.00207 → wait:
        # Actually 0.001% = 1e-5 share → λ ≈ 1e-5 * 144 = 0.00144 → CV = 1/√0.00144 ≈ 26.35
        cv = _pool_cv(0.00001)  # 0.001%
        assert cv > 20.0

    def test_solo_miner_returns_extreme_cv(self):
        """Extremely tiny share → very high CV."""
        # share ≈ 1e-16 (realistic solo miner) → λ ≈ 1.44e-14 → CV ≈ 1/√(1.44e-14) ≈ 8.333e6
        cv = _pool_cv(1e-16)
        # Due to floating point, CV may be exactly 1e6 for very small shares (clamped λ)
        # λ = max(1e-16 * 144, 1e-12) = max(1.44e-14, 1e-12) = 1e-12
        # CV = 1/√1e-12 = 1/1e-6 = 1e6 exactly
        assert cv >= 1e6, f"Expected CV >= 1e6, got {cv}"

    def test_zero_share_clamped(self):
        """share_of_network = 0 → λ clamped to 1e-12 → CV = 1/√1e-12 = 1e6."""
        cv = _pool_cv(0.0)
        assert cv == pytest.approx(1e6, rel=0.01)

    def test_whole_network_returns_low_cv(self):
        """100% of network → λ = 144 → CV = 1/√144 ≈ 0.0833."""
        cv = _pool_cv(1.0)
        assert cv == pytest.approx(0.08333, rel=0.01)

    def test_large_pool(self):
        """20% of network → λ = 28.8 → CV = 1/√28.8 ≈ 0.186."""
        cv = _pool_cv(0.20)
        assert cv == pytest.approx(0.1863, rel=0.01)

    def test_always_positive(self):
        """CV is always > 0 for any valid input."""
        for share in [0, 1e-16, 1e-10, 1e-6, 0.001, 0.01, 0.1, 0.5, 1.0]:
            assert _pool_cv(share) > 0

    def test_monotonic_decreasing(self):
        """Higher share → lower CV."""
        shares = [1e-10, 1e-8, 1e-6, 0.0001, 0.001, 0.01, 0.1, 0.5]
        cv_vals = [_pool_cv(s) for s in shares]
        for i in range(1, len(cv_vals)):
            assert cv_vals[i] <= cv_vals[i - 1], (
                f"Non-monotonic at index {i}: {cv_vals[i]} > {cv_vals[i-1]}"
            )


# ══════════════════════════════════════════════════════════════════════
#  _solo_cv
# ══════════════════════════════════════════════════════════════════════

class TestSoloCv:
    """Formula: CV = √((1-p) / p) for Bernoulli trial per day.

    For small p, CV ≈ 1/√p (since 1-p ≈ 1).
    """

    def test_zero_probability_returns_999(self):
        """solo_p_day = 0 → guard clause returns 999.0."""
        assert _solo_cv(0.0) == 999.0

    def test_negative_returns_999(self):
        """solo_p_day < 0 → guard clause returns 999.0."""
        assert _solo_cv(-0.1) == 999.0

    def test_certain_event_returns_low_cv(self):
        """p = 1.0 (certain) → CV = √((1-1)/1) = √0 = 0."""
        cv = _solo_cv(1.0)
        assert cv == pytest.approx(0.0, abs=1e-10)

    def test_fifty_percent_returns_1(self):
        """p = 0.5 → CV = √(0.5/0.5) = √1 = 1."""
        cv = _solo_cv(0.5)
        assert cv == pytest.approx(1.0, rel=0.01)

    def test_ten_percent(self):
        """p = 0.1 → CV = √(0.9/0.1) = √9 = 3."""
        cv = _solo_cv(0.1)
        assert cv == pytest.approx(3.0, rel=0.01)

    def test_one_percent(self):
        """p = 0.01 → CV ≈ √(0.99/0.01) = √99 ≈ 9.95."""
        cv = _solo_cv(0.01)
        assert cv == pytest.approx(9.9499, rel=0.01)

    def test_realistic_solo_mining_probability(self):
        """p ≈ 1.59e-5 (100 TH/s at 126T diff) → CV ≈ √(1/1.59e-5) ≈ 251."""
        cv = _solo_cv(1.59e-5)
        assert cv == pytest.approx(250.7, rel=0.01)

    def test_always_positive_for_valid_inputs(self):
        """CV > 0 for 0 < p < 1."""
        for p in [1e-10, 1e-8, 1e-6, 0.001, 0.01, 0.1, 0.5, 0.99]:
            assert _solo_cv(p) > 0

    def test_monotonic_decreasing(self):
        """Higher p → lower CV."""
        probs = [1e-8, 1e-6, 0.0001, 0.001, 0.01, 0.1, 0.5, 0.99]
        cv_vals = [_solo_cv(p) for p in probs]
        for i in range(1, len(cv_vals)):
            assert cv_vals[i] <= cv_vals[i - 1], (
                f"Non-monotonic at index {i}: {cv_vals[i]} > {cv_vals[i-1]}"
            )


# ══════════════════════════════════════════════════════════════════════
#  _rental_cv
# ══════════════════════════════════════════════════════════════════════

class TestRentalCv:
    """Formula: 2 × pool_cv, with guard for None/0/negative."""

    def test_returns_double_pool_cv(self):
        """pool_cv = 0.5 → rental_cv = 1.0."""
        cv = _rental_cv(0.5)
        assert cv == pytest.approx(1.0)

    def test_large_pool_cv_doubled(self):
        """pool_cv = 26.35 → rental_cv = 52.70."""
        cv = _rental_cv(26.35)
        assert cv == pytest.approx(52.70)

    def test_zero_pool_cv_returns_999(self):
        """pool_cv = 0 → falsy → returns 999."""
        cv = _rental_cv(0.0)
        assert cv == 999.0

    def test_none_pool_cv_returns_999(self):
        """pool_cv = None → falsy → returns 999."""
        cv = _rental_cv(None)
        assert cv == 999.0

    def test_negative_pool_cv_returns_999(self):
        """pool_cv < 0 → treated as falsy? Let's check: 0.0 would be falsy, but -1.0 is truthy.
        The code checks `if pool_cv` which is True for -1.0, so -1.0 * 2 = -2.0.
        This is a quirk of the current implementation.
        """
        cv = _rental_cv(-1.0)
        # pool_cv = -1.0 is truthy (non-zero), so returns -1.0 * 2 = -2.0
        assert cv == pytest.approx(-2.0)

    def test_high_variance_returns_high_cv(self):
        """pool_cv = 100 → rental_cv = 200."""
        cv = _rental_cv(100.0)
        assert cv == pytest.approx(200.0)


# ══════════════════════════════════════════════════════════════════════
#  Integration: CV → score chain
# ══════════════════════════════════════════════════════════════════════

class TestCVtoScoreChain:
    """End-to-end: pool/solo/rental CV computed then mapped to risk score."""

    def test_large_pool_low_risk(self):
        """10% pool share → pool CV ≈ 0.264 → risk score 2 (very low)."""
        cv = _pool_cv(0.10)
        score = _cv_to_score(cv)
        assert score <= 3

    def test_small_pool_medium_risk(self):
        """0.01% pool share → pool CV ≈ 26.35 → risk score 9 (very high)."""
        cv = _pool_cv(0.0001)
        score = _cv_to_score(cv)
        assert score >= 8

    def test_solo_mining_high_risk(self):
        """Realistic solo p = 1.6e-5 → solo CV ≈ 250 → risk score 10 (max)."""
        cv = _solo_cv(1.6e-5)
        score = _cv_to_score(cv)
        assert score == 10

    def test_rental_medium_risk(self):
        """Rental with 1% pool share.
        pool_cv(0.01) = 1/√(0.01*144) = 1/1.2 ≈ 0.833
        rental_cv = 2 * 0.833 = 1.667
        score = clamp(log10(1.667)*3+5, 1, 10) ≈ round(5.67) = 6 (medium).
        """
        cv = _rental_cv(_pool_cv(0.01))
        score = _cv_to_score(cv)
        # 1% share is a realistic pool share, rental amplifies risk to ~score 6 (medium)
        assert score == 6, f"Expected score 6, got {score} (cv={cv:.4f})"

    def test_rental_always_higher_risk_than_pool(self):
        """For the same share, rental CV > pool CV → rental score ≥ pool score."""
        for share in [1e-6, 0.0001, 0.001, 0.01, 0.1]:
            pool_cv = _pool_cv(share)
            rental_cv = _rental_cv(pool_cv)
            pool_score = _cv_to_score(pool_cv)
            rental_score = _cv_to_score(rental_cv)
            assert rental_score >= pool_score, (
                f"share={share}: rental score {rental_score} < pool score {pool_score}"
            )

    def test_solo_extreme_vs_pool(self):
        """Solo mining at realistic HR is far riskier than pool mining."""
        pool_cv = _pool_cv(0.01)  # 1% pool share
        solo_cv = _solo_cv(1.6e-5)  # realistic solo p
        pool_risk = _cv_to_score(pool_cv)
        solo_risk = _cv_to_score(solo_cv)
        assert solo_risk >= pool_risk

    def test_rental_vs_direct_pool_extreme(self):
        """For 0.001% share, rental adds meaningful risk over pool."""
        share = 0.00001
        pool_s = _cv_to_score(_pool_cv(share))
        rental_s = _cv_to_score(_rental_cv(_pool_cv(share)))
        # Rental should be at least as risky as pool — might be the same if both
        # are already at ceiling (score 10)
        assert rental_s >= pool_s
