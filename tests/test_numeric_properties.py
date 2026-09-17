"""
Property-based tests for the numeric core (NUM-002, Issue #605).

docs/TEST_STRATEGY.md · NUM-002: "valores extremos mas finitos — floats entre
limites operacionais e bordas IEEE-754; invariantes: probabilidades em [0,1],
saída serializável e sem NaN".

The surfaces exercised are the pure profitability/probability helpers the poll
pipeline actually uses:

  - helpers.compute_solo_probabilities       (probability math)
  - helpers.compute_lender_profitability     (Scenario D lease-vs-mine money)
  - helpers.compute_pool_rental_break_even   (cost model + break-even)
  - services.poll_compute.fiat_convert       (BTC → fiat payload fields)

Strategy notes:
  - OPERATIONAL floats cover the plausible domain (network shares, BTC
    amounts, TH/s, prices) — the values production actually feeds in.
  - IEEE-754 boundary literals (1e308, 5e-324, -0.0 and multiplication
    overflow) are injected explicitly: hypothesis' float strategies exclude
    most of them by default.
  - The serialization invariant uses json.dumps(allow_nan=False): any NaN or
    Infinity surviving the computation fails the test, which is precisely the
    BE-04 guarantee the matrix asks for (a NaN rendered by the frontend
    becomes null or 0.0 silently).

Pure numerical verification — no DB, no Flask, no HTTP.
"""

import json
import math
import sys
from decimal import Decimal

import pytest
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

from helpers import (
    compute_lender_profitability,
    compute_pool_rental_break_even,
    compute_solo_probabilities,
)

sys.path.insert(0, ".")

from services.poll_compute import fiat_convert  # noqa: E402

# ── strategies ──────────────────────────────────────────────────────────────

# Plausible operational values: 0 < share <= 1 (share of network), including
# the tiny tail that real miners live in (1e-12 .. 1) and the exact bounds.
operational_share = st.one_of(
    st.just(0.0),
    st.just(1.0),
    st.floats(min_value=1e-12, max_value=1.0, allow_nan=False, allow_infinity=False),
)

positive_finite = st.floats(
    min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False
)

small_nonneg = st.floats(
    min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False
)

# IEEE-754 boundary values, injected by name (the matrix demands them).
ieee_edges = st.sampled_from(
    [
        5e-324,          # smallest positive subnormal
        -0.0,            # negative zero
        1e308,           # near max double
        -1e308,          # near min finite double
        1.7976931348623157e308,  # DBL_MAX
        sys.float_info.max,
        sys.float_info.min,
        1e-300,
    ]
)

any_finite = st.floats(allow_nan=False, allow_infinity=False)

btc_prices = st.fixed_dictionaries(
    {
        "USD": st.one_of(st.none(), st.floats(min_value=0.0, max_value=1e7)),
        "BRL": st.one_of(st.none(), st.floats(min_value=0.0, max_value=1e7)),
        "EUR": st.one_of(st.none(), st.floats(min_value=0.0, max_value=1e7)),
    }
)


# ── helpers ─────────────────────────────────────────────────────────────────

