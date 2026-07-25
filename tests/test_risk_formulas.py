"""
Unit tests for CYPHER risk formula helpers (module-level in services/polling.py).

Tests _cv_to_score, _pool_cv, _solo_cv, _rental_cv in isolation — no DB,
no Flask, no HTTP. Pure numerical verification.

See also tests/test_opportunity_engine_direct.py for the companion
approach to testing pure functions without app.py.
"""

import math
import pytest

from services.polling import (
    _cv_to_score,
    _pool_cv,
    _solo_cv,
    _rental_cv,
)


# ══════════════════════════════════════════════════════════════════════
# _cv_to_score — normalise CV (coefficient of variation) to 1–10 scale
# ══════════════════════════════════════════════════════════════════════

class TestCvToScore:
    """Formula: score = clamp(log10(CV) × 3 + 5, 1, 10)."""

    def test_zero_cv_returns_1(self):
        """CV = 0 → abaixo do threshold 0.01 → retorna 1."""
        assert _cv_to_score(0.0) == 1

    def test_very_small_cv_returns_1(self):
        """CV = 0.001 → abaixo de 0.01 → retorna 1."""
        assert _cv_to_score(0.001) == 1

    def test_cv_001_returns_1(self):
        """CV = 0.01 → exatamente no threshold inferior → retorna 1."""
        assert _cv_to_score(0.01) == 1

    def test_cv_01_returns_2(self):
        """CV = 0.1 → score = log10(0.1)×3 + 5 = -1×3 + 5 = 2."""
        assert _cv_to_score(0.1) == 2

    def test_cv_05_returns_4(self):
        """CV = 0.5 → score ≈ log10(0.5)×3 + 5 ≈ 4."""
        # log10(0.5) ≈ -0.3010 → -0.3010×3 + 5 ≈ 4.097 → round → 4
        assert _cv_to_score(0.5) == 4

    def test_cv_1_returns_5(self):
        """CV = 1.0 → score = log10(1.0)×3 + 5 = 0 + 5 = 5."""
        assert _cv_to_score(1.0) == 5

    def test_cv_2_returns_6(self):
        """CV = 2.0 → score ≈ log10(2)×3 + 5 ≈ 5.9 → round → 6."""
        assert _cv_to_score(2.0) == 6

    def test_cv_10_returns_8(self):
        """CV = 10.0 → score = log10(10)×3 + 5 = 3 + 5 = 8."""
        assert _cv_to_score(10.0) == 8

    def test_cv_100_returns_10(self):
        """CV = 100.0 → exatamente no threshold superior → retorna 10."""
        assert _cv_to_score(100.0) == 10

    def test_cv_1000_returns_10(self):
        """CV = 1000.0 → acima de 100 → capped em 10."""
        assert _cv_to_score(1000.0) == 10

    def test_cv_316_returns_10(self):
        """CV ≈ 316 → log10(316)×3+5 ≈ 12.49 → clamped → 10."""
        assert _cv_to_score(316.2) == 10

    def test_cv_returns_int(self):
        """Sempre retorna int, nunca float."""
        for v in (0.0, 0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0):
            assert isinstance(_cv_to_score(v), int)

    def test_monotonic_non_decreasing(self):
        """CV maior nunca produz score menor."""
        scores = [_cv_to_score(v) for v in [0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 50.0, 100.0]]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i-1], f"Non-monotonic at index {i}: {scores[i]} < {scores[i-1]}"


# ══════════════════════════════════════════════════════════════════════
# _pool_cv — Poisson-based CV for pool mining
# ══════════════════════════════════════════════════════════════════════

