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
    # The same contract id comes back from every endpoint probe — the
    # dedup must collapse it to a single entry.
    assert len(out["contracts"]) == 1
    assert out["contracts"][0]["id"] == "c-1"
    assert out["contracts"][0]["status"] == "RUNNING"
    # Braiins auth uses the `apikey` header.
    assert seen["headers"]["apikey"] == "owner-token"


def test_braiins_contracts_rejected_key_reports_error(monkeypatch):
    """A CONFIGURED key rejected by the API (401/403) must NOT be reported
    as an empty account — the panel needs to tell the user the key is bad.
    This was the silent-failure bug: `if not r.ok: continue` swallowed the
    auth rejection and returned success=True with zero contracts."""
    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token")

    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(ok=False, status_code=401)

    monkeypatch.setattr(rp.requests, "get", fake_get)
    out = rp.fetch_braiins_contracts()
    assert out["success"] is False
    assert out["needs_auth"] is True
    assert "rejected" in out.get("error", "").lower()
    assert out["contracts"] == []


def test_braiins_contracts_spot_bid_fallback(monkeypatch):
    """Legacy /contract endpoints may 404 while the current spot API
    (/spot/bid/current, /spot/bid) still returns the caller's orders — the
    probe must fall back and parse the spot envelope + bid_status names."""
    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token")
    bid = {"bid_id": "B123", "bid_status": "SPOT_BID_STATUS_ACTIVE",
           "speed_limit_ph": 100.0, "amount_sat": 20000000, "price_sat": 90000000,
           "created_ts": "2026-07-01T00:00:00Z"}

    def fake_get(url, headers=None, timeout=None):
        if "/contract" in url:
            return FakeResponse(ok=False, status_code=404)
        return FakeResponse(payload={"items": [bid]})

    monkeypatch.setattr(rp.requests, "get", fake_get)
    out = rp.fetch_braiins_contracts()
    assert out["success"] is True
    assert len(out["contracts"]) == 1
    c = out["contracts"][0]
    assert c["id"] == "B123"
    assert "ACTIVE" in c["status"]  # SPOT_BID_STATUS_ACTIVE → ACTIVE
    assert c["speed_limit_ph"] == 100.0
    assert c["amount_sat"] == 20000000


def test_braiins_contract_speed_spot_fallback(monkeypatch):
    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token")

    def fake_get(url, headers=None, timeout=None):
        if "/contract/" in url and "/speed" in url:
            return FakeResponse(ok=False, status_code=404)
        return FakeResponse(payload={"items": [
            {"timestamp": 1785007000, "speed_ph": 100.0},
            {"timestamp": 1785007300, "speed_ph": 110.0},
        ]})

    monkeypatch.setattr(rp.requests, "get", fake_get)
    out = rp.fetch_braiins_contract_speed("B123")
    assert out["success"] is True
    assert len(out["points"]) == 2
    assert out["points"][0]["speed_ph"] == 100.0


def test_braiins_contract_detail_normalizes_with_metrics(monkeypatch):
    """Braiins detail is normalized to the MRR schema and carries pre-computed
    analytics (percent, avg TH, delivered TH.h, cost sats/TH/h) so the
    frontend perf banner renders for Braiins contracts too."""
    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token")
    contract = {"id": "c-1", "status": "RUNNING", "speed_limit_ph": 100.0,
                "amount_sat": 50000000, "price_sat": 50013000}

    def fake_get(url, headers=None, timeout=None):
        if "speed" in url:
            return FakeResponse(payload={"items": [
                {"timestamp": 1000, "speed_ph": 100.0},
                {"timestamp": 4600, "speed_ph": 100.0},
            ]})
        return FakeResponse(payload={"items": [contract]})

    monkeypatch.setattr(rp.requests, "get", fake_get)
    out = rp.fetch_braiins_contract_detail("c-1")
    assert out["success"] is True
    d = out["detail"]
    assert d["id"] == "c-1"
    assert d["hashrate"]["advertised"]["type"] == "ph"
    assert d["hashrate"]["average"]["percent"] == 100.0
    # 100 PH/s avg x 1 hour = 100 TH.h
    assert d["perf"]["avg_th"] == 100000.0
    assert d["perf"]["delivered_thh"] == 100000.0
    # 0.5 BTC = 50_000_000 sats / 100_000 TH.h = 500 sats/TH/h
    assert abs(d["perf"]["cost_sats_per_thh"] - 500.0) < 1e-6
    assert d["price"]["paid"] == 0.5
    assert out["graph"]["points"]


