"""Tests for the Rentals ANALYSIS CSV export (Controle de Rendimento).

Covers the capital-protection rules:
  - cancelled_by_performance: delivery % < configurable minimum (default 90).
  - Refund entitlement (MRR policy): <80% delivery → FULL refund (paid_sats);
    80%..min → proportional refund paid_sats * (1 - delivery/100).
  - spread vs the market price AT PURCHASE (historical market lookup, live
    fallback); real loss = paid - delivered fair value; effective cost.
  - Seller intelligence: reliability score → should_blacklist / auto_action
    (ok / monitor / request_refund / blacklist).
  - Dates parsing to 1970-01-01 are invalid → flagged, never used in lookups.
  - Braiins contracts → partial rows + honest note (no seller/delivery data).
  - CSV rendering: full column set, BOM handled by the caller.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import rental_performance as rp  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Per-test scratch DB (get_db reads DB_PATH at call time)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite"))


@pytest.fixture(autouse=True)
def _no_network(db, monkeypatch):
    """Hermetic: no provider fetches — market price comes from a mocked
    lookup, P/L from a mocked network hashrate resolver."""
    monkeypatch.setattr(rp, "_historical_market_sats_per_thh",
                        lambda ts: None)
    monkeypatch.setattr(rp, "fetch_market_reference",
                        lambda: {"available": False})
    monkeypatch.setattr(rp, "_resolve_network_hashrate_for_rental",
                        lambda *a, **k: None)


def _rental(**kw):
    """An MRR rental row (renter bucket) with sane defaults."""
    base = {
        "id": "R-1",
        "start": "2026-07-01 12:00:00 UTC",
        "end": "2026-07-02 12:00:00 UTC",
        "ended": True,
        "length_hours": 24.0,
        "hashrate_advertised_th": 100.0,
        "hashrate_average_th": 100.0,
        "hashrate_percent": 100.0,
        "price_paid_btc": 0.0001,  # 10000 sats
        "rig": {"id": "rig-a", "name": "NiceRig 100"},
    }
    base.update(kw)
    return base


def _build(rows, min_delivery_pct=90.0, tenant_id=""):
    return rp.build_rentals_analysis_rows(
        [], rows, [], tenant_id=tenant_id,
        min_delivery_pct=min_delivery_pct)


# ── Refund rules ───────────────────────────────────────────────────────────

def test_refund_full_below_80(db):
    """delivery < 80% → FULL refund (paid_sats)."""
    rows = _build([_rental(hashrate_percent=70.0)])
    r = rows[0]
    assert r["status"] == "cancelled_performance"
    assert r["cancelled_by_performance"] == "1"
    assert r["performance_ok"] == ""
    assert r["expected_refund_sats"] == 10000  # full paid
    assert r["refund_pending_sats"] == 10000   # due (MRR doesn't expose received)
    assert "reembolso" in r["notes"]


def test_refund_proportional_between_80_and_min(db):
    """80% ≤ delivery < min → proportional: paid * (1 - delivery/100)."""
    rows = _build([_rental(hashrate_percent=85.0)])
    r = rows[0]
    assert r["cancelled_by_performance"] == "1"
    # 10000 * (1 - 0.85) = 1500
    assert r["expected_refund_sats"] == 1500
    assert r["refund_pending_sats"] == 1500


def test_no_refund_at_or_above_min(db):
    """delivery ≥ min → performance ok, no refund, action ok."""
    rows = _build([_rental(hashrate_percent=96.0)])
    r = rows[0]
    assert r["performance_ok"] == "1"
    assert r["cancelled_by_performance"] == ""
    assert r["expected_refund_sats"] == 0
    assert r["auto_action"] == "ok"


def test_min_delivery_configurable(db):
    """Lower the acceptable minimum → 85% delivery becomes OK."""
    rows = _build([_rental(hashrate_percent=85.0)], min_delivery_pct=80.0)
    r = rows[0]
    assert r["min_acceptable_delivery"] == 80.0
    assert r["performance_ok"] == "1"
    assert r["cancelled_by_performance"] == ""
    assert r["expected_refund_sats"] == 0


def test_min_delivery_clamped_out_of_range(db):
    """Out-of-range min is clamped to 90."""
    rows = _build([_rental(hashrate_percent=96.0)], min_delivery_pct=200.0)
    assert rows[0]["min_acceptable_delivery"] == 90.0


# ── Invalid dates (1970) ───────────────────────────────────────────────────

def test_epoch_date_flagged_invalid(db):
    """1970-01-01 dates are invalid → flagged, never used for market lookup."""
    rows = _build([_rental(start="1970-01-01 00:00:01 UTC",
                           end="1970-01-01 01:00:00 UTC")])
    r = rows[0]
    assert "data inválida" in r["notes"]
    assert r["market_sats_per_thh"] is None
    # Incomplete data can't be judged → monitor (not an invented ok/refund).
    assert r["auto_action"] == "monitor"


def test_unparseable_date_flagged_invalid(db):
    """A present-but-unparseable date is invalid data, not silently ignored."""
    rows = _build([_rental(start="not-a-date",
                           end="2026-07-02 12:00:00 UTC")])
    r = rows[0]
    assert "data inválida" in r["notes"]
    assert r["market_sats_per_thh"] is None


# ── Spread / loss / effective cost with market price at purchase ──────────

def test_market_price_at_purchase_drives_spread_and_loss(db, monkeypatch):
    """With a market price at purchase time, spread + real loss compute."""
    monkeypatch.setattr(rp, "_historical_market_sats_per_thh",
                        lambda ts: 4.0)  # sats/TH·h at purchase
    # paid 10000 sats for 100 TH × 24h = 2400 TH·h advertised
    rows = _build([_rental(hashrate_percent=100.0)])
    r = rows[0]
    assert r["market_sats_per_thh"] == 4.0
    # cost = 10000 / 2400 ≈ 4.17 sats/TH·h
    assert r["cost_sats_per_thh"] == pytest.approx(4.17, abs=0.01)
    # fair value = 4 × 2400 = 9600 → spread = 10000 - 9600 = 400 (slightly overpaid)
    assert r["spread_sats"] == pytest.approx(400.0, abs=0.01)
    # loss = paid - delivered value (100% delivery → 9600) = 400
    assert r["loss_sats"] == pytest.approx(400.0, abs=0.01)
    # no refund due (100% delivery) → after-refund equals pre-refund
    assert r["loss_after_refund_sats"] == pytest.approx(400.0, abs=0.01)
    assert r["spread_pct"] == pytest.approx(4.2, abs=0.01)  # 1 casa decimal


def test_no_market_price_keeps_honest_empty(db):
    """No market price → spread/loss stay None with an honest note."""
    rows = _build([_rental(hashrate_percent=96.0)])
    r = rows[0]
    assert r["market_sats_per_thh"] is None
    assert r["spread_sats"] is None
    assert r["loss_sats"] is None
    assert r["loss_after_refund_sats"] is None
    assert "sem preço de mercado" in r["notes"]


def test_loss_after_refund_nets_due_refund(db, monkeypatch):
    """Real (net) loss subtracts the DUE refund — the pre-refund figure
    overstates damage for exactly the rentals the CSV flags."""
    monkeypatch.setattr(rp, "_historical_market_sats_per_thh",
                        lambda ts: 4.0)
    # 70% delivery (avg matches), paid 10000 sats, 100 TH advertised × 24h.
    rows = _build([_rental(hashrate_percent=70.0, hashrate_average_th=70.0)])
    r = rows[0]
    assert r["expected_refund_sats"] == 10000  # full refund due
    # delivered value = 4 × (70 TH × 24h) = 6720 → pre-refund loss = 3280
    assert r["loss_sats"] == pytest.approx(3280.0, abs=0.01)
    # net = 3280 - 10000 = -6720 (nothing actually lost after the refund)
    assert r["loss_after_refund_sats"] == pytest.approx(-6720.0, abs=0.01)
    assert "loss_after_refund" in r["notes"]


# ── Seller intelligence → blacklist suggestion ─────────────────────────────

def test_low_reliability_suggests_blacklist(db):
    """A rig with a bad local track record → should_blacklist + action."""
    _seed_history(db, [("rig-bad", 55.0), ("rig-bad", 60.0)])
    rows = _build([_rental(id="R-2", rig={"id": "rig-bad", "name": "BadRig"},
                           hashrate_percent=100.0)])
    r = rows[0]
    assert r["seller_reliability_score"] is not None
    assert r["seller_reliability_score"] < 70.0
    assert r["should_blacklist"] == "1"
    assert r["auto_action"] == "blacklist"


def test_already_blacklisted_not_reflagged(db):
    """Blacklisted rig → flagged in the row + action stays refund/ok (no dup)."""
    # Rig already on the manual blacklist.
    assert rp.add_rig_to_blacklist("rig-x") is True
    rows = _build([_rental(id="R-3", rig={"id": "rig-x", "name": "X"},
                           hashrate_percent=70.0)])
    r = rows[0]
    assert r["blacklisted"] == "1"
    assert r["auto_action"] == "request_refund"  # refund wins over re-blacklist
    assert "blacklist" in r["notes"]


def test_request_refund_when_performance_bad_but_reliable(db):
    """Bad delivery + reliable rig → request_refund (not blacklist)."""
    rows = _build([_rental(hashrate_percent=70.0,
                           rig={"id": "rig-new", "name": "NewRig"})])
    r = rows[0]
    assert r["auto_action"] == "request_refund"
    assert r["should_blacklist"] == ""


def test_missing_delivery_is_monitor(db):
    """No delivery % → monitor (can't judge performance)."""
    rows = _build([_rental(hashrate_percent=None)])
    r = rows[0]
    assert r["delivery_pct"] is None
    assert r["auto_action"] == "monitor"
    assert r["performance_ok"] == ""


# ── Braiins contracts ──────────────────────────────────────────────────────

def test_braiins_contract_partial_row(db):
    """Braiins contracts carry no seller/delivery → partial row + honest note."""
    contracts = [{"id": "B-1", "status": "SPOT_BID_STATUS_ACTIVE",
                  "speed_limit_ph": 1.5, "amount_sat": 5000,
                  "started_at": "2026-07-01T00:00:00Z", "ended_at": None}]
    rows = rp.build_rentals_analysis_rows([], [], contracts)
    r = rows[0]
    assert r["provider"] == "braiins"
    assert r["status"] == "ACTIVE"
    assert r["advertised_th"] == 1500.0  # 1.5 PH → TH
    assert r["paid_sats"] == 5000
    assert r["delivery_pct"] is None
    assert r["auto_action"] == "monitor"
    assert "sem entrega medida" in r["notes"]


# ── CSV rendering ──────────────────────────────────────────────────────────

def test_csv_has_all_columns_and_rows(db):
    """The CSV renders the full column set with the analysis values."""
    rows = _build([_rental(hashrate_percent=70.0)])
    csv_text = rp.rentals_analysis_csv(rows)
    lines = csv_text.strip().splitlines()
    header = lines[0]
    for col in rp.RENTAL_ANALYSIS_COLUMNS:
        assert col in header
    body = lines[1]
    assert "cancelled_performance" in body
    assert "10000" in body  # paid + full refund


# ── Route: /api/rentals/export?mode=analysis ──────────────────────────────

import app as _app_module  # noqa: E402


@pytest.fixture
def rclient():
    """Flask test client (mirrors tests/test_rental_performance.py)."""
    _app_module.app.config["TESTING"] = True
    _app_module._RENTALS_CACHE.clear()
    with _app_module.app.test_client() as c:
        yield c
        _app_module._RENTALS_CACHE.clear()


def _mrr_rental(**over):
    """A realistic MRR rental payload (matches test_rental_performance)."""
    base = {
        "id": "5657736",
        "owner": "almansoorii",
        "renter": "cypher",
        "hashrate": {"advertised": {"hash": "0.165", "type": "ph", "nice": "165.00T"},
                     "average": {"hash": "0.15932150061561", "type": "ph",
                                  "nice": "159.32T", "percent": "96.56"}},
        "price": {"type": "legacy", "advertised": "0.00000000",
                   "paid": "0.00001404", "currency": "BTC"},
        "length": "3.85", "extended": "0", "extensions": [],
        "start": "2026-07-25 19:17:20 UTC", "end": "2026-07-25 23:08:20 UTC",
        "start_unix": "1785007040", "end_unix": "1785020900", "ended": True,
        "rig": {"id": "376882", "name": "A02 165TH", "type": "sha256ab",
                "status": {"status": "available", "rented": False, "online": True},
                "online": True, "region": "eu-de", "rpi": "100.00"},
    }
    base.update(over)
    return base


def _stub_providers(monkeypatch):
    """Stub provider fetchers so the route never hits the network."""
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=200, tenant_id="": {
            "success": True, "needs_auth": False,
            "rentals": [rp._normalize_rental(_mrr_rental())]
            if (rtype == "renter" and not history) else [],
            "total": 1})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False,
                              "contracts": []})
    monkeypatch.setattr(
        _app_module._rental_perf, "get_rig_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(
        _app_module._rental_perf, "get_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(
        _app_module._rental_perf, "_historical_market_sats_per_thh",
        lambda ts: None)
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_market_reference",
        lambda: {"available": False})
    monkeypatch.setattr(
        _app_module._rental_perf, "_resolve_network_hashrate_for_rental",
        lambda *a, **k: None)


