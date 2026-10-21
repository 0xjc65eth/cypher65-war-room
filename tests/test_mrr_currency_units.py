"""Issue #843: no implicit FX and no undeclared hashrate units."""

import json

import pytest

from services import rental_performance as rp


def raw_rental(currency="BTC", unit="th", paid="0.0001"):
    return {
        "id": "fixture843",
        "hashrate": {
            "advertised": {"hash": "100", "type": unit},
            "average": {"hash": "90", "type": unit, "percent": "90"},
        },
        "price": {"paid": paid, "currency": currency},
        "length": "2",
        "ended": True,
        "rig": {"id": "fixture-rig843", "type": "sha256"},
    }


@pytest.mark.parametrize("currency", ["LTC", "ETH", "DOGE", "BCH", "XYZ", None, ""])
def test_non_btc_or_undeclared_payments_never_become_btc(currency):
    row = rp._normalize_rental(raw_rental(currency))
    assert row["price_paid_btc"] is None
    assert row["price_paid_amount"] == 0.0001
    assert row["price_currency"] == (currency or None)
    assert row["price_observed_at"] is None
    assert row["price_source"] == "mrr_api_v2"
    json.dumps(row, allow_nan=False)


def test_btc_payment_preserves_existing_contract_and_original_amount():
    row = rp._normalize_rental(raw_rental())
    assert row["price_paid_btc"] == pytest.approx(0.0001)
    assert row["price_paid_amount"] == pytest.approx(0.0001)
    assert row["price_currency"] == "BTC"
    assert rp.compute_mrr_perf(raw_rental())["cost_sats_per_thh"] == pytest.approx(
        10000 / 180
    )


@pytest.mark.parametrize("currency", ["LTC", "ETH", "DOGE", "BCH", None])
def test_detail_and_shared_pl_ignore_non_btc_even_if_caller_passes_sats(currency):
    perf = rp.compute_mrr_perf(raw_rental(currency))
    assert perf["cost_sats_per_thh"] is None
    assert perf["paid_sats"] is None
    assert perf["paid_amount"] == pytest.approx(0.0001)
    assert perf["payment_currency"] == currency
    pl = rp.attach_pl(perf, 10000, network_hashrate_hs=1e20)
    assert pl["available"] is False
    assert pl.get("paid_sats") is None
    assert pl.get("pl_sats") is None


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("hash", 1e-12),
        ("kh", 1e-9),
        ("mh", 1e-6),
        ("gh", 1e-3),
        ("th", 1),
        ("ph", 1e3),
        ("eh", 1e6),
    ],
)
def test_declared_mrr_hashrate_units_convert_to_th(unit, expected):
    assert rp._hash_to_th(1, unit) == pytest.approx(expected, rel=1e-12, abs=0)


@pytest.mark.parametrize("unit", [None, "", "watts", "petahashish", 1])
def test_unknown_units_are_unavailable_not_raw_th_or_zero(unit):
    assert rp._hash_to_th(7, unit) is None
    row = rp._normalize_rental(raw_rental(unit=unit))
    assert row["hashrate_advertised_th"] is None
    assert row["hashrate_average_th"] is None
    perf = rp.compute_mrr_perf(raw_rental(unit=unit))
    assert perf["delivered_thh"] is None
    assert perf["cost_sats_per_thh"] is None


@pytest.mark.parametrize("bad", [True, -1, float("nan"), float("inf"), 10**400])
def test_invalid_hashrate_and_money_never_leak_nonfinite_numbers(bad):
    assert rp._hash_to_th(bad, "th") is None
    row = rp._normalize_rental(raw_rental(paid=bad))
    assert row["price_paid_btc"] is None
    perf = rp.compute_mrr_perf(raw_rental(paid=bad))
    assert perf["paid_sats"] is None
    json.dumps({"row": row, "perf": perf}, allow_nan=False)


def test_explicit_non_btc_overrides_legacy_btc_field_in_every_summary(monkeypatch):
    monkeypatch.setattr(rp, "_resolve_network_hashrate_for_rental", lambda *_: 1e20)
    row = rp._normalize_rental(raw_rental("LTC"))
    row["price_paid_btc"] = 1.0  # Contradictory legacy/cache payload must not win.
    history = rp._rental_to_history_row(row)
    assert history["paid_sats"] is None
    assert history["cost_sats_per_thh"] is None
    portfolio = rp.compute_portfolio_summary([row], [], [], [])
    assert portfolio["spend"]["spent_sats"] is None
    assert portfolio["spend"]["avg_cost_sats_per_thh"] is None
    rankings = rp.compute_provider_rankings([row], [], [], [])
    assert rankings[0]["spend_sats"] is None
    assert rankings[0]["avg_pl_pct"] is None