class TestPoolCv:
    """CV = 1/√λ where λ = share_of_network × 144 (expected blocks/day)."""

    def test_zero_share_uses_min_lambda(self):
        """share_of_network = 0 → λ = 1e-12 → CV = 1/√1e-12 = 1e+6."""
        cv = _pool_cv(0.0)
        expected = 1.0 / math.sqrt(1e-12)
        assert cv == pytest.approx(expected, rel=1e-9)

    def test_very_small_share(self):
        """share_of_network = 1e-12 → λ = 1.44e-10 → CV ≈ 83333."""
        cv = _pool_cv(1e-12)
        expected = 1.0 / math.sqrt(1.44e-10)
        assert cv == pytest.approx(expected, rel=1e-6)

    def test_one_percent_of_network(self):
        """1% da rede → λ = 0.01 × 144 = 1.44 → CV = 1/√1.44 ≈ 0.833."""
        cv = _pool_cv(0.01)
        expected = 1.0 / math.sqrt(1.44)
        assert cv == pytest.approx(expected, rel=1e-6)

    def test_ten_percent_of_network(self):
        """10% da rede → λ = 14.4 → CV = 1/√14.4 ≈ 0.264."""
        cv = _pool_cv(0.10)
        expected = 1.0 / math.sqrt(14.4)
        assert cv == pytest.approx(expected, rel=1e-6)

    def test_full_network_share(self):
        """100% da rede → λ = 144 → CV = 1/√144 = 1/12 ≈ 0.0833."""
        cv = _pool_cv(1.0)
        expected = 1.0 / 12.0
        assert cv == pytest.approx(expected, rel=1e-6)

    def test_negative_share_uses_min_lambda(self):
        """share negativo → max com 1e-12 → CV estável (não quebra)."""
        cv = _pool_cv(-0.5)
        expected = 1.0 / math.sqrt(1e-12)
        assert cv == pytest.approx(expected, rel=1e-6)

    def test_returns_float(self):
        """Sempre retorna float."""
        assert isinstance(_pool_cv(0.001), float)
        assert isinstance(_pool_cv(0.5), float)
        assert isinstance(_pool_cv(0.0), float)


# ══════════════════════════════════════════════════════════════════════
# _solo_cv — Bernoulli-based CV for solo mining
# ══════════════════════════════════════════════════════════════════════

class TestSoloCv:
    """CV = √((1-p)/p) where p = P(at least 1 block/day)."""

    def test_zero_probability_returns_999(self):
        """p = 0 → CV = 999 (capped, indicando incerteza extrema)."""
        assert _solo_cv(0.0) == 999.0

    def test_negative_probability_returns_999(self):
        """p < 0 → CV = 999 (caso inválido)."""
        assert _solo_cv(-0.1) == 999.0

    def test_very_small_probability(self):
        """p = 1e-10 → CV ≈ √((1-1e-10) / 1e-10) ≈ 1e5."""
        cv = _solo_cv(1e-10)
        expected = math.sqrt((1 - 1e-10) / 1e-10)
        assert cv == pytest.approx(expected, rel=1e-6)

    def test_one_percent_daily(self):
        """p = 0.01 (1% chance de bloco no dia) → CV ≈ √(0.99/0.01) ≈ 9.95."""
        cv = _solo_cv(0.01)
        expected = math.sqrt(0.99 / 0.01)
        assert cv == pytest.approx(expected, rel=1e-4)

    def test_ten_percent_daily(self):
        """p = 0.10 → CV ≈ √(0.90/0.10) = 3.0."""
        cv = _solo_cv(0.10)
        expected = math.sqrt(0.90 / 0.10)
        assert cv == pytest.approx(expected, rel=1e-6)

    def test_fifty_percent_daily(self):
        """p = 0.50 → CV = √(0.50/0.50) = 1.0."""
        cv = _solo_cv(0.50)
        assert cv == pytest.approx(1.0, rel=1e-6)

    def test_ninety_percent_daily(self):
        """p = 0.90 → CV = √(0.10/0.90) ≈ 0.333."""
        cv = _solo_cv(0.90)
        expected = math.sqrt(0.10 / 0.90)
        assert cv == pytest.approx(expected, rel=1e-6)

    def test_certainty_daily(self):
        """p = 1.0 → CV = 0 (certeza, sem variância)."""
        cv = _solo_cv(1.0)
        assert cv == pytest.approx(0.0, rel=1e-6)

    def test_returns_float(self):
        """Sempre retorna float."""
        assert isinstance(_solo_cv(0.001), float)
        assert isinstance(_solo_cv(0.5), float)
        assert isinstance(_solo_cv(1.0), float)
        assert isinstance(_solo_cv(0.0), float)

    def test_monotonic_decreasing(self):
        """p maior → CV menor (mais chance → menos variância relativa)."""
        cvs = [_solo_cv(p) for p in [1e-10, 1e-5, 0.001, 0.01, 0.1, 0.5, 0.9, 1.0]]
        for i in range(1, len(cvs)):
            assert cvs[i] <= cvs[i-1], f"Non-monotonic at index {i}: {cvs[i]} > {cvs[i-1]}"