def test_export_route_analysis_mode(rclient, monkeypatch):
    """?mode=analysis returns the full yield-control CSV (analysis columns)."""
    _stub_providers(monkeypatch)
    resp = rclient.get("/api/rentals/export?mode=analysis")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    body = resp.get_data(as_text=True)
    assert "cancelled_by_performance" in body
    assert "expected_refund_sats" in body
    assert "spread_sats" in body
    assert "loss_sats" in body
    assert "auto_action" in body
    # The 96.56% delivery rental → performance ok (≥ 90 default).
    import csv as _csv
    import io as _io
    row = next(_csv.reader(_io.StringIO(body)))
    # Parse the body row by the header index.
    idx = rp.RENTAL_ANALYSIS_COLUMNS.index("performance_ok")
    rows = list(_csv.reader(_io.StringIO(body)))
    assert rows[1][idx] == "1"
    assert rows[1][rp.RENTAL_ANALYSIS_COLUMNS.index("auto_action")] == "ok"
    assert "rentals_analysis_" in resp.headers["Content-Disposition"]


def test_export_route_simple_still_default(rclient, monkeypatch):
    """No mode param keeps the legacy simple CSV (header provider,id,bucket)."""
    _stub_providers(monkeypatch)
    resp = rclient.get("/api/rentals/export")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "provider,id,bucket" in body
    assert "cancelled_by_performance" not in body


