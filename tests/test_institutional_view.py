"""Hermetic tests for the HashratePulse Enterprise institutional view upgrade.

Covers the CFO audit fixes in services/hashrate_market.py:
  1. VWAP is liquidity-WEIGHTED (a huge venue's price must dominate the
     benchmark, not a naive mean).
  2. Snapshot exposes median + price range (executive summary depth).
  3. rent_vs_own benchmark: rental cost vs owned-hardware mining cost,
     with cheaper/premium flags + notes.
  4. Regime detection preserved (Tight/Normal/Wide/Dislocated).
  5. Deepest-venue note only fires for real (non-estimated) deep venues.
"""

import os
import sys

import pytest

sys.path.insert(0, ".")

from services.hashrate_market import (  # noqa: E402
    NormalizedOffer,
    compute_institutional_view,
    _estimate_own_mining_cost_usd_per_th_day,
)


def _offer(provider, price_btc_ph_day, hashrate_th=1000.0, estimated=False):
    """Build a NormalizedOffer from BTC/PH/day (the unit the UI shows)."""
    return NormalizedOffer(
        provider=provider,
        hashrate=hashrate_th,
        price_per_th_day=price_btc_ph_day / 1000.0,  # PH→TH
        duration_days=1.0,
        fee_pct=0.0,
        algorithm="sha256",
        source=provider,
        estimated=estimated,
    )


def _offers_standard():
    return [
        _offer("braiins", 0.000100, hashrate_th=1000),  # 100 PH
        _offer("nicehash", 0.000110, hashrate_th=20000),  # 20000 TH = 20 PH
        _offer("mrr", 0.000120, hashrate_th=100000),  # 100000 TH = 100 PH
    ]


# ── No data / degenerate ────────────────────────────────────────────────────


def test_no_data_returns_empty_view():
    r = compute_institutional_view([], None, None)
    assert r["regime"] == "No Data"
    assert r["snapshot"] is None
    assert r["venues"] == []
    assert r["notes"] == []


# ── VWAP: liquidity-weighted ────────────────────────────────────────────────


def test_vwap_is_liquidity_weighted_not_naive_mean():
    offers = [
        _offer("braiins", 0.000100, hashrate_th=1000),  # 1 PH — cheap, tiny
        _offer("mrr", 0.000300, hashrate_th=1000000),  # 1000 PH — expensive, huge
    ]
    r = compute_institutional_view(offers, None, None)
    vwap = r["snapshot"]["vwap_4h_btc_ph_day"]
    # Naive mean would be 0.000200. The weighted VWAP must lean heavily
    # toward the 1000-PH venue (0.0003), proving weight > naive mean.
    assert vwap > 0.000200
    assert 0.000290 < vwap <= 0.000300


def test_vwap_single_offer_equals_its_price():
    r = compute_institutional_view([_offer("braiins", 0.000150)], None, None)
    assert r["snapshot"]["vwap_4h_btc_ph_day"] == 0.000150


# ── Median + range ──────────────────────────────────────────────────────────


def test_snapshot_exposes_median_and_range():
    r = compute_institutional_view(_offers_standard(), None, None)
    snap = r["snapshot"]
    assert snap["median_btc_ph_day"] == 0.000110  # middle of [100,110,120]
    assert snap["price_range_btc_ph_day"] == [0.000100, 0.000120]
    assert snap["offer_count"] == 3


# ── Regime detection ────────────────────────────────────────────────────────


def test_regime_tight_when_spread_small():
    offers = [
        _offer("braiins", 0.000100),
        _offer("nicehash", 0.000102),
        _offer("mrr", 0.000104),
    ]
    assert compute_institutional_view(offers, None, None)["regime"] == "Tight"


def test_regime_wide_when_spread_elevated():
    offers = [
        _offer("braiins", 0.000100),
        _offer("nicehash", 0.000115),
        _offer("mrr", 0.000130),
    ]
    assert compute_institutional_view(offers, None, None)["regime"] == "Wide"


# ── Rent vs own benchmark ───────────────────────────────────────────────────


def test_rent_vs_own_cheaper_than_own():
    # Cheap rental + normal BTC price → renting beats owned hardware.
    offers = [_offer("braiins", 0.000030)]
    r = compute_institutional_view(offers, None, btc_usd=60000.0)
    rvo = r["snapshot"]["rent_vs_own"]
    assert rvo is not None
    assert rvo["cheaper_than_own"] is True
    assert rvo["discount_pct"] > 0
    assert rvo["premium_pct"] == 0
    # Rental of 30k sat/TH/d ≈ 0.0003 BTC/TH/d * 60000 ≈ $18/TH/d… wait,
    # best_price is BTC/TH/day: 0.000030/1000 = 3e-8 BTC/TH/d * 1e8 = 3 sat
    # → $0.0018/TH/d. Own ~ $0.041 → renting ~2.4% of own cost.
    assert rvo["ratio"] < 1.0
    # Note surfaced for the operator.
    assert any("CHEAPER" in n for n in r["notes"])


