"""Tests for core CYPHER65 functions: solo_mining calculations + helpers formatters."""

import math
import pytest
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solo_mining import calc_block_probability, _parse_hashrate, normalize_cost
from helpers import parse_diff_to_float, fmt_diff


# ═══════════════════════════════════════════════════════════════════════════
# 1. calc_block_probability
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcBlockProbability:
    """Poisson-based block discovery probability."""

    def test_zero_hashrate(self):
        """Zero hashrate => lambda=0 => P=0."""
        result = calc_block_probability(0, 110e12, 86400)
        assert result["lambda"] == 0.0
        assert result["p_at_least_1_block"] == 0.0
        assert result["p_at_least_1_block_pct"] == 0.0
        assert result["p_zero_blocks_pct"] == 100.0

    def test_known_values(self):
        """225 TH/s for 24h at 110T difficulty — verify lambda and probability.
        Known: hashes_per_block = 110e12 * 2^32 ≈ 4.72e23
        block_rate = 225e12 / 4.72e23 ≈ 4.76e-10
        lambda(24h) = 4.76e-10 * 86400 ≈ 4.12e-5
        P = 1 - e^(-lambda) ≈ lambda (for small lambda) ≈ 4.12e-5
        P% ≈ 0.00412%
        """
        result = calc_block_probability(225e12, 110e12, 86400)
        # lambda should be ~4.12e-5
        assert 4.0e-5 < result["lambda"] < 4.3e-5
        # hashes per block
        expected_hpb = 110e12 * (2 ** 32)
        assert result["hashes_per_block"] == pytest.approx(expected_hpb, rel=1e-6)
        # P ≈ lambda for small values
        assert result["p_at_least_1_block"] == pytest.approx(result["lambda"], rel=0.02)
        # P% should be ~0.004%
        assert 0.003 < result["p_at_least_1_block_pct"] < 0.005

    def test_large_hashrate_guaranteed(self):
        """Enormous hashrate => near-certain block in 24h."""
        # 100 EH/s at current difficulty for 24h => lambda ~18, P ~= 1.0
        result = calc_block_probability(100e18, 110e12, 86400)
        assert result["p_at_least_1_block"] > 0.999
        assert result["p_zero_blocks_pct"] < 0.001

    def test_very_short_duration(self):
        """1 second => lambda is tiny, P ≈ 0."""
        result = calc_block_probability(225e12, 110e12, 1)
        assert result["lambda"] < 1e-8
        assert result["p_at_least_1_block"] < 1e-7

    def test_difficulty_zero_handling(self):
        """Difficulty=0 raises ZeroDivisionError — the function does not guard against this.
        This test documents the current behavior. Fix the function if zero-diff should be handled."""
        with pytest.raises(ZeroDivisionError):
            calc_block_probability(1e12, 0, 1)


# ═══════════════════════════════════════════════════════════════════════════
# 2. _parse_hashrate
# ═══════════════════════════════════════════════════════════════════════════

class TestParseHashrate:
    """Parse human-readable hashrate strings to H/s."""

    def test_terahash(self):
        assert _parse_hashrate("225TH") == 225e12
        assert _parse_hashrate("225 TH/s") == 225e12
        assert _parse_hashrate("225TH/s") == 225e12
        assert _parse_hashrate("225 th") == 225e12  # case-insensitive

    def test_petahash(self):
        assert _parse_hashrate("1.5PH") == 1.5e15
        assert _parse_hashrate("1.5 PH/s") == 1.5e15

    def test_exahash(self):
        assert _parse_hashrate("100EH") == 100e18
        assert _parse_hashrate("0.5 EH") == 0.5e18

    def test_gigahash(self):
        assert _parse_hashrate("500GH") == 500e9

    def test_megahash(self):
        assert _parse_hashrate("100MH") == 100e6

    def test_kilohash(self):
        assert _parse_hashrate("50KH") == 50e3

    def test_plain_hash(self):
        assert _parse_hashrate("1000H") == 1000
        assert _parse_hashrate("1000") == 1000  # no unit => plain number

    def test_decimal_values(self):
        assert _parse_hashrate("0.5TH") == 0.5e12
        assert _parse_hashrate("225.75 TH") == 225.75e12

    def test_with_spaces(self):
        assert _parse_hashrate("  225 TH/s  ") == 225e12