def test_braiins_contract_speed_needs_auth(monkeypatch):
    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
    out = rp.fetch_braiins_contract_speed("c-1")
    assert out["success"] is False
    assert out["needs_auth"] is True


def test_braiins_contract_detail_accepts_passed_contract(monkeypatch):
    """When the caller already has the contract dict (frontend list payload),
    the detail must NOT re-probe the list endpoints — only the speed series
    is fetched. Guards the per-click HTTP cost."""
    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token")
    contract = {"id": "B1", "status": "ACTIVE", "speed_limit_ph": 50.0,
                "amount_sat": 10000000, "price_sat": 30000000}
    urls = []

    def fake_get(url, headers=None, timeout=None):
        urls.append(url)
        return FakeResponse(payload={"items": [
            {"timestamp": 0, "speed_ph": 50.0},
            {"timestamp": 3600, "speed_ph": 50.0},
        ]})

    monkeypatch.setattr(rp.requests, "get", fake_get)
    out = rp.fetch_braiins_contract_detail("B1", contract=contract)
    assert out["success"] is True
    # Only the speed endpoints were hit (list probe endpoints must NOT appear).
    assert len(urls) == 1
    assert "/speed" in urls[0]
    assert "/contract/active" not in urls
    assert out["detail"]["perf"]["avg_th"] == 50000.0


# ── Analytics: market reference + MRR perf + rig track record ──────────────


def _mkt_offer(provider, btc_per_th_day, estimated=False):
    from services.hashrate_market import NormalizedOffer
    return NormalizedOffer(
        provider=provider,
        hashrate=100.0,
        price_per_th_day=btc_per_th_day,
        duration_days=1.0,
        fee_pct=0.0,
        algorithm="sha256",
        source=provider,
        estimated=estimated,
    )


def test_market_reference_picks_cheapest_live(monkeypatch):
    """fetch_market_reference picks the cheapest NON-estimated live quote and
    converts BTC/TH/day → sats/TH/h (price * 1e8 / 24h)."""
    offers = [
        _mkt_offer("braiins", 0.000150),
        _mkt_offer("mrr", 0.000120),      # cheapest live → wins
        _mkt_offer("nicehash", 0.000010, estimated=True),  # estimated → ignored
    ]
    monkeypatch.setattr(rp, "_fetch_market_offers", lambda: offers)
    out = rp.fetch_market_reference()
    assert out["available"] is True
    assert out["provider"] == "mrr"
    # 0.00012 BTC/TH/day → sats/TH/h: 0.00012 * 1e8 / 24 = 500
    assert abs(out["price_sats_per_thh"] - 500.0) < 1e-6


def test_market_reference_unavailable_when_no_offers(monkeypatch):
    monkeypatch.setattr(rp, "_fetch_market_offers", lambda: [])
    out = rp.fetch_market_reference()
    assert out["available"] is False


def test_market_reference_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("provider down")
    monkeypatch.setattr(rp, "_fetch_market_offers", boom)
    assert rp.fetch_market_reference() == {"available": False}


def test_compute_mrr_perf_from_raw_detail():
    """compute_mrr_perf derives the same perf block Braiins carries from a
    RAW MRR detail payload (percent, avg TH, delivered TH·h, cost)."""
    raw = _mrr_rental()  # 0.165 PH adv / 159.32 TH avg · paid 0.00001404 BTC · 3.85h
    perf = rp.compute_mrr_perf(raw)
    assert perf["percent"] == 96.56
    assert perf["limit_th"] == 165.0
    assert abs(perf["avg_th"] - 159.32150061561) < 1e-9
    # 159.3215 TH x 3.85 h = 613.39 TH·h
    assert abs(perf["delivered_thh"] - (159.32150061561 * 3.85)) < 1e-6
    # 0.00001404 BTC = 1404 sats / 613.39 TH·h = 2.29 sats/TH/h
    expected_cost = 1404.0 / (159.32150061561 * 3.85)
    assert abs(perf["cost_sats_per_thh"] - expected_cost) < 1e-6