# ── Helpers ────────────────────────────────────────────────────────────────

def _seed_history(db, pairs):
    """Insert local rental_history rows for a rig (delivery % track record)."""
    import datetime as _dt
    rows = []
    for i, (rid, pct) in enumerate(pairs):
        start = _dt.datetime(2026, 6, 1 + i, tzinfo=_dt.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC")
        rows.append({
            "provider": "mrr", "bucket": "renter", "rental_id": f"h-{rid}-{i}",
            "rig_id": rid, "rig_name": "rig-" + rid,
            "start": start, "end": None, "percent": pct,
            "avg_th": 100.0, "advertised_th": 100.0,
            "cost_sats_per_thh": None, "length_hours": 24.0,
            "delivered_thh": 2400.0, "paid_sats": None,
            "network_hashrate_hs": None,
        })
    assert rp.save_rental_history(rows) is True


# ── Pilot audit columns (Issue #119): auto-exclusion no CSV ───────────────

def test_analysis_csv_includes_auto_exclusion(db):
    """Rig auto-excluído → colunas do piloto preenchidas: auto_excluded=1,
    causa (grade + entrega), régua vigente, data — e sem REVOGADA."""
    _seed_history(db, [("rig-a", 57.5), ("rig-a", 55.0)])
    assert rp.add_rig_to_auto_blacklist("rig-a") is True
    r = _build([_rental()])[0]
    assert r["auto_excluded"] == "1"
    assert "grade F" in r["auto_exclude_cause"]
    assert "entrega" in r["auto_exclude_cause"]
    assert r["auto_exclude_rule"] == "floor F · mín 2"
    assert r["auto_exclude_ts"] != ""
    assert r["auto_exclude_restored"] == ""
    assert "auto-exclusão do piloto" in r["notes"]


def test_analysis_csv_marks_restored(db):
    """Restore do rig → auto_excluded some, auto_exclude_restored=1 e o
    note carrega (REVOGADA) — o veredito reflete a decisão revogada."""
    _seed_history(db, [("rig-a", 57.5), ("rig-a", 55.0)])
    assert rp.add_rig_to_auto_blacklist("rig-a") is True
    assert rp.remove_rig_from_blacklist("rig-a") is True
    r = _build([_rental()])[0]
    assert r["auto_excluded"] == ""
    assert r["auto_exclude_restored"] == "1"
    assert r["auto_exclude_cause"] != ""
    assert r["auto_exclude_rule"] == "floor F · mín 2"
    assert "REVOGADA" in r["notes"]


def test_analysis_csv_header_includes_pilot_columns(db):
    """O header do CSV carrega as 5 colunas do piloto para o operador
    auditar exclusões em planilha."""
    rows = _build([_rental()])
    header = rp.rentals_analysis_csv(rows).splitlines()[0]
    for col in ("auto_excluded", "auto_exclude_cause", "auto_exclude_rule",
                "auto_exclude_ts", "auto_exclude_restored"):
        assert col in header