# ═══════════════════════════════════════════════════════════════════════════
# 3. normalize_cost
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeCost:
    """Normalize rental prices to BTC/PH/day."""

    def test_sats_per_ph_day(self):
        """200,000 sats/PH/day = 0.002 BTC/PH/day."""
        result = normalize_cost(200_000, "sats/PH/day")
        assert result == pytest.approx(0.002, rel=1e-6)

    def test_btc_per_eh_day(self):
        """0.002 BTC/EH/day = 0.002 / 1000 = 0.000002 BTC/PH/day."""
        result = normalize_cost(0.002, "BTC/EH/day")
        assert result == pytest.approx(2e-6, rel=1e-6)

    def test_btc_per_ph_day(self):
        """Direct pass-through."""
        result = normalize_cost(0.005, "BTC/PH/day")
        assert result == 0.005

    def test_case_insensitive(self):
        """Unit strings should be case-insensitive."""
        result = normalize_cost(200_000, "sats/ph/day")
        assert result == pytest.approx(0.002, rel=1e-6)

    def test_unknown_unit(self):
        """Unknown unit returns None."""
        result = normalize_cost(100, "eur/day")
        assert result is None

    def test_usd_per_th_day(self):
        """USD/TH/day requires BTC price lookup — returns None if API fails."""
        # This will call get_btc_price() — may return None if offline
        result = normalize_cost(0.05, "usd/th/day")
        # Should not crash; may be None if CoinGecko is unreachable
        if result is not None:
            assert result > 0


# ═══════════════════════════════════════════════════════════════════════════
# 4. fmt_diff
# ═══════════════════════════════════════════════════════════════════════════

class TestFmtDiff:
    """Format difficulty values to human-readable strings."""

    def test_raw_number(self):
        assert fmt_diff(0) == "0"
        assert fmt_diff(1) == "1.00"
        assert fmt_diff(999) == "999.00"

    def test_kilo(self):
        assert fmt_diff(1000) == "1.00 K"
        assert fmt_diff(5000) == "5.00 K"

    def test_mega(self):
        assert fmt_diff(1_000_000) == "1.00 M"
        assert fmt_diff(2_500_000) == "2.50 M"

    def test_giga(self):
        assert fmt_diff(1_000_000_000) == "1.00 G"
        assert fmt_diff(5_500_000_000) == "5.50 G"

    def test_tera(self):
        assert fmt_diff(1_000_000_000_000) == "1.00 T"
        # 110T
        assert fmt_diff(110_000_000_000_000) == "110.00 T"
        # 25.73T
        assert fmt_diff(25_730_000_000_000) == "25.73 T"

    def test_peta(self):
        assert fmt_diff(1_000_000_000_000_000) == "1.00 P"

    def test_exa(self):
        assert fmt_diff(1_000_000_000_000_000_000) == "1.00 E"

    def test_none_and_empty(self):
        """None is treated as falsy => returns '0'."""
        assert fmt_diff(None) == "0"
        assert fmt_diff(0) == "0"

    def test_string_input(self):
        """fmt_diff does NOT parse strings — call parse_diff_to_float first.
        This test documents the current behavior: float() on a string raises ValueError."""
        with pytest.raises(ValueError):
            fmt_diff("25.73 T")

    def test_negative_values(self):
        """Negative values are NOT abs'd — they show as negative raw numbers."""
        result = fmt_diff(-1000)
        assert result == "-1000.00"


# ═══════════════════════════════════════════════════════════════════════════
# 5. parse_diff_to_float
# ═══════════════════════════════════════════════════════════════════════════

class TestParseDiffToFloat:
    """Parse difficulty strings like '25.73 T' to float values."""

    def test_tera(self):
        assert parse_diff_to_float("25.73 T") == pytest.approx(25.73e12, rel=1e-3)
        assert parse_diff_to_float("110 T") == pytest.approx(110e12, rel=1e-3)

    def test_giga(self):
        assert parse_diff_to_float("5.5 G") == pytest.approx(5.5e9, rel=1e-3)

    def test_mega(self):
        assert parse_diff_to_float("100 M") == pytest.approx(100e6, rel=1e-3)

    def test_kilo(self):
        assert parse_diff_to_float("50 K") == pytest.approx(50e3, rel=1e-3)

    def test_peta(self):
        assert parse_diff_to_float("1.5 P") == pytest.approx(1.5e15, rel=1e-3)

    def test_no_suffix(self):
        assert parse_diff_to_float("5000") == 5000.0

    def test_number_input(self):
        """Direct number input passes through."""
        assert parse_diff_to_float(25.73e12) == pytest.approx(25.73e12, rel=1e-3)

    def test_comma_decimal(self):
        """European decimal format."""
        assert parse_diff_to_float("25,73 T") == pytest.approx(25.73e12, rel=1e-3)

    def test_invalid_input(self):
        """Invalid strings return 0."""
        assert parse_diff_to_float("not a number") == 0.0
        assert parse_diff_to_float("") == 0.0

    def test_none(self):
        assert parse_diff_to_float(None) == 0.0

    def test_spaces(self):
        assert parse_diff_to_float("  110 T  ") == pytest.approx(110e12, rel=1e-3)