def test_rent_vs_own_more_expensive_than_own():
    # Expensive rental → own fleet is cheaper; note must say MORE.
    offers = [_offer("braiins", 0.001000)]
    r = compute_institutional_view(offers, None, btc_usd=60000.0)
    rvo = r["snapshot"]["rent_vs_own"]
    assert rvo is not None
    assert rvo["cheaper_than_own"] is False
    assert rvo["premium_pct"] > 0
    assert rvo["discount_pct"] == 0
    assert any("MORE" in n for n in r["notes"])


def test_rent_vs_own_none_without_btc_usd():
    r = compute_institutional_view(_offers_standard(), None, btc_usd=None)
    assert r["snapshot"]["rent_vs_own"] is None
    # No rent-vs-own note without a USD price.
    assert not any("CHEAPER" in n or "MORE" in n for n in r["notes"])


def test_own_cost_estimator_defaults():
    cost = _estimate_own_mining_cost_usd_per_th_day()
    assert cost is not None and cost > 0
    # S19-class 30 J/TH @ 5c/kWh + 15% → ≈ 0.0414 USD/TH/day
    assert 0.02 < cost < 0.08


def test_own_cost_estimator_env_override(monkeypatch):
    # env var wins over the default arg; 10c/kWh must cost more than 5c/kWh.
    monkeypatch.setenv("ELECTRICITY_USD_KWH", "0.10")
    cost_at_10c = _estimate_own_mining_cost_usd_per_th_day()
    assert cost_at_10c is not None
    monkeypatch.delenv("ELECTRICITY_USD_KWH", raising=False)
    cost_at_5c = _estimate_own_mining_cost_usd_per_th_day()
    assert cost_at_5c is not None
    # Double the electricity price → strictly higher all-in cost.
    assert cost_at_10c > cost_at_5c
    assert abs(cost_at_10c - 2 * cost_at_5c) < 0.002  # pure linear in price


# ── Deepest-venue note ──────────────────────────────────────────────────────


def test_deepest_venue_note_only_for_real_deep_venues():
    offers = [
        _offer("braiins", 0.000100, hashrate_th=8000000),  # 8000 PH — deep
        _offer("nicehash", 0.000110, hashrate_th=1000),
    ]
    r = compute_institutional_view(offers, None, None)
    assert any("deepest visible liquidity" in n for n in r["notes"])
    assert "braiins" in " ".join(r["notes"])


def test_no_deepest_note_when_all_thin():
    offers = [
        _offer("braiins", 0.000100, hashrate_th=1000),
        _offer("nicehash", 0.000110, hashrate_th=2000),
    ]
    r = compute_institutional_view(offers, None, None)
    assert not any("deepest visible liquidity" in n for n in r["notes"])


# ── Venue table sanity ──────────────────────────────────────────────────────


def test_venue_rows_carry_usd_price_input_fields():
    r = compute_institutional_view(_offers_standard(), None, btc_usd=50000.0)
    assert len(r["venues"]) == 3
    v0 = r["venues"][0]
    # price_btc_ph_day is BTC/PH/day; the JS converts to USD/TH/d.
    assert v0["price_btc_ph_day"] == 0.000100
    assert v0["risk_tier"] >= 1
    assert v0["recommendation"]
    assert v0["estimated"] is False


# ── M4/M5: freshness + profit columns exposed by the view ──────────────────


def test_venue_rows_expose_metrics_score_roi_ev():
    """M5: score/roi/EV were computed by compute_metrics() but dropped at the
    view boundary — the panel now ranks by value, not just sticker price."""
    r = compute_institutional_view(_offers_standard(), None, btc_usd=50000.0)
    assert len(r["venues"]) == 3
    for v in r["venues"]:
        # Every venue must carry the profit-oriented columns (nullable OK
        # on legacy payloads, but the view itself always computes them).
        assert "score" in v
        assert "roi_pct" in v
        assert "expected_value_btc" in v
        assert "estimated_cost_btc" in v
        assert "risk_level" in v
        assert v["score"] is not None
        assert v["roi_pct"] is not None
        assert v["expected_value_btc"] is not None
    # Cheapest venue is the only realistic one → EV should be sane (a real
    # float, not None) and score derived from ROI.
    best = min(r["venues"], key=lambda v: v["price_btc_ph_day"])
    assert isinstance(best["roi_pct"], float)
    assert isinstance(best["expected_value_btc"], float)


def test_venue_fetched_at_stamped_when_meta_has_it():
    """M4: fetched_at passes through from offer.meta (stamped by
    _cached_fetch) so the panel can show quote freshness. Absent meta → None
    (frontend shows '—'), never a crash."""
    # Offers built without meta → fetched_at must be None (not KeyError).
    r = compute_institutional_view(_offers_standard(), None, btc_usd=None)
    assert all(v["fetched_at"] is None for v in r["venues"])

    # Offer WITH meta.fetched_at → passthrough.
    import dataclasses

    offers = [
        dataclasses.replace(
            _offer("braiins", 0.000100, hashrate_th=1000),
            meta={"fetched_at": 1234567890, "available_asks": 3},
        )
    ]
    r2 = compute_institutional_view(offers, None, btc_usd=None)
    assert r2["venues"][0]["fetched_at"] == 1234567890
    assert r2["venues"][0]["meta"]["available_asks"] == 3