def test_compute_mrr_perf_missing_fields():
    perf = rp.compute_mrr_perf({"id": "x"})
    assert perf["percent"] is None
    assert perf["avg_th"] is None
    assert perf["cost_sats_per_thh"] is None


def test_rig_performance_history_matches_by_rig(monkeypatch):
    """fetch_rig_performance_history returns only rentals of the SAME rig
    (by rig id, name fallback), excludes the current rental, and sorts
    newest first."""
    # The listing returns NORMALIZED rentals (fetch_mrr_rentals output) —
    # normalize the raw fixtures the same way the real fetcher does.
    raw = [
        _mrr_rental(id="1", rig={"id": "376882", "name": "A02 165TH"}),          # same rig id
        _mrr_rental(id="2", rig={"id": "376882", "name": "A02 165TH"}),          # same rig id
        _mrr_rental(id="3", rig={"id": "999", "name": "Other rig"}),            # different rig
        _mrr_rental(id="4", rig={"id": None, "name": "a02 165th"}),              # name-only match
    ]
    # Set distinct starts so the newest-first sort is observable.
    raw[0]["start"] = "2026-07-20 10:00:00 UTC"
    raw[1]["start"] = "2026-07-25 10:00:00 UTC"
    raw[3]["start"] = "2026-07-15 10:00:00 UTC"
    rentals = [rp._normalize_rental(r) for r in raw]

    def fake_listing(**kw):
        return {"success": True, "needs_auth": False, "rentals": rentals, "total": len(rentals)}

    monkeypatch.setattr(rp, "fetch_mrr_rentals", fake_listing)
    # The real caller (detail route) passes BOTH id and name from the rig.
    out = rp.fetch_rig_performance_history(rig_id="376882", rig_name="A02 165TH",
                                           exclude_rental_id="1")
    ids = [r["id"] for r in out]
    # #1 excluded (current), #2 same id, #4 name match; #3 different rig out.
    assert ids == ["2", "4"]
    assert out[0]["percent"] == 96.56


def test_rig_performance_history_requires_rig():
    assert rp.fetch_rig_performance_history() == []
    assert rp.fetch_rig_performance_history(rig_id=None, rig_name="") == []


# ── Route wiring: /api/rentals/detail enriches both providers ──────────────

import app as _app_module


@pytest.fixture
def rclient():
    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as c:
        yield c


def test_detail_route_mrr_enriched(rclient, monkeypatch):
    """GET /api/rentals/detail?provider=mrr returns perf + rig_history + market
    computed from the RAW MRR detail (server-side analytics)."""
    raw = _mrr_rental()
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_mrr_rental_detail",
        lambda rid, tenant_id="": {"success": True, "detail": raw, "graph": {"chartdata": {"bars": "[1,2]"}}, "log": {"rental_log": []}})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_rig_performance_history",
        lambda *a, **k: [{"id": "2", "start": "2026-07-01", "percent": 94.0}])
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_market_reference",
        lambda: {"available": True, "price_sats_per_thh": 500.0, "provider": "mrr"})

    resp = rclient.get("/api/rentals/detail?provider=mrr&id=5657736")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["provider"] == "mrr"
    assert data["detail"]["id"] == "5657736"
    # Perf derived from raw MRR detail (96.56% / 165 TH adv).
    assert data["perf"]["percent"] == 96.56
    assert data["perf"]["limit_th"] == 165.0
    assert data["rig_history"][0]["percent"] == 94.0
    assert data["market"]["price_sats_per_thh"] == 500.0


def test_detail_route_braiins_market(rclient, monkeypatch):
    """POST /api/rentals/detail (braiins) carries market + empty rig_history."""
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_braiins_contract_detail",
        lambda cid, contract=None, tenant_id="": {"success": True, "detail": {"id": cid, "perf": {"percent": 95.0}},
                                                    "graph": {"points": []}})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_market_reference",
        lambda: {"available": True, "price_sats_per_thh": 480.0, "provider": "braiins"})

    resp = rclient.post("/api/rentals/detail", json={"provider": "braiins", "id": "B1", "contract": {"id": "B1"}})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["detail"]["perf"]["percent"] == 95.0
    assert data["market"]["provider"] == "braiins"
    assert data["rig_history"] == []


def test_num_helper():
    assert rp._num(None) is None
    assert rp._num("") is None
    assert rp._num("3.85") == 3.85
    assert rp._num("nope") is None


