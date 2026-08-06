"""Tests for services/rental_performance.py — the RENTALS panel fetchers.

All provider HTTP is mocked; credential paths (env + Settings fallback) are
exercised so the fail-closed behavior is pinned.
"""
import time

import pytest

import services.rental_performance as rp


class FakeResponse:
    def __init__(self, ok=True, status_code=200, payload=None):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload if payload is not None else {"success": True, "data": {}}

    def json(self):
        return self._payload


def _mrr_rental(**over):
    base = {
        "id": "5657736",
        "owner": "almansoorii",
        "renter": "cypher",
        "hashrate": {"advertised": {"hash": "0.165", "type": "ph", "nice": "165.00T"},
                     "average": {"hash": "0.15932150061561", "type": "ph", "nice": "159.32T", "percent": "96.56"}},
        "price": {"type": "legacy", "advertised": "0.00000000", "paid": "0.00001404", "currency": "BTC"},
        "length": "3.85", "extended": "0", "extensions": [],
        "start": "2026-07-25 19:17:20 UTC", "end": "2026-07-25 23:08:20 UTC",
        "start_unix": "1785007040", "end_unix": "1785020900", "ended": True,
        "rig": {"id": "376882", "name": "A02 165TH", "type": "sha256ab",
                "status": {"status": "available", "rented": False, "online": True},
                "online": True, "region": "eu-de", "rpi": "100.00"},
    }
    base.update(over)
    return base


@pytest.fixture
def mrr_creds(monkeypatch):
    monkeypatch.setenv("MRR_API_KEY", "k-test")
    monkeypatch.setenv("MRR_API_SECRET", "s-test")
    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)


def test_mrr_rentals_needs_auth(monkeypatch):
    monkeypatch.delenv("MRR_API_KEY", raising=False)
    monkeypatch.delenv("MRR_API_SECRET", raising=False)
    monkeypatch.setattr(rp, "load_settings", lambda: {}, raising=False)
    out = rp.fetch_mrr_rentals()
    assert out["success"] is False
    assert out["needs_auth"] is True
    assert out["rentals"] == []


def test_mrr_rentals_normalizes(mrr_creds, monkeypatch):
    payload = {"success": True, "data": {
        "total": 34, "returned": 1, "start": 0, "limit": 25,
        "rentals": [_mrr_rental()],
    }}
    calls = {}

    def fake_get(url, headers=None, timeout=None, params=None):
        calls["url"] = url
        calls["headers"] = headers
        calls["params"] = params or {}
        return FakeResponse(payload=payload)

    monkeypatch.setattr(rp.requests, "get", fake_get)
    out = rp.fetch_mrr_rentals(rtype="renter", history=True)
    assert out["success"] is True
    assert out["total"] == 34
    r = out["rentals"][0]
    assert r["id"] == "5657736"
    # Unit normalization: MRR reports hash in PH (0.165 PH = 165 TH) — the
    # panel must show TH/s, not treat the raw number as TH (1000x bug guard).
    assert r["hashrate_advertised_th"] == 165.0
    assert r["hashrate_average_th"] == 159.32150061561
    assert r["hashrate_percent"] == 96.56
    assert r["price_paid_btc"] == 0.00001404
    assert r["ended"] is True
    assert r["rig"]["region"] == "eu-de"
    # MRR signs the PATH WITHOUT query params; filters go as request params.
    assert calls["url"].endswith("/rental")
    assert calls["params"]["type"] == "renter"
    assert calls["params"]["history"] == "true"
    assert calls["headers"]["x-api-key"] == "k-test"
    assert "x-api-nonce" in calls["headers"] and "x-api-sign" in calls["headers"]
    assert "?type=renter&history=true&limit=25" not in calls["url"]


def test_mrr_rentals_http_error(mrr_creds, monkeypatch):
    monkeypatch.setattr(rp.requests, "get", lambda *a, **k: FakeResponse(ok=False, status_code=503))
    out = rp.fetch_mrr_rentals()
    assert out["success"] is False
    assert "503" in out.get("error", "")


