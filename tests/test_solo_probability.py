"""
Unit tests for helpers.compute_solo_probabilities — the corrected solo-mining
probability math used by app.py._do_poll().

Locks the formulas against regression:
  - solo_p_day      = 1 - (1 - p)^144            (p = per-BLOCK chance)
  - solo_p_year     = 1 - (1 - p)^(144·365)
  - solo_p_5year    = 1 - (1 - p)^(144·365·5)
  - expected_blocks = p × 144 × 365
  - expected_time   = 1 / (p × 144)   days       (NOT 1/p — the old bug)

Pure numerical verification — no DB, no Flask, no HTTP.
See tests/test_risk_formulas.py for the companion approach.
"""

import math
import pytest

from helpers import compute_solo_probabilities


# ══════════════════════════════════════════════════════════════════════
# Known-value lock: p = 1e-6 (0.0001% of network)
# ══════════════════════════════════════════════════════════════════════

class TestKnownValues:
    """Hardcoded expected values for p = 1e-6, computed independently."""

    P = 1e-6

    def test_expected_time_to_block_days(self):
        """1/(p·144) = 1/(1e-6·144) = 6944.44 days (~19 years)."""
        out = compute_solo_probabilities(self.P)
        assert out["solo_expected_time_to_block_days"] == pytest.approx(
            6944.444444, rel=1e-6
        )

    def test_expected_blocks_per_year(self):
        """p·144·365 = 1e-6·52560 = 0.05256 blocks/year."""
        out = compute_solo_probabilities(self.P)
        assert out["solo_expected_blocks_per_year"] == pytest.approx(0.05256, rel=1e-6)

    def test_p_day(self):
        """1-(1-p)^144 = 1.43989704e-4 (vs old bug: p = 1e-6)."""
        out = compute_solo_probabilities(self.P)
        assert out["solo_p_day"] == pytest.approx(1.4398970449e-4, rel=1e-5)

    def test_p_year(self):
        """1-(1-p)^(144·365) = 5.12026334e-2."""
        out = compute_solo_probabilities(self.P)
        assert out["solo_p_year"] == pytest.approx(0.051202633431, rel=1e-5)

    def test_p_5year(self):
        """1-(1-p)^(144·365·5) = 0.23110443997."""
        out = compute_solo_probabilities(self.P)
        assert out["solo_p_5year"] == pytest.approx(0.231104439972, rel=1e-5)


# ══════════════════════════════════════════════════════════════════════
# Formula identity (mirrors definition but keeps the 144 factor explicit)
# ══════════════════════════════════════════════════════════════════════

class TestFormulaIdentity:
    """Each output equals its mathematical definition (with 144 blocks/day)."""

    def test_all_keys_present(self):
        out = compute_solo_probabilities(2e-6)
        assert set(out.keys()) == {
            "solo_p_day",
            "solo_p_year",
            "solo_p_5year",
            "solo_expected_blocks_per_year",
            "solo_expected_time_to_block_days",
        }

    @pytest.mark.parametrize("p", [1e-8, 1e-6, 1e-4, 0.001, 0.01])
    def test_formulas_match_definition(self, p):
        out = compute_solo_probabilities(p)
        assert out["solo_p_day"] == pytest.approx(1 - (1 - p) ** 144)
        assert out["solo_p_year"] == pytest.approx(1 - (1 - p) ** (144 * 365))
        assert out["solo_p_5year"] == pytest.approx(1 - (1 - p) ** (144 * 365 * 5))
        assert out["solo_expected_blocks_per_year"] == pytest.approx(p * 144 * 365)
        assert out["solo_expected_time_to_block_days"] == pytest.approx(1.0 / (p * 144))


# ══════════════════════════════════════════════════════════════════════
# Regression guards — must FAIL if someone reverts to the old buggy math
# ══════════════════════════════════════════════════════════════════════

class TestRegressionGuards:
    """Catch the pre-fix bugs: expected_time = 1/p and solo_p_day = p."""

    def test_expected_time_is_NOT_one_over_p(self):
        """Old bug returned 1/p (144× too large). Must stay ~1/(p·144)."""
        p = 1e-6
        out = compute_solo_probabilities(p)
        old_bug_value = 1.0 / p  # 1,000,000 days
        assert out["solo_expected_time_to_block_days"] != pytest.approx(old_bug_value)
        assert out["solo_expected_time_to_block_days"] < old_bug_value / 100.0

    def test_p_day_is_NOT_raw_share(self):
        """Old bug used the per-block chance directly as the daily chance."""
        p = 1e-6
        out = compute_solo_probabilities(p)
        assert out["solo_p_day"] != pytest.approx(p)
        # Correct daily P is ~144× the per-block chance for small p.
        assert out["solo_p_day"] > p * 100.0

    def test_p_year_is_NOT_one_minus_one_minus_p_365(self):
        """Old bug used 365 days, not 144·365 blocks."""
        p = 1e-6
        out = compute_solo_probabilities(p)
        old_bug_value = 1 - (1 - p) ** 365
        assert out["solo_p_year"] != pytest.approx(old_bug_value)

    def test_expected_blocks_is_NOT_p_times_365(self):
        """Old bug counted 365 blocks/year instead of 144·365."""
        p = 1e-6
        out = compute_solo_probabilities(p)
        old_bug_value = p * 365
        assert out["solo_expected_blocks_per_year"] != pytest.approx(old_bug_value)
        assert out["solo_expected_blocks_per_year"] == pytest.approx(old_bug_value * 144)


# ══════════════════════════════════════════════════════════════════════
# Edge cases
# ══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_zero_share_returns_zeros_and_none_time(self):
        out = compute_solo_probabilities(0.0)
        assert out["solo_p_day"] == 0.0
        assert out["solo_p_year"] == 0.0
        assert out["solo_p_5year"] == 0.0
        assert out["solo_expected_blocks_per_year"] == 0.0
        assert out["solo_expected_time_to_block_days"] is None

    def test_negative_share_is_safe(self):
        """Guards divide-by-zero: never raises."""
        out = compute_solo_probabilities(-0.5)
        assert out["solo_expected_time_to_block_days"] is None
        assert out["solo_p_day"] == 0.0

    def test_none_share_is_safe(self):
        out = compute_solo_probabilities(None)
        assert out["solo_expected_time_to_block_days"] is None
        assert out["solo_p_day"] == 0.0

    def test_full_network_certainty(self):
        """p=1 → block today is certain; expected time = 1/144 day."""
        out = compute_solo_probabilities(1.0)
        assert out["solo_p_day"] == pytest.approx(1.0)
        assert out["solo_expected_time_to_block_days"] == pytest.approx(1.0 / 144)

    def test_default_blocks_per_day_is_144(self):
        """Sanity: defaults match the documented 144 blocks/day."""
        p = 3e-6
        default_out = compute_solo_probabilities(p)
        explicit_out = compute_solo_probabilities(p, blocks_per_day=144.0)
        assert default_out == explicit_out