def test_braiins_key_strips_whitespace(monkeypatch):
    """A pasted token with trailing newline/space must be stripped before it
    becomes the `apikey` header (verbatim) — otherwise Braiins 401s and the
    panel reports "key rejected" for a valid key."""
    import services.settings as _settings_mod
    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
    monkeypatch.setattr(_settings_mod, "load_settings",
                        lambda: {"braiins_api_key": "owner-token\n  "})
    from agents.solo_mining_advisor.tools import braiins_credentials
    assert braiins_credentials()["api_key"] == "owner-token"
    assert rp._braiins_key() == "owner-token"


def test_braiins_credentials_strips_env(monkeypatch):
    """Env-var credentials are stripped too (Render env values can carry
    trailing whitespace from the dashboard UI)."""
    monkeypatch.setenv("BRAIINS_API_KEY", "env-token \t")
    from agents.solo_mining_advisor.tools import braiins_credentials
    assert braiins_credentials()["api_key"] == "env-token"


# ── Settings route: env_overrides + test-braiins verdict ────────────────────

import agents.solo_mining_advisor.tools as _tools


def test_settings_get_exposes_env_overrides(rclient, monkeypatch):
    """GET /api/settings reports which credentials are env-overridden so the UI
    can warn that the Settings field won't take effect on the server."""
    monkeypatch.setenv("BRAIINS_API_KEY", "env-key")
    monkeypatch.delenv("MRR_API_KEY", raising=False)
    monkeypatch.delenv("MRR_API_SECRET", raising=False)
    resp = rclient.get("/api/settings")
    assert resp.status_code == 200
    overrides = resp.get_json()["env_overrides"]
    assert overrides["braiins_api_key"] is True
    assert overrides["mrr_api_key"] is False
    assert overrides["mrr_api_secret"] is False


def test_settings_test_braiins_not_configured(rclient, monkeypatch):
    """No key anywhere → clear 'not configured' verdict (not a 401)."""
    monkeypatch.setattr(_tools, "braiins_credentials",
                        lambda tenant_id="": {"api_key": ""})
    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
    resp = rclient.post("/api/settings/test-braiins")
    data = resp.get_json()
    assert data["success"] is False
    assert data["configured"] is False
    assert "not configured" in data["error"]


def test_settings_test_braiins_rejected(rclient, monkeypatch):
    """Configured key that the API refuses → verdict 'rejected' with reason."""
    monkeypatch.setattr(_tools, "braiins_credentials",
                        lambda tenant_id="": {"api_key": "owner-token"})
    monkeypatch.setattr(
        rp, "fetch_braiins_contracts",
        lambda tenant_id="": {"success": False, "needs_auth": True, "contracts": [],
                              "error": "Braiins API rejected the key (HTTP 401/403)"})
    resp = rclient.post("/api/settings/test-braiins")
    data = resp.get_json()
    assert data["success"] is False
    assert data["configured"] is True
    assert data["verdict"] == "rejected"
    assert "401" in data["error"]


def test_settings_test_braiins_ok(rclient, monkeypatch):
    """Valid key → verdict 'ok' with the contract count."""
    monkeypatch.setattr(_tools, "braiins_credentials",
                        lambda tenant_id="": {"api_key": "owner-token"})
    monkeypatch.setattr(
        rp, "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False,
                              "contracts": [{"id": "B1"}, {"id": "B2"}]})
    resp = rclient.post("/api/settings/test-braiins")
    data = resp.get_json()
    assert data["success"] is True
    assert data["verdict"] == "ok"
    assert data["contracts"] == 2


def test_hash_to_th_units():
    """MRR hash values carry a unit (ph/mh/gh/th) — normalize to TH/s."""
    assert rp._hash_to_th("0.165", "ph") == 165.0      # 0.165 PH = 165 TH
    assert rp._hash_to_th("159.32", "th") == 159.32   # already TH
    assert rp._hash_to_th("500", "gh") == 0.5         # 500 GH = 0.5 TH
    assert rp._hash_to_th("1", "mh") == 1e-6          # 1 MH = 1e-6 TH
    assert rp._hash_to_th("7", "") == 7.0             # unknown unit → raw
    assert rp._hash_to_th(None, "ph") is None
    assert rp._hash_to_th("nope", "ph") is None