# ══════════════════════════════════════════════════════════════════════
# _rental_cv — Rental CV = pool_cv × 2 (price exposure proxy)
# ══════════════════════════════════════════════════════════════════════

class TestRentalCv:
    """CV = pool_cv × 2, with fallback to 999.0."""

    def test_pool_cv_1_returns_2(self):
        """pool_cv = 1.0 → rental_cv = 2.0."""
        assert _rental_cv(1.0) == 2.0

    def test_pool_cv_0_returns_999(self):
        """pool_cv = 0.0 é falsy em Python → retorna 999.0 (fallback).
        Em prática pool_cv nunca é 0.0 vindo de _pool_cv()."""
        assert _rental_cv(0.0) == 999.0

    def test_pool_cv_01_returns_02(self):
        """pool_cv = 0.1 → rental_cv = 0.2."""
        assert _rental_cv(0.1) == 0.2

    def test_pool_cv_5_returns_10(self):
        """pool_cv = 5.0 → rental_cv = 10.0."""
        assert _rental_cv(5.0) == 10.0

    def test_pool_cv_none_returns_999(self):
        """pool_cv = None → fallback 999.0."""
        assert _rental_cv(None) == 999.0

    def test_returns_float(self):
        """Sempre retorna float."""
        assert isinstance(_rental_cv(1.0), float)
        assert isinstance(_rental_cv(0.1), float)
        assert isinstance(_rental_cv(None), float)


# ══════════════════════════════════════════════════════════════════════
# Integration: _cv_to_score ∘ (pool/solo/rental) end-to-end
# ══════════════════════════════════════════════════════════════════════

class TestEndToEndRiskScores:
    """Test realistic scenarios through the full pipeline: CV → score."""

    def test_pool_one_pct_network(self):
        """1% da rede: pool_cv ≈ 0.833 → score ≈ 4 (baixo risco)."""
        cv = _pool_cv(0.01)
        score = _cv_to_score(cv)
        assert 3 <= score <= 5

    def test_pool_01_pct_network(self):
        """0.1% da rede: pool_cv ≈ 2.64 → score ≈ 6 (risco moderado)."""
        cv = _pool_cv(0.001)
        score = _cv_to_score(cv)
        assert 5 <= score <= 7

    def test_solo_high_share(self):
        """Solo com P=0.1/dia: solo_cv ≈ 3 → score ≈ 6."""
        cv = _solo_cv(0.10)
        score = _cv_to_score(cv)
        assert 5 <= score <= 7

    def test_solo_low_share(self):
        """Solo com P=1e-6/dia: solo_cv ≈ 1000 → score = 10."""
        cv = _solo_cv(1e-6)
        score = _cv_to_score(cv)
        assert score == 10

    def test_rental_pool_01_pct(self):
        """Rental com pool_cv ≈ 2.64 → rental_cv ≈ 5.28 → score ≈ 7."""
        pool_cv = _pool_cv(0.001)
        rental_cv = _rental_cv(pool_cv)
        score = _cv_to_score(rental_cv)
        assert 6 <= score <= 8

    def test_pool_lower_risk_than_solo_same_hashrate(self):
        """Para hashrates pequenos (< 0.1% da rede): pool tem score ≤ solo.
        Acima disso a mineração solo tem variância menor (λ ~ 1+ blocos/dia)
        e seu CV fica menor que o do pool matematicamente."""
        for share in [1e-6, 1e-5, 1e-4, 0.0005]:
            p = 1 - math.exp(-share * 144)
            pool_score = _cv_to_score(_pool_cv(share))
            solo_score = _cv_to_score(_solo_cv(p))
            assert pool_score <= solo_score, \
                f"share={share}: pool={pool_score} > solo={solo_score}"