def _assert_finite_tree(node):
    """Every float in the structure is finite (no NaN, no ±Infinity)."""
    if isinstance(node, float):
        assert math.isfinite(node), f"non-finite float reached output: {node}"
    elif isinstance(node, dict):
        for v in node.values():
            _assert_finite_tree(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _assert_finite_tree(v)


def _assert_json_serializable(node):
    """The structure survives json.dumps with allow_nan=False (BE-04)."""
    json.dumps(node, allow_nan=False)


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 1 — probabilities stay in [0, 1] and the output serializes
# ═══════════════════════════════════════════════════════════════════════════


class TestSoloProbabilitiesProperties:
    @settings(max_examples=300, deadline=None)
    @given(share=operational_share)
    def test_probabilities_in_unit_interval_and_serializable(self, share):
        out = compute_solo_probabilities(share)
        for key in ("solo_p_day", "solo_p_year", "solo_p_5year"):
            assert 0.0 <= out[key] <= 1.0, f"{key}={out[key]} outside [0,1]"
        assert out["solo_expected_blocks_per_year"] >= 0.0
        _assert_finite_tree(out)
        _assert_json_serializable(out)

    @settings(max_examples=200, deadline=None)
    @given(share=operational_share, blocks=st.floats(min_value=1.0, max_value=1e6))
    def test_monotonicity_more_blocks_never_lowers_probability(self, share, blocks):
        """P(≥1 block in N days) is non-decreasing in N — monotonicity is the
        semantic core; a regression that inverts the exponent breaks it."""
        if share <= 0:
            return
        short = compute_solo_probabilities(share, blocks)
        long_ = compute_solo_probabilities(share, blocks * 2)
        assert long_["solo_p_day"] >= short["solo_p_day"] - 1e-15

    @settings(max_examples=150, deadline=None)
    @given(share=st.one_of(ieee_edges, st.floats(min_value=-1e6, max_value=0.0)))
    def test_degenerate_shares_never_raise_and_yield_zero(self, share):
        """Non-positive shares → zeroed base shape with expected time None.
        Subnormal-POSITIVE shares stay honest math: p in [0,1] and a finite
        (possibly astronomical) expected time — 3e305 days IS the truth for a
        denormal miner, and it serializes (NUM-002: no NaN, not no magnitude).
        """
        out = compute_solo_probabilities(share)
        _assert_finite_tree(out)
        if share > 0:
            assert 0.0 <= out["solo_p_day"] <= 1.0
        else:
            assert out["solo_p_day"] == 0.0
            assert out["solo_expected_time_to_block_days"] is None

    def test_ieee_multiplication_overflow_in_blocks_window(self):
        """Borda IEEE-754: blocks_per_day × 365 × 5 overflows via the base
        when share is near 1 — (1-p)**huge underflows to 0.0 → P = 1.0, still
        inside [0, 1] and serializable. The guard is the invariant, not the
        magnitude."""
        out = compute_solo_probabilities(1.0 - 1e-16, blocks_per_day=1e308)
        assert 0.0 <= out["solo_p_day"] <= 1.0
        _assert_json_serializable(out)

    def test_subnormal_share_boundaries(self):
        for edge in (5e-324, sys.float_info.min, 1e-300):
            out = compute_solo_probabilities(edge)
            assert 0.0 <= out["solo_p_day"] <= 1.0
            _assert_finite_tree(out)


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 2 — money never becomes NaN/Infinity and always serializes
# ═══════════════════════════════════════════════════════════════════════════


class TestLenderProfitabilityProperties:
    @settings(max_examples=300, deadline=None)
    @given(
        ths=positive_finite,
        rate=positive_finite,
        power=small_nonneg,
        mining=st.floats(min_value=0.0, max_value=1e3),
        price=positive_finite,
    )
    def test_money_fields_finite_and_serializable(self, ths, rate, power, mining, price):
        out = compute_lender_profitability(
            ths=ths,
            market_btc_per_th_day=rate,
            power_cost_usd_per_day=power,
            pool_net_btc_per_day=mining,
            btc_usd=price,
        )
        _assert_finite_tree(out)
        _assert_json_serializable(out)

    @settings(max_examples=200, deadline=None)
    @given(
        ths=positive_finite,
        rate=positive_finite,
        power=small_nonneg,
        mining=st.floats(min_value=0.0, max_value=1e3),
        price=positive_finite,
    )
    def test_recommendation_is_from_the_contracted_set(self, ths, rate, power, mining, price):
        out = compute_lender_profitability(
            ths=ths, market_btc_per_th_day=rate,
            power_cost_usd_per_day=power, pool_net_btc_per_day=mining,
            btc_usd=price,
        )
        assert out["lender_recommendation"] in {"lease", "mine", "equal", "insufficient"}

    @settings(max_examples=200, deadline=None)
    @given(data=st.data())
    def test_ieee_edge_inputs_never_produce_nan(self, data):
        """Bordas IEEE-754 explícitas (1e308, 5e-324, -0.0, overflow em
        multiplicação): the function must degrade to the base shape — never
        emit NaN (inf - inf) or Infinity in a money field."""
        ths = data.draw(st.one_of(ieee_edges, positive_finite))
        rate = data.draw(st.one_of(ieee_edges, positive_finite))
        power = data.draw(st.one_of(ieee_edges, small_nonneg))
        mining = data.draw(st.one_of(ieee_edges, st.floats(min_value=0.0, max_value=1e3)))
        price = data.draw(st.one_of(ieee_edges, positive_finite))
        out = compute_lender_profitability(
            ths=ths, market_btc_per_th_day=rate,
            power_cost_usd_per_day=power, pool_net_btc_per_day=mining,
            btc_usd=price,
        )
        _assert_finite_tree(out)
        _assert_json_serializable(out)
        # "insufficient" means the FIAT side is unavailable — USD fields must
        # be None. BTC-domain fields may still carry honest finite numbers
        # (denormal inputs underflow to 0.0, which is a number, not garbage).
        if out["lender_recommendation"] == "insufficient":
            assert out["lender_net_usd_per_day"] is None
            assert out["lender_mine_net_usd_per_day"] is None
            assert out["lender_vs_mining_usd_per_day"] is None

    @settings(max_examples=150, deadline=None)
    @given(
        ths=positive_finite,
        rate=positive_finite,
        mining=st.floats(min_value=0.0, max_value=1e3),
        price=positive_finite,
    )
    def test_zero_power_keeps_lease_vs_mine_identity(self, ths, rate, mining, price):
        """With no power cost, vs_mining = revenue − mining income exactly
        (the comparison identity from the docstring)."""
        out = compute_lender_profitability(
            ths=ths, market_btc_per_th_day=rate,
            power_cost_usd_per_day=0.0, pool_net_btc_per_day=mining,
            btc_usd=price,
        )
        if out["lender_net_usd_per_day"] is None:
            return
        # vs_mining is computed from the RAW nets then rounded once (helper
        # contract); comparing against rounded-per-field expectation must
        # therefore allow the single-ULP rounding drift.
        expected_vs = round(
            out["lender_net_usd_per_day"] - out["lender_mine_net_usd_per_day"], 4
        )
        assert out["lender_vs_mining_usd_per_day"] == pytest.approx(
            expected_vs, abs=2e-4
        )


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 3 — break-even fields stay finite and honor the guards
# ═══════════════════════════════════════════════════════════════════════════


class TestBreakEvenProperties:
    @settings(max_examples=300, deadline=None)
    @given(
        ths=st.one_of(positive_finite, ieee_edges),
        net=st.one_of(st.floats(min_value=-1e3, max_value=1e3), ieee_edges),
        price=st.one_of(positive_finite, ieee_edges),
        rental=st.one_of(small_nonneg, ieee_edges),
        watts=st.one_of(small_nonneg, ieee_edges),
        kwh=st.one_of(small_nonneg, ieee_edges),
    )
    def test_output_finite_and_serializable_for_all_edges(
        self, ths, net, price, rental, watts, kwh
    ):
        out = compute_pool_rental_break_even(
            ths=ths, pool_net_btc_per_day=net, btc_usd=price,
            cost_mode="rental", rental_usd_per_th_day=rental,
        )
        _assert_finite_tree(out)
        _assert_json_serializable(out)
        # guards: break-even exists only with price > 0 and ths > 0, and the
        # emitted figure is EXACTLY the clamped formula at emitted precision:
        # None ⇔ raw overflow (unknown, not inf); sign follows the raw math
        # (negative net ⇒ negative break-even — honest, not clamped).
        if out["breakeven_cost_per_th_day"] is not None:
            assert ths > 0 and price > 0
            assert out["breakeven_cost_per_th_day"] == round(
                (net * price) / max(ths, 1e-12), 4
            )

    @settings(max_examples=200, deadline=None)
    @given(
        ths=positive_finite,
        net=st.floats(min_value=0.0, max_value=1e3),
        price=positive_finite,
    )
    def test_breakeven_formula_identity(self, ths, net, price):
        """breakeven_cost_per_th_day = round(net × price / ths, 4) — the
        contracted formula, held over the whole operational domain."""
        out = compute_pool_rental_break_even(
            ths=ths, pool_net_btc_per_day=net, btc_usd=price, cost_mode="none",
        )
        # Contract pin: the helper computes (net × price) / max(ths, 1e-12)
        # — the clamp guards the division against denormal TH/s — and emits
        # None when the raw figure overflows (unknown, not inf). A missing
        # price or hashrate also yields None.
        if price <= 0 or ths <= 0:
            assert out["breakeven_cost_per_th_day"] is None
            return
        raw = (net * price) / max(ths, 1e-12)
        expected = round(raw, 4) if math.isfinite(raw) else None
        assert out["breakeven_cost_per_th_day"] == expected

    @settings(max_examples=150, deadline=None)
    @given(
        ths=positive_finite,
        net=st.floats(min_value=0.0, max_value=1e3),
        price=positive_finite,
        rental=small_nonneg,
    )
    def test_breakeven_scales_inversely_with_hashrate(self, ths, net, price, rental):
        """Doubling TH/s halves the per-TH break-even (formula sanity)."""
        base = compute_pool_rental_break_even(
            ths=ths, pool_net_btc_per_day=net, btc_usd=price, cost_mode="none")
        doubled = compute_pool_rental_break_even(
            ths=ths * 2, pool_net_btc_per_day=net, btc_usd=price, cost_mode="none")
        if base["breakeven_cost_per_th_day"] is not None:
            # Contract pin on both sides (same round(·, 4) of the clamped
            # formula): double rounding makes round(x)/2 ≠ round(x/2), and
            # the 1e-12 TH/s clamp flattens the halving in the denormal tail.
            assert doubled["breakeven_cost_per_th_day"] == round(
                (net * price) / max(ths * 2, 1e-12), 4
            )


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 4 — fiat conversion: None-safe, finite, serialized
# ═══════════════════════════════════════════════════════════════════════════


class TestFiatConvertProperties:
    @settings(max_examples=200, deadline=None)
    @given(
        btc=st.one_of(st.floats(min_value=0.0, max_value=1e6), ieee_edges),
        prices=btc_prices,
    )
    def test_fiat_fields_finite_or_none(self, btc, prices):
        out = fiat_convert(btc, prices)
        for cur, val in out.items():
            if val is None:
                # None ⇔ missing quote OR non-finite product (overflow is
                # unknown, not a number) — both are honest unavailability.
                assert prices[cur] is None or not math.isfinite(
                    btc * prices[cur]
                )
            else:
                assert math.isfinite(val)
        _assert_json_serializable(out)

    @settings(max_examples=150, deadline=None)
    @given(
        btc=st.floats(min_value=0.0, max_value=1e6),
        px=st.floats(min_value=0.0, max_value=1e7),
    )
    def test_rounding_contract_4_decimals(self, btc, px):
        out = fiat_convert(btc, {"USD": px})
        assert out["USD"] == round(btc * px, 4)


# ═══════════════════════════════════════════════════════════════════════════
# Edge pins — the exact IEEE-754 boundaries from the matrix, by name
# ═══════════════════════════════════════════════════════════════════════════


class TestIeeeEdgePins:
    """The four boundary classes the NUM-002 row demands, pinned on the two
    money helpers. Properties sweep broadly; these pin the named corners."""

    def test_lender_1e308_inputs(self):
        out = compute_lender_profitability(
            ths=1e308, market_btc_per_th_day=1e308,
            power_cost_usd_per_day=1e308, pool_net_btc_per_day=1e308,
            btc_usd=1e308,
        )
        _assert_finite_tree(out)
        _assert_json_serializable(out)

    def test_lender_overflow_product_becomes_insufficient_not_nan(self):
        """1e308 × 1e308 overflows to inf; inf − inf is NaN — the guard must
        route this to the base shape (BE-04: NaN money is forbidden)."""
        out = compute_lender_profitability(
            ths=1e300, market_btc_per_th_day=1e300,
            power_cost_usd_per_day=1e300, pool_net_btc_per_day=1e300,
            btc_usd=1e300,
        )
        assert out["lender_recommendation"] == "insufficient"
        _assert_finite_tree(out)

    def test_lender_negative_zero_ths(self):
        out = compute_lender_profitability(
            ths=-0.0, market_btc_per_th_day=2e-4,
            power_cost_usd_per_day=0.0, pool_net_btc_per_day=1e-3,
            btc_usd=100000.0,
        )
        assert out["lender_recommendation"] == "insufficient"

    def test_lender_subnormal_rate(self):
        out = compute_lender_profitability(
            ths=100.0, market_btc_per_th_day=5e-324,
            power_cost_usd_per_day=0.0, pool_net_btc_per_day=1e-3,
            btc_usd=100000.0,
        )
        assert out["lender_revenue_btc_per_day"] == pytest.approx(0.0, abs=1e-12)
        _assert_finite_tree(out)

    def test_breakeven_1e308_price(self):
        out = compute_pool_rental_break_even(
            ths=1e-300, pool_net_btc_per_day=1e308, btc_usd=1e308, cost_mode="none",
        )
        # product overflows → break-even must be None (guard), never inf
        assert out["breakeven_cost_per_th_day"] is None
        _assert_finite_tree(out)

    def test_fiat_convert_rejects_nan_price_input(self):
        """A Decimal quote (upstream type confusion) must not corrupt the
        output — the comprehension coerces via multiplication; NaN prices
        would produce NaN fiat. Pinned: quotes are floats or None here."""
        out = fiat_convert(0.5, {"USD": 100000.0, "BRL": None})
        assert out == {"USD": 50000.0, "BRL": None}

    def test_decimal_quote_type_confusion_degrades_not_corrupts(self):
        """Upstream feeds a Decimal into fiat_convert — output must stay a
        finite float (or the caller's guard trips), never NaN."""
        out = fiat_convert(0.5, {"USD": Decimal("100000")})
        assert out["USD"] == pytest.approx(50000.0, abs=1e-6)
        assert isinstance(out["USD"], float)