def test_mrr_rentals_permission_error(mrr_creds, monkeypatch):
    payload = {"success": False, "data": {"permission": "balance", "message": "No Permission - account/1285"}}
    monkeypatch.setattr(rp.requests, "get", lambda *a, **k: FakeResponse(payload=payload))
    out = rp.fetch_mrr_rentals()
    assert out["success"] is False
    assert "No Permission" in out.get("error", "")


def test_mrr_rental_detail_graph_log(mrr_creds, monkeypatch):
    detail = {"success": True, "data": _mrr_rental()}
    graph = {"success": True, "data": {"rentalid": "5657736", "chartdata": {
        "time_start": "2026-07-25 15:17:20", "time_end": "2026-07-25 19:08:20",
        "bars": "[1785007080000,0],[1785007140000,36865135957333]"}}}
    log = {"success": True, "data": {"rental_log": [{"id": "43923043", "time": "t", "msg": "Rental #5657736 has finished."}]}}

    def fake_get(url, headers=None, timeout=None):
        if "/graph" in url:
            return FakeResponse(payload=graph)
        if "/log" in url:
            return FakeResponse(payload=log)
        return FakeResponse(payload=detail)

    monkeypatch.setattr(rp.requests, "get", fake_get)
    out = rp.fetch_mrr_rental_detail("5657736")
    assert out["success"] is True
    assert out["detail"]["id"] == "5657736"
    assert "1785007140000" in out["graph"]["chartdata"]["bars"]
    assert out["log"]["rental_log"][0]["msg"].startswith("Rental #")


def test_braiins_contracts_needs_auth(monkeypatch):
    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
    out = rp.fetch_braiins_contracts()
    assert out["success"] is False
    assert out["needs_auth"] is True
    assert "BRAIINS_API_KEY" in out.get("error", "")


def test_braiins_key_falls_back_to_settings(monkeypatch):
    """BRAIINS_API_KEY resolves from the Settings DB when the env var is unset
    (same env → Settings fallback as MRR)."""
    import services.settings as _settings_mod
    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
    monkeypatch.setattr(_settings_mod, "load_settings",
                        lambda: {"braiins_api_key": "owner-token-db"})
    assert rp._braiins_key() == "owner-token-db"


def test_braiins_key_env_wins_over_settings(monkeypatch):
    import services.settings as _settings_mod
    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token-env")
    monkeypatch.setattr(_settings_mod, "load_settings",
                        lambda: {"braiins_api_key": "owner-token-db"})
    assert rp._braiins_key() == "owner-token-env"


def test_braiins_contracts_with_key(monkeypatch):
    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token")
    contract = {"id": "c-1", "status": "RUNNING", "speed_limit_ph": 121.7,
                "amount_sat": 50000000, "price_sat": 50013000}
    payload = {"items": [contract]}
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return FakeResponse(payload=payload)

    monkeypatch.setattr(rp.requests, "get", fake_get)
    out = rp.fetch_braiins_contracts()
    assert out["success"] is True
    assert out["contracts"][0]["id"] == "c-1"
    assert out["contracts"][0]["status"] == "RUNNING"
    # Braiins auth uses the `apikey` header.
    assert seen["headers"]["apikey"] == "owner-token"


def test_braiins_contract_speed_needs_auth(monkeypatch):
    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
    out = rp.fetch_braiins_contract_speed("c-1")
    assert out["success"] is False
    assert out["needs_auth"] is True


def test_num_helper():
    assert rp._num(None) is None
    assert rp._num("") is None
    assert rp._num("3.85") == 3.85
    assert rp._num("nope") is None


def test_hash_to_th_units():
    """MRR hash values carry a unit (ph/mh/gh/th) — normalize to TH/s."""
    assert rp._hash_to_th("0.165", "ph") == 165.0      # 0.165 PH = 165 TH
    assert rp._hash_to_th("159.32", "th") == 159.32   # already TH
    assert rp._hash_to_th("500", "gh") == 0.5         # 500 GH = 0.5 TH
    assert rp._hash_to_th("1", "mh") == 1e-6          # 1 MH = 1e-6 TH
    assert rp._hash_to_th("7", "") == 7.0             # unknown unit → raw
    assert rp._hash_to_th(None, "ph") is None
    assert rp._hash_to_th("nope", "ph") is None