def test_mixed_currency_cost_uses_only_btc_priced_work(monkeypatch):
    monkeypatch.setattr(rp, "_resolve_network_hashrate_for_rental", lambda *_: 1e20)
    btc = rp._normalize_rental(raw_rental("BTC"))
    ltc = rp._normalize_rental(raw_rental("LTC"))
    summary = rp.compute_portfolio_summary([btc, ltc], [], [], [])["spend"]
    assert summary["spent_sats"] == 10000
    assert summary["avg_cost_sats_per_thh"] == pytest.approx(round(10000 / 180, 2))
    assert summary["priced_count"] == 1
    assert summary["unpriced_count"] == 1
    assert summary["price_state"] == "partial"


def test_history_and_analysis_do_not_claim_refund_sats_for_non_btc(monkeypatch):
    monkeypatch.setattr(rp, "_resolve_network_hashrate_for_rental", lambda *_: 1e20)
    monkeypatch.setattr(rp, "_market_price_for_ts", lambda *_: None)
    monkeypatch.setattr(rp, "_rig_local_delivery", lambda *a, **kw: {"pairs": []})
    row = rp._normalize_rental(raw_rental("ETH"))
    row["hashrate_percent"] = 10.0
    result = rp._mrr_analysis_row(row, "fixture-tenant843", 90.0, set(), set())
    assert result["paid_sats"] is None
    assert result["expected_refund_sats"] is None
    assert result["roi_pct"] is None
    assert "None sats" not in result["notes"]


@pytest.mark.parametrize("currency", ["BTC", "LTC", "ETH", "DOGE", "BCH", None])
def test_actual_http_detail_preserves_currency_and_qualifies_all_money(
    monkeypatch, currency
):
    import app as application

    monkeypatch.setattr(
        rp,
        "fetch_mrr_rental_detail",
        lambda *a, **kw: {"success": True, "detail": raw_rental(currency)},
    )
    monkeypatch.setattr(rp, "_resolve_network_hashrate_for_rental", lambda *_: 1e20)
    monkeypatch.setattr(rp, "fetch_market_reference", lambda: {"available": False})
    monkeypatch.setattr(
        rp, "analyze_rig", lambda *a, **kw: {"history": [], "trust": {}, "summary": {}}
    )
    with application.app.test_client() as client:
        response = client.get("/api/rentals/detail?id=fixture843&provider=mrr")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["detail"]["price"]["currency"] == currency
    assert payload["detail"]["price"]["paid"] == "0.0001"
    if currency == "BTC":
        assert payload["perf"]["paid_sats"] == 10000
        assert payload["pl"]["available"] is True
    else:
        assert payload["perf"]["paid_sats"] is None
        assert payload["perf"]["cost_sats_per_thh"] is None
        assert payload["pl"]["available"] is False
        assert payload["pl"].get("paid_sats") is None
        assert payload["pl"].get("pl_sats") is None
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize("algorithm", [None, "", "scrypt", "ethash", "unverified"])
def test_unverified_algorithm_cannot_enter_bitcoin_economics(algorithm):
    raw = raw_rental()
    raw["rig"]["type"] = algorithm
    row = rp._normalize_rental(raw)
    assert row["hashrate_average_th"] is None
    assert row["hashrate_advertised_th"] is None
    assert row["price_paid_btc"] == pytest.approx(0.0001)
    perf = rp.compute_mrr_perf(raw)
    assert perf["delivered_thh"] is None
    assert perf["cost_sats_per_thh"] is None
    assert rp.attach_pl(perf, 10000, network_hashrate_hs=1e20)["available"] is False


@pytest.mark.parametrize("currency", ["LTC", "BTC"])
def test_history_series_keeps_unknown_spend_distinct_from_verified_zero(
    monkeypatch, tmp_path, currency
):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "currency-series.sqlite"))
    monkeypatch.setattr(rp, "_resolve_network_hashrate_for_rental", lambda *_: 1e20)
    raw = raw_rental(currency, paid="0")
    raw["start"] = "2026-10-19 00:00:00 UTC"
    history = rp._rental_to_history_row(rp._normalize_rental(raw))
    assert rp.save_rental_history([history], tenant_id="fixture843") is True
    series = rp.compute_portfolio_series(tenant_id="fixture843")
    expected = 0 if currency == "BTC" else None
    assert series["points"][0]["spent_sats"] == expected
    assert series["totals"]["spent_sats"] == expected
