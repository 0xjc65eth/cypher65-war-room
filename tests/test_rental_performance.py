"""Tests for services/rental_performance.py — the RENTALS panel fetchers.

All provider HTTP is mocked; credential paths (env + Settings fallback) are
exercised so the fail-closed behavior is pinned.
"""
import time

import pytest

import services.rental_performance as rp


class FakeResponse:
    def __init__(self, ok=True, status_code=200, payload=None, text=""):
        self.ok = ok
        self.status_code = status_code
        self.text = text
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


def test_rig_performance_history_matches_by_rig(tmp_path, monkeypatch):
    """fetch_rig_performance_history returns only rentals of the SAME rig
    (by rig id, name fallback), excludes the current rental, and sorts
    newest first."""
    # Hermetic: the remote path PERSISTS rows — isolate the DB so this test
    # never pollutes the shared scratch DB (latent order-dependency for any
    # other test reading local history for the same rig). Pin the REMOTE
    # path too (local-first default would consult this isolated DB, empty).
    monkeypatch.setenv("DB_PATH", str(tmp_path / "rig_hist.sqlite"))
    monkeypatch.setenv("RENTAL_HISTORY_LOCAL_FIRST", "0")
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


# ── CFO analytics: expected yield, P/L, stability, portfolio, local history ─


def test_compute_expected_yield_sats_per_thh():
    """Yield model pinned: at 100 EH/s network and 3.125 BTC reward, 1 TH/s
    produces 450 sats/day → 18.75 sats/TH·h (gross, before pool fee)."""
    net = 100e18  # 100 EH/s in H/s
    y = rp.compute_expected_yield_sats_per_thh(net)
    assert y is not None
    assert abs(y - 18.75) < 1e-9
    # Same formula as app.py profitability: share × 144 blocks × reward / 24.
    assert abs(y * 24 - 450.0) < 1e-6


def test_compute_expected_yield_unknown_network(monkeypatch):
    """Cold box (no network hashrate) → None, never a fabricated number."""
    monkeypatch.setattr(rp, "_network_hashrate_hs", lambda: 0.0)
    assert rp.compute_expected_yield_sats_per_thh() is None
    assert rp.compute_expected_yield_sats_per_thh(0) is None
    assert rp.compute_expected_yield_sats_per_thh("nope") is None


def test_compute_rental_pl_profit_and_loss():
    """P/L = expected gross yield vs paid — loss when cost > yield, profit
    when yield > cost (cheap fill or luck-favorable window)."""
    net = 100e18  # → 18.75 sats/TH·h
    # 100 TH·h delivered, paid 5000 sats → yield 1875 → loss −3125 (−62.5%)
    loss = rp.compute_rental_pl(100.0, 5000, network_hashrate_hs=net)
    assert loss["pl_sats"] == -3125.0
    assert loss["pl_pct"] == -62.5
    assert loss["break_even_sats_per_thh"] == 18.75
    # Paid 1000 sats → yield 1875 → profit +875 (+87.5%)
    win = rp.compute_rental_pl(100.0, 1000, network_hashrate_hs=net)
    assert win["pl_sats"] == 875.0
    assert win["pl_pct"] == 87.5


def test_compute_rental_pl_missing_inputs():
    pl = rp.compute_rental_pl(None, 5000, network_hashrate_hs=100e18)
    assert pl["pl_sats"] is None and pl["yield_sats"] is None
    pl2 = rp.compute_rental_pl(100.0, None, network_hashrate_hs=100e18)
    assert pl2["pl_sats"] is None


def test_compute_speed_stability_grades():
    stable = rp.compute_speed_stability([{"speed_ph": 100}, {"speed_ph": 100}, {"speed_ph": 104}])
    assert stable["grade"] == "STABLE" and stable["cv_pct"] < 5
    variable = rp.compute_speed_stability([{"speed_ph": 80}, {"speed_ph": 150}, {"speed_ph": 70}])
    assert variable["grade"] == "VARIABLE" and variable["cv_pct"] > 15
    # Fewer than 2 points → NO DATA
    nodata = rp.compute_speed_stability([{"speed_ph": 100}])
    assert nodata["cv_pct"] is None and nodata["grade"] is None


def test_attach_pl_from_perf():
    perf = {"delivered_thh": 100.0}
    pl = rp.attach_pl(perf, 5000, network_hashrate_hs=100e18)
    assert pl["available"] is True and pl["pl_sats"] == -3125.0
    assert rp.attach_pl({}, 5000) == {"available": False}


def test_portfolio_summary_aggregates():
    # The route passes NORMALIZED buckets (fetch_mrr_rentals output).
    active = [rp._normalize_rental(_mrr_rental())]       # paid 0.00001404 BTC · avg 159.32 TH · 3.85h
    history = [rp._normalize_rental(_mrr_rental(id="2"))]
    pf = rp.compute_portfolio_summary(active, history, [], [])
    assert pf["counts"]["active"] == 1 and pf["counts"]["history"] == 1
    spend = pf["spend"]
    assert spend["count"] == 2
    assert spend["spent_sats"] == 2808  # 2 × 1404 sats
    assert spend["avg_delivery_pct"] == 96.6  # rounded to 1 decimal
    assert spend["delivered_thh"] is not None
    assert spend["avg_cost_sats_per_thh"] is not None
    assert pf["split"]["mrr"] == 2 and pf["split"]["braiins"] == 0


def test_rental_history_local_roundtrip(tmp_path, monkeypatch):
    """save_rental_history → get_local_rig_history reads it back, and the
    LOCAL-FIRST path serves the track record WITHOUT calling the MRR API."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "hist.sqlite"))
    row = rp._rental_to_history_row(rp._normalize_rental(_mrr_rental()), provider="mrr")
    assert rp.save_rental_history([row], tenant_id="t-hist") is True
    local = rp.get_local_rig_history(rig_id="376882", tenant_id="t-hist")
    assert len(local) == 1 and local[0]["id"] == "5657736"
    assert local[0]["percent"] == 96.56
    # Tenant isolation: another tenant sees nothing.
    assert rp.get_local_rig_history(rig_id="376882", tenant_id="t-other") == []
    # Local-first: fetch_rig_performance_history must NOT hit the MRR API.
    def boom(**kw):
        raise AssertionError("must not hit MRR when local history exists")
    monkeypatch.setattr(rp, "fetch_mrr_rentals", boom)
    out = rp.fetch_rig_performance_history(rig_id="376882", rig_name="A02 165TH",
                                           tenant_id="t-hist")
    assert [x["id"] for x in out] == ["5657736"]


def test_fetch_rig_performance_history_remote_fallback(tmp_path, monkeypatch):
    """No local rows → falls back to the MRR history API, persists what it
    finds, and serves the NEXT call from SQLite (no second API hit)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "hist2.sqlite"))
    rentals = [rp._normalize_rental(_mrr_rental())]
    calls = {"n": 0}

    def fake_listing(**kw):
        calls["n"] += 1
        return {"success": True, "needs_auth": False,
                "rentals": rentals, "total": 1}

    monkeypatch.setattr(rp, "fetch_mrr_rentals", fake_listing)
    # First call: fetches + persists the matched rental.
    out = rp.fetch_rig_performance_history(rig_id="376882", rig_name="A02 165TH",
                                           tenant_id="t-fb")
    assert len(out) == 1 and out[0]["id"] == "5657736"
    # Second call is served from SQLite — the API is NOT re-hit.
    out2 = rp.fetch_rig_performance_history(rig_id="376882", rig_name="A02 165TH",
                                            tenant_id="t-fb")
    assert len(out2) == 1 and out2[0]["id"] == "5657736"
    assert calls["n"] == 1


def test_list_route_includes_portfolio_and_ingest(rclient, monkeypatch):
    """GET /api/rentals carries the portfolio block and ingests the fetched
    buckets into local history (track record builds with zero extra calls)."""
    rental = _mrr_rental()
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=50, tenant_id="": {
            "success": True, "needs_auth": False,
            "rentals": [rental] if (rtype == "renter" and history) else [],
            "total": 1})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False, "contracts": []})
    monkeypatch.setattr(
        _app_module._rental_perf, "get_rig_blacklist", lambda tenant_id="": [])
    ingested = {}
    monkeypatch.setattr(
        _app_module._rental_perf, "ingest_rentals",
        lambda *a, **k: ingested.update({"args": a}) or True)
    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["portfolio"]["spend"]["count"] == 1
    assert data["portfolio"]["split"]["mrr"] == 1
    # ingest_rentals was called with the buckets (not swallowed).
    assert ingested.get("args") and len(ingested["args"]) == 4


def test_detail_route_mrr_has_pl(rclient, monkeypatch):
    """GET /api/rentals/detail (mrr) attaches the P/L block computed from the
    perf analytics + the paid amount (server-side economics)."""
    raw = _mrr_rental()
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_mrr_rental_detail",
        lambda rid, tenant_id="": {"success": True, "detail": raw,
                                    "graph": {"chartdata": {"bars": "[1,2]"}},
                                    "log": {"rental_log": []}})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_rig_performance_history",
        lambda *a, **k: [])
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_market_reference",
        lambda: {"available": False})
    resp = rclient.get("/api/rentals/detail?provider=mrr&id=5657736")
    assert resp.status_code == 200
    data = resp.get_json()
    # 0.00001404 BTC = 1404 sats paid; 613.39 TH·h delivered; yield depends
    # on the shared-state network hashrate (may be cold → available False).
    assert data["pl"]["paid_sats"] == 1404.0
    assert data["pl"]["available"] in (True, False)


# ── Auto-alert: rental closed with P/L below threshold ─────────────────────


def _ended_mrr_rental(rid, end_unix, paid_btc="0.0004", **over):
    """Normalized ENDED MRR rental. Default: 159.32 TH avg × 3.85h (613.4 TH·h)
    paid 0.0004 BTC (40k sats) → at 18.75 sats/TH·h yield the economic P/L is
    ≈ −71% (below a −50 threshold)."""
    r = _mrr_rental(id=rid)
    r["ended"] = True
    r["end_unix"] = str(end_unix)
    r["price"] = {"type": "legacy", "advertised": "0.00000000",
                  "paid": paid_btc, "currency": "BTC"}
    r.update(over)
    return rp._normalize_rental(r)


def _pl_settings(threshold="-50", window="48"):
    return {"rental_pl_alert_pct": threshold,
            "rental_pl_alert_window_hours": window}


def test_pl_alert_fires_below_threshold_and_dedups(tmp_path, monkeypatch):
    """A closed rental with economic P/L below the tenant threshold fires ONE
    alert; the SAME rental never alerts again (persisted dedup)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pl.sqlite"))
    monkeypatch.setattr(rp, "_network_hashrate_hs", lambda: 100e18)  # 18.75 sats/TH·h
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _pl_settings())
    now = int(time.time())
    hist = [_ended_mrr_rental("r1", now - 1000)]

    a = rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t1", now=now)
    assert len(a) == 1
    alert = a[0]
    assert alert["severity"] == "WARN"
    assert alert["category"] == "rental_pl"
    assert "Rental #r1" in alert["message"]
    assert "P/L -71" in alert["message"] or "P/L −71" in alert["message"] or "P/L -7" in alert["message"]

    # Second evaluation: deduped (one alert per rental EVER).
    assert rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t1", now=now) == []


def test_pl_alert_respects_window(tmp_path, monkeypatch):
    """Rentals that ended BEFORE the window (default 48h) never alert — no
    backfill flood on first enable."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pl2.sqlite"))
    monkeypatch.setattr(rp, "_network_hashrate_hs", lambda: 100e18)
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _pl_settings())
    now = int(time.time())
    old = now - 200 * 3600  # ~8 days ago
    hist = [_ended_mrr_rental("old", old)]
    assert rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t2", now=now) == []


def test_pl_alert_disabled_when_threshold_empty_or_positive(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pl3.sqlite"))
    monkeypatch.setattr(rp, "_network_hashrate_hs", lambda: 100e18)
    now = int(time.time())
    hist = [_ended_mrr_rental("r1", now - 1000)]
    # empty threshold → off
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _pl_settings(threshold=""))
    assert rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t3", now=now) == []
    # non-negative threshold → off (nonsensical)
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _pl_settings(threshold="0"))
    assert rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t3", now=now) == []


def test_pl_alert_tenant_isolation(tmp_path, monkeypatch):
    """Dedup is per-tenant: the same rental alerts for EACH tenant once."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pl4.sqlite"))
    monkeypatch.setattr(rp, "_network_hashrate_hs", lambda: 100e18)
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _pl_settings())
    now = int(time.time())
    hist = [_ended_mrr_rental("r1", now - 1000)]
    assert len(rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t-a", now=now)) == 1
    assert len(rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t-b", now=now)) == 1
    assert rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t-a", now=now) == []


def test_pl_alert_overpay_vs_market_fallback(tmp_path, monkeypatch):
    """Cold box (no network hashrate → economic P/L impossible): the alert
    falls back to OVERPAY vs the live market price (> (1+|threshold|/100)×)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pl5.sqlite"))
    monkeypatch.setattr(rp, "_network_hashrate_hs", lambda: 0.0)  # cold
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _pl_settings(threshold="-50"))
    offers = [_mkt_offer("braiins", 0.000120)]  # 500 sats/TH·h
    monkeypatch.setattr(rp, "_fetch_market_offers", lambda: offers)
    now = int(time.time())
    # cost 2000 sats/TH·h (paid 0.0122678 BTC for 613.4 TH·h) vs market 500 →
    # 4× > 1.5× → fires the overpay branch.
    hist = [_ended_mrr_rental("r1", now - 1000, paid_btc="0.0122678")]
    a = rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t5", now=now)
    assert len(a) == 1
    assert "mercado" in a[0]["message"]
    # Cheap rental (1.2× market) → below the 1.5× bar → no alert.
    hist2 = [_ended_mrr_rental("r2", now - 1000, paid_btc="0.000368")]  # 600 sats/TH·h
    assert rp.evaluate_rental_pl_alerts(hist2, [], tenant_id="t5", now=now) == []


def test_pl_alert_mark_is_atomic(tmp_path, monkeypatch):
    """_mark_pl_alert_fired returns True only for the FIRST claimant — a
    concurrent /api/rentals request cannot double-fire (INSERT OR IGNORE)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pl7.sqlite"))
    assert rp._mark_pl_alert_fired("t", "mrr", "r-atomic", -71.2) is True
    assert rp._mark_pl_alert_fired("t", "mrr", "r-atomic", -71.2) is False
    # Different tenant / different rental → fresh claim.
    assert rp._mark_pl_alert_fired("t2", "mrr", "r-atomic", -71.2) is True
    assert rp._mark_pl_alert_fired("t", "mrr", "r-other", -90.0) is True


# ── CFO: recommendation engine + market timing + auto-blacklist ───────────


def _reco_hist_row(rid, rig_id, rig_name, pct, cost, start):
    return {"provider": "mrr", "rental_id": rid, "rig_id": rig_id,
            "rig_name": rig_name, "start": start, "end": None,
            "percent": pct, "avg_th": 100.0, "advertised_th": 100.0,
            "cost_sats_per_thh": cost, "length_hours": 1.0,
            "delivered_thh": 100.0,
            "paid_sats": (cost * 100.0) if cost is not None else None}


def test_build_rental_recommendations_ranks_and_counts_avoid(tmp_path, monkeypatch):
    """build_rental_recommendations ranks MRR rigs by reliability × price,
    excludes blacklists + grade F (counted in avoid), and needs a track
    record (a rig with no samples never appears)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "reco.sqlite"))
    rows = [
        # 5 samples for rigA → above the sample-size cap, so it earns grade A.
        _reco_hist_row("0", "rigA", "Rig A", 99, 508, "2026-07-19 10:00:00"),
        _reco_hist_row("1", "rigA", "Rig A", 98, 520, "2026-07-20 10:00:00"),
        _reco_hist_row("2", "rigA", "Rig A", 96, 510, "2026-07-21 10:00:00"),
        _reco_hist_row("3", "rigA", "Rig A", 97, 505, "2026-07-22 10:00:00"),
        _reco_hist_row("10", "rigA", "Rig A", 97, 512, "2026-07-23 10:00:00"),
        _reco_hist_row("4", "rigB", "Rig B", 85, 600, "2026-07-20 10:00:00"),
        _reco_hist_row("5", "rigB", "Rig B", 88, 590, "2026-07-21 10:00:00"),
        _reco_hist_row("6", "rigB", "Rig B", 82, 610, "2026-07-22 10:00:00"),
        _reco_hist_row("7", "rigF", "Rig F", 60, 700, "2026-07-20 10:00:00"),
        _reco_hist_row("8", "rigF", "Rig F", 55, 690, "2026-07-21 10:00:00"),
        _reco_hist_row("9", "rigF", "Rig F", 58, 710, "2026-07-22 10:00:00"),
    ]
    assert rp.save_rental_history(rows, tenant_id="t-reco") is True
    offers = [_mkt_offer("mrr", 0.000120)]  # 500 sats/TH·h
    monkeypatch.setattr(rp, "_fetch_market_offers", lambda: offers)

    rec = rp.build_rental_recommendations(tenant_id="t-reco")
    assert rec["tracked"] == 3
    assert rec["avoid_count"] == 1  # rigF grade F
    top = rec["top"]
    assert len(top) >= 1
    # Rig A (A-grade, cheap) outranks Rig B (C-grade, pricier).
    assert top[0]["rig_id"] == "rigA"
    assert top[0]["grade"] == "A"
    assert top[0]["vs_market_pct"] is not None and top[0]["vs_market_pct"] > 0
    # No rigF anywhere in top (excluded).
    assert all(t["rig_id"] != "rigF" for t in top)


def test_build_rental_recommendations_empty_without_track_record(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "reco2.sqlite"))
    rec = rp.build_rental_recommendations(tenant_id="t-none")
    assert rec["top"] == [] and rec["tracked"] == 0


def test_market_trend_aggregates_daily_cheapest(tmp_path, monkeypatch):
    """fetch_market_trend returns one point per day (the CHEAPEST offer) with
    the sats/TH·h conversion + a summary vs the 30d average."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "trend.sqlite"))
    conn = rp.get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS hashrate_market_history (
        ts INTEGER, provider TEXT, hashrate REAL, price_per_th_day REAL,
        duration_days REAL, fee_pct REAL, algorithm TEXT, score REAL, raw_data TEXT)""")
    base = int(time.time()) - 3 * 86400
    for i in range(3):
        ts = base + i * 86400
        # Two providers per day — the MIN must win (braiins cheaper).
        c.execute("INSERT INTO hashrate_market_history VALUES (?,?,?,?,?,?,?,?,?)",
                  (ts, "mrr", 100.0, 0.000240, 1.0, 0.0, "sha256", 1.0, "{}"))
        c.execute("INSERT INTO hashrate_market_history VALUES (?,?,?,?,?,?,?,?,?)",
                  (ts, "braiins", 100.0, 0.000120, 1.0, 0.0, "sha256", 1.0, "{}"))
    conn.commit()
    conn.close()

    trend = rp.fetch_market_trend(days=30)
    assert len(trend["points"]) == 3
    # 0.00012 BTC/TH/day → 500 sats/TH·h — the cheapest per day wins.
    assert all(abs(p["sats_per_thh"] - 500.0) < 1e-6 for p in trend["points"])
    s = trend["summary"]
    assert s["days"] == 3 and s["avg_sats_per_thh"] == 500.0
    assert s["current_sats_per_thh"] == 500.0 and s["vs_avg_pct"] == 0.0


def test_auto_blacklist_flow(tmp_path, monkeypatch):
    """analyze_rig auto-excludes a grade-F rig (≥2 samples) into the AUTO
    list; is_rig_blacklisted sees it; a restore clears BOTH lists AND is
    respected: the same streak never re-excludes — only NEW bad samples
    after the restore do."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "auto.sqlite"))
    bad_hist = [{"id": "1", "start": "2026-07-20 10:00:00", "percent": 60.0},
                {"id": "2", "start": "2026-07-21 10:00:00", "percent": 55.0}]
    monkeypatch.setattr(rp, "fetch_rig_performance_history", lambda *a, **k: bad_hist)
    out = rp.analyze_rig(rig_id="rigZ", tenant_id="t-auto")
    assert out["auto_blacklisted"] is True
    assert out["trust"]["grade"] == "F"
    assert rp.is_rig_blacklisted("rigZ", tenant_id="t-auto") is True
    assert rp.is_rig_auto_blacklisted("rigZ", tenant_id="t-auto") is True
    # Manual restore clears both.
    assert rp.remove_rig_from_blacklist("rigZ", tenant_id="t-auto") is True
    assert rp.is_rig_blacklisted("rigZ", tenant_id="t-auto") is False
    # Restore RESPECTED: the same streak (all samples older than the
    # exclusion moment) must NOT re-exclude on the next detail view.
    out2 = rp.analyze_rig(rig_id="rigZ", tenant_id="t-auto")
    assert out2["auto_blacklisted"] is False
    assert rp.is_rig_blacklisted("rigZ", tenant_id="t-auto") is False
    # A NEW bad sample AFTER the restore re-excludes (fresh streak).
    new_hist = bad_hist + [{"id": "3", "start": "2099-01-01 10:00:00", "percent": 50.0}]
    monkeypatch.setattr(rp, "fetch_rig_performance_history", lambda *a, **k: new_hist)
    out3 = rp.analyze_rig(rig_id="rigZ", tenant_id="t-auto")
    assert out3["auto_blacklisted"] is True
    assert rp.is_rig_blacklisted("rigZ", tenant_id="t-auto") is True


def test_auto_blacklist_not_for_good_rig(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "auto2.sqlite"))
    monkeypatch.setattr(
        rp, "fetch_rig_performance_history",
        lambda *a, **k: [{"id": "1", "start": "2026-07-20", "percent": 97.0},
                         {"id": "2", "start": "2026-07-21", "percent": 96.0}])
    out = rp.analyze_rig(rig_id="rigGood", tenant_id="t-auto2")
    assert out["auto_blacklisted"] is False
    assert rp.is_rig_blacklisted("rigGood", tenant_id="t-auto2") is False


def test_list_route_carries_reco_trend_and_export(rclient, monkeypatch):
    """GET /api/rentals includes recommendations + market_trend + auto list,
    and /api/rentals/export returns a CSV ledger."""
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=50, tenant_id="": {
            "success": True, "needs_auth": False,
            "rentals": [rp._normalize_rental(_mrr_rental())] if (rtype == "renter" and not history) else [],
            "total": 1})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False, "contracts": []})
    monkeypatch.setattr(
        _app_module._rental_perf, "get_rig_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(
        _app_module._rental_perf, "get_auto_blacklist", lambda tenant_id="": ["376882"])
    monkeypatch.setattr(
        _app_module._rental_perf, "ingest_rentals", lambda *a, **k: True)
    monkeypatch.setattr(
        _app_module._rental_perf, "evaluate_rental_pl_alerts", lambda *a, **k: [])
    monkeypatch.setattr(
        _app_module._rental_perf, "build_rental_recommendations",
        lambda tenant_id="": {"top": [{"rig_id": "376882", "name": "A02 165TH", "grade": "A",
                                        "score": 96.0, "samples": 4}],
                              "avoid_count": 0, "tracked": 1,
                              "market": {"available": True, "price_sats_per_thh": 500.0}})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_market_trend",
        lambda days=30: {"points": [{"day": "2026-07-22", "sats_per_thh": 500.0}],
                         "summary": {"days": 1, "avg_sats_per_thh": 500.0,
                                      "current_sats_per_thh": 500.0,
                                      "vs_avg_pct": 0.0}})

    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["recommendations"]["top"][0]["rig_id"] == "376882"
    assert data["market_trend"]["summary"]["days"] == 1
    assert data["rig_auto_blacklist"] == ["376882"]

    # CSV export — same fetchers; body must carry the header row + the rental.
    resp = rclient.get("/api/rentals/export")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    body = resp.get_data(as_text=True)
    assert "provider,id,bucket" in body
    assert "mrr,5657736,active" in body


def test_pl_alert_skips_braiins_contracts(tmp_path, monkeypatch):
    """Braiins ended contracts are intentionally skipped (list payload has no
    delivered TH·h — alerting on advertised speed would be dishonest)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pl6.sqlite"))
    monkeypatch.setattr(rp, "_network_hashrate_hs", lambda: 100e18)
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _pl_settings())
    now = int(time.time())
    contracts = [{"id": "B1", "status": "FINISHED", "ended_at": "2026-08-01T00:00:00Z",
                  "amount_sat": 50000000, "speed_limit_ph": 100.0}]
    assert rp.evaluate_rental_pl_alerts([], contracts, tenant_id="t6", now=now) == []


def test_detail_route_braiins_has_stability_and_pl(rclient, monkeypatch):
    """POST /api/rentals/detail (braiins) surfaces the speed-series STABILITY
    grade + the P/L economics."""
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_braiins_contract_detail",
        lambda cid, contract=None, tenant_id="": {
            "success": True,
            "detail": {"id": cid, "perf": {"percent": 100.0, "delivered_thh": 100.0}},
            "graph": {"points": []},
            "stability": {"cv_pct": 2.0, "mean_ph": 100.0, "grade": "STABLE",
                          "min_ph": 99.0, "max_ph": 101.0, "label": "STABLE"},
            "pl": {"available": False}})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_market_reference",
        lambda: {"available": False})
    resp = rclient.post("/api/rentals/detail",
                        json={"provider": "braiins", "id": "B1", "contract": {"id": "B1"}})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["stability"]["grade"] == "STABLE"
    assert data["pl"] == {"available": False}


def test_list_route_fires_pl_alerts(rclient, monkeypatch):
    """GET /api/rentals triggers the P/L auto-alert for the CALLER's tenant:
    push always; webhook only when the tenant configured a URL. Fire-and-
    forget dispatchers are patched (the route imports them from
    services.user_polling at call time)."""
    import services.user_polling as _up
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=50, tenant_id="": {
            "success": True, "needs_auth": False, "rentals": [], "total": 0})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False, "contracts": []})
    monkeypatch.setattr(
        _app_module._rental_perf, "get_rig_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(
        _app_module._rental_perf, "ingest_rentals", lambda *a, **k: True)
    monkeypatch.setattr(
        _app_module._rental_perf, "evaluate_rental_pl_alerts",
        lambda *a, **k: [{"severity": "WARN", "category": "rental_pl",
                          "message": "Rental #1 fechou com prejuízo",
                          "rental_id": "1", "provider": "mrr"}])
    fired = {"webhook": [], "push": []}
    monkeypatch.setattr(_up, "_fire_webhook_async", lambda kw: fired["webhook"].append(kw))
    monkeypatch.setattr(_up, "_fire_push_async",
                        lambda t, s, c, m: fired["push"].append((t, s, c, m)))
    # No webhook configured (conftest default) → only push fires.
    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    assert len(fired["push"]) == 1
    assert fired["push"][0][1] == "WARN" and fired["push"][0][2] == "rental_pl"
    assert fired["webhook"] == []

    # Tenant WITH a webhook URL → webhook fired too (tenant-aware settings).
    import services.settings as _settings_mod
    monkeypatch.setattr(
        _settings_mod, "load_settings",
        lambda tenant_id="": {"webhook_url": "https://discord.com/api/webhooks/x",
                              "webhook_min_severity": "WARN"})
    fired["webhook"].clear()
    fired["push"].clear()
    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    assert len(fired["webhook"]) == 1
    assert fired["webhook"][0]["url"] == "https://discord.com/api/webhooks/x"
    assert fired["webhook"][0]["category"] == "rental_pl"
    assert len(fired["push"]) == 1


# ── Braiins spot EXECUTION: quote, balance, bid (real money) ─────────────────

def _fake_braiins_key(monkeypatch, key="owner-token"):
    """Point the tenant key resolver at a known token. _braiins_key calls the
    binding IMPORTED into rp (not _tools'), so patch that one."""
    monkeypatch.setattr(rp, "braiins_credentials",
                        lambda tenant_id="": {"api_key": key})


def test_create_braiins_bid_posts_correct_body(monkeypatch):
    """POST /spot/bid body follows the live API units: speed_limit_ph (PH/s),
    amount_sat, price_sat, dest_upstream.url + identity, memo, cl_order_id."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(rp, "braiins_price_unit", lambda tenant_id="": "sats/PH/day")
    sent = {}

    def fake_post(url, json=None, headers=None, timeout=20):
        sent["url"] = url
        sent["json"] = json
        sent["headers"] = headers
        return FakeResponse(payload={"bid_id": "BID-123", "amount_sat": 500000})

    monkeypatch.setattr(rp.requests, "post", fake_post)
    out = rp.create_braiins_bid(
        speed_limit_ph=1.0, amount_sat=500000, price_sat=123456,
        upstream_url="stratum+tcp://pool.example:3333",
        upstream_identity="user.worker", memo="bat1",
        cl_order_id="c65-abc123", tenant_id="")
    assert out["success"] is True
    assert out["bid"]["id"] == "BID-123"
    assert sent["url"] == "https://hashpower.braiins.com/v1/spot/bid"
    body = sent["json"]
    assert body["speed_limit_ph"] == 1.0
    assert body["amount_sat"] == 500000
    assert body["price_sat"] == 123456
    assert body["dest_upstream"]["url"] == "stratum+tcp://pool.example:3333"
    assert body["dest_upstream"]["identity"] == "user.worker"
    assert body["memo"] == "bat1"
    assert body["cl_order_id"] == "c65-abc123"
    assert sent["headers"]["apikey"] == "owner-token"


def test_create_braiins_bid_401_fail_closed(monkeypatch):
    """Rejected key → needs_auth (never a generic failure)."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(rp, "braiins_price_unit", lambda tenant_id="": "sats/PH/day")
    monkeypatch.setattr(rp.requests, "post",
                        lambda *a, **k: FakeResponse(ok=False, status_code=401))
    out = rp.create_braiins_bid(1.0, 500000, 123456,
                                "stratum+tcp://h:3333", tenant_id="")
    assert out["success"] is False
    assert out["needs_auth"] is True


def test_create_braiins_bid_clamps_out_of_band(monkeypatch):
    """Sanity clamps run BEFORE the wire: a unit bug (e.g. TH mistaken for
    PH) must never reach the API."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(rp, "braiins_price_unit", lambda tenant_id="": "sats/PH/day")
    called = []
    monkeypatch.setattr(rp.requests, "post",
                        lambda *a, **k: called.append(1) or FakeResponse())
    # speed out of band (0.0005 PH = 0.5 TH < 1 TH floor; 5000 PH = 5 EH cap)
    assert rp.create_braiins_bid(0.0005, 500000, 123456, "stratum+tcp://h:3333")["success"] is False
    assert rp.create_braiins_bid(5000.0, 500000, 123456, "stratum+tcp://h:3333")["success"] is False
    # amount out of band
    assert rp.create_braiins_bid(1.0, 100, 123456, "stratum+tcp://h:3333")["success"] is False
    assert rp.create_braiins_bid(1.0, 200_000_000, 123456, "stratum+tcp://h:3333")["success"] is False
    # price out of band (a PH/day unit bug lands far outside 1e4..1e9)
    assert rp.create_braiins_bid(1.0, 500000, 5, "stratum+tcp://h:3333")["success"] is False
    # non-stratum upstream rejected
    assert rp.create_braiins_bid(1.0, 500000, 123456, "https://pool.example")["success"] is False
    assert called == []  # NOTHING reached the API


def test_create_braiins_bid_missing_key(monkeypatch):
    """No key anywhere → explicit needs_auth, no HTTP at all."""
    _fake_braiins_key(monkeypatch, key="")
    called = []
    monkeypatch.setattr(rp.requests, "post",
                        lambda *a, **k: called.append(1) or FakeResponse())
    out = rp.create_braiins_bid(1.0, 500000, 123456, "stratum+tcp://h:3333")
    assert out["success"] is False
    assert out["needs_auth"] is True
    assert called == []


def test_create_braiins_bid_honors_account_price_unit(monkeypatch):
    """MONEY-SAFETY: the account's price unit (spot/settings) must be honored
    on the wire. A sats/TH/day account gets price_sat / 1000 (PH/day → TH/day);
    an UNKNOWN unit fails closed (never guess with real money)."""
    _fake_braiins_key(monkeypatch)
    sent = []

    def fake_post(url, json=None, headers=None, timeout=20):
        sent.append(json)
        return FakeResponse(payload={"bid_id": "B1"})

    monkeypatch.setattr(rp.requests, "post", fake_post)

    # Account priced per TH/day → price 123456 sats/PH/day = 123 sats/TH/day.
    monkeypatch.setattr(rp, "braiins_price_unit", lambda tenant_id="": "sats/TH/day")
    out = rp.create_braiins_bid(1.0, 500000, 123456, "stratum+tcp://h:3333")
    assert out["success"] is True
    assert sent[-1]["price_sat"] == 123

    # Unknown unit → refuse before the wire (no POST made for this call).
    n_before = len(sent)
    monkeypatch.setattr(rp, "braiins_price_unit", lambda tenant_id="": "sats/KH/hour")
    out = rp.create_braiins_bid(1.0, 500000, 123456, "stratum+tcp://h:3333")
    assert out["success"] is False
    assert "unit" in out["error"].lower()
    assert len(sent) == n_before


def test_fetch_braiins_balance_items_envelope(monkeypatch):
    """items envelope (total/available/blocked balance_types) → sats."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(
        rp.requests, "get",
        lambda *a, **k: FakeResponse(payload={"items": [
            {"balance_type": "total", "amount": "1000000"},
            {"balance_type": "available", "amount": "800000"},
            {"balance_type": "blocked", "amount": "200000"},
        ]}))
    out = rp.fetch_braiins_balance()
    assert out["available"] is True
    assert out["total_sat"] == 1000000
    assert out["available_sat"] == 800000
    assert out["blocked_sat"] == 200000


def test_fetch_braiins_balance_flat_envelope(monkeypatch):
    """Flat dict envelope {total, available, blocked} also parses."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(rp.requests, "get",
                        lambda *a, **k: FakeResponse(
                            payload={"total": "5000000", "available": "4900000"}))
    out = rp.fetch_braiins_balance()
    assert out["total_sat"] == 5000000
    assert out["available_sat"] == 4900000


def test_fetch_braiins_balance_401_surfaces(monkeypatch):
    """401 from a CONFIGURED key → needs_auth error (never a zero balance)."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(rp.requests, "get",
                        lambda *a, **k: FakeResponse(ok=False, status_code=401))
    out = rp.fetch_braiins_balance()
    assert out["available"] is False
    assert out["needs_auth"] is True
    assert "401" in out["error"]


def test_braiins_quote_converts_units_and_includes_balance(monkeypatch):
    """quote: orderbook BTC/TH/day → sats/TH·h + raw sats/PH/day, with the
    tenant's balance attached for the buy modal prefill."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(
        _tools, "get_braiins_orderbook",
        lambda: {"price_btc_per_th_day": 0.0001230,
                 "best_order_hr_ph": 500.0,
                 "price_raw_unit": "sats/PH/day"})
    monkeypatch.setattr(
        rp, "fetch_braiins_balance",
        lambda tenant_id="": {"available": True, "available_sat": 800000})
    q = rp.braiins_quote()
    assert q["available"] is True
    # 0.0001230 BTC/TH·day × 1e8 / 24 → sats/TH·h
    assert q["price_sats_per_thh"] == round(0.0001230 * 1e8 / 24.0, 2)
    # × 1000 → sats/PH·day (the raw bid unit)
    assert q["price_sat_per_ph_day"] == round(0.0001230 * 1e8 * 1000.0, 0)
    assert q["balance"]["available_sat"] == 800000


def test_bid_route_th_to_ph_and_validation(rclient, monkeypatch):
    """POST /api/rentals/braiins/bid: TH→PH conversion, required fields,
    clamped errors, and the idempotency key passthrough."""
    _fake_braiins_key(monkeypatch)
    sent = {}

    def fake_create(speed_limit_ph=None, amount_sat=None, price_sat=None,
                    upstream_url="", upstream_identity="", memo="",
                    cl_order_id="", tenant_id=""):
        sent.update(locals())
        return {"success": True, "bid": {"id": "BID-ROUTE", "raw": {}}}

    monkeypatch.setattr(_app_module._rental_perf, "create_braiins_bid", fake_create)

    # Missing amount/price → 400 before any provider call.
    resp = rclient.post("/api/rentals/braiins/bid",
                        json={"speed_limit_th": 1000, "upstream_url": "stratum+tcp://h:3333"})
    assert resp.status_code == 400

    # Zero hashrate → 400.
    resp = rclient.post("/api/rentals/braiins/bid", json={
        "speed_limit_th": 0, "amount_sat": 500000, "price_sat": 123456,
        "upstream_url": "stratum+tcp://h:3333"})
    assert resp.status_code == 400

    # Valid: 1000 TH → 1.0 PH on the wire; cl_order_id passed through.
    resp = rclient.post("/api/rentals/braiins/bid", json={
        "speed_limit_th": 1000, "amount_sat": 500000, "price_sat": 123456,
        "upstream_url": "stratum+tcp://h:3333",
        "upstream_identity": "u.w", "memo": "bat", "cl_order_id": "c65-x"})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert sent["speed_limit_ph"] == 1.0
    assert sent["amount_sat"] == 500000
    assert sent["cl_order_id"] == "c65-x"


def test_bid_route_surfaces_clamp_error(rclient, monkeypatch):
    """Out-of-band inputs come back as 400 with the clamp message (a unit bug
    must never look like a provider failure)."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(
        _app_module._rental_perf, "create_braiins_bid",
        lambda **k: {"success": False,
                     "error": "speed_limit must be 0.001-1000.0 PH/s"})
    resp = rclient.post("/api/rentals/braiins/bid", json={
        "speed_limit_th": 5_000_000, "amount_sat": 500000, "price_sat": 123456,
        "upstream_url": "stratum+tcp://h:3333"})
    assert resp.status_code == 400
    assert "speed_limit" in resp.get_json()["error"]


def test_quote_and_balance_routes(rclient, monkeypatch):
    """GET quote/balance routes surface the tenant data (mocked at module)."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(
        _tools, "get_braiins_orderbook",
        lambda: {"price_btc_per_th_day": 0.0001230, "price_raw_unit": "sats/PH/day"})
    monkeypatch.setattr(
        rp, "fetch_braiins_balance",
        lambda tenant_id="": {"available": True, "available_sat": 800000})
    q = rclient.get("/api/rentals/braiins/quote")
    assert q.status_code == 200
    assert q.get_json()["available"] is True
    assert q.get_json()["balance"]["available_sat"] == 800000
    b = rclient.get("/api/rentals/braiins/balance")
    assert b.status_code == 200
    assert b.get_json()["available_sat"] == 800000


def test_braiins_price_unit_default(monkeypatch):
    """spot/settings unreachable → default sats/PH/day (never crash)."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(rp.requests, "get",
                        lambda *a, **k: FakeResponse(ok=False, status_code=503))
    assert rp.braiins_price_unit() == "sats/PH/day"
    monkeypatch.setattr(
        rp.requests, "get",
        lambda *a, **k: FakeResponse(payload={"price_unit": "sats/TH/h"}))
    assert rp.braiins_price_unit() == "sats/TH/h"


# ── Portfolio TIME SERIES: spent + estimated P/L per week/month ─────────────

def _series_row(rid, start, paid_sats, delivered_thh=100.0, tenant="t1"):
    return {"provider": "mrr", "rental_id": rid, "rig_id": "rig1",
            "rig_name": "Rig 1", "start": start, "end": None,
            "percent": 96.0, "avg_th": 100.0, "advertised_th": 100.0,
            "cost_sats_per_thh": None, "length_hours": 1.0,
            "delivered_thh": delivered_thh, "paid_sats": paid_sats}


def test_portfolio_series_buckets_week_with_tenant_isolation(tmp_path, monkeypatch):
    """compute_portfolio_series aggregates spent + estimated P/L per ISO week
    from the LOCAL table, scoped to the tenant (never cross-tenant)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series.sqlite"))
    monkeypatch.setattr(rp, "compute_rental_pl",
                        lambda delivered, paid, **k: {"pl_sats": -100.0, "pl_pct": -50.0})
    rows = [
        _series_row("1", "2026-07-20 10:00:00 UTC", 5000),   # W30
        _series_row("2", "2026-07-21 10:00:00 UTC", 3000),   # W30
        _series_row("3", "2026-07-28 10:00:00 UTC", 8000),   # W31
        _series_row("4", "2026-07-29 10:00:00 UTC", 2000),   # W31 (other tenant? no)
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    assert rp.save_rental_history([_series_row("9", "2026-07-29 10:00:00 UTC", 999999)],
                                  tenant_id="t2") is True

    s = rp.compute_portfolio_series(tenant_id="t1", bucket="week")
    assert s["bucket"] == "week" and s["estimate"] is True
    assert [p["label"] for p in s["points"]] == ["2026-W30", "2026-W31"]
    assert s["points"][0]["spent_sats"] == 8000
    assert s["points"][1]["spent_sats"] == 10000  # 8000 + 2000
    # Each rental contributes -100 pl → cumulatives -200 then -400.
    assert s["points"][0]["pl_sats"] == -200.0
    assert s["points"][0]["cum_pl_sats"] == -200.0
    assert s["points"][1]["cum_pl_sats"] == -400.0
    # t2's 999999-sat rental is NOT in t1's series.
    assert s["totals"]["spent_sats"] == 18000  # 5000+3000+8000+2000
    assert s["totals"]["rentals"] == 4


def test_portfolio_series_month_bucket_and_unparseable_start(tmp_path, monkeypatch):
    """bucket=month groups by calendar month; rows with unparseable start fall
    back to created_ts so they never vanish from the series."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series2.sqlite"))
    monkeypatch.setattr(rp, "compute_rental_pl",
                        lambda delivered, paid, **k: {"pl_sats": -50.0})
    rows = [
        _series_row("1", "2026-06-15 10:00:00 UTC", 1000),
        _series_row("2", "2026-07-20 10:00:00 UTC", 2000),
        _series_row("3", "garbage-date", 4000),  # → created_ts fallback
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    s = rp.compute_portfolio_series(tenant_id="t1", bucket="month")
    labels = [p["label"] for p in s["points"]]
    # created_ts fallback buckets row 3 into the ingest month (now).
    assert "2026-06" in labels and "2026-07" in labels
    assert len(labels) == len(set(labels))  # no dup labels
    assert sum(p["spent_sats"] for p in s["points"]) == 7000


def test_portfolio_series_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series3.sqlite"))
    s = rp.compute_portfolio_series(tenant_id="nobody", bucket="week")
    assert s["points"] == [] and s["totals"] == {}


def test_portfolio_series_unknown_yield_is_null_not_zero(tmp_path, monkeypatch):
    """HONEST TELEMETRY: when no rental in a bucket has computable P/L (cold
    box, network hashrate unknown), pl_sats/cum_pl_sats are None — a flat 0
    would read as 'no loss' and fabricate a verdict."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series4.sqlite"))
    # compute_rental_pl without yield → pl_sats None (mimics cold box).
    monkeypatch.setattr(rp, "compute_rental_pl",
                        lambda delivered, paid, **k: {"pl_sats": None, "pl_pct": None})
    assert rp.save_rental_history([_series_row("1", "2026-07-20 10:00:00 UTC", 5000)],
                                  tenant_id="t1") is True
    s = rp.compute_portfolio_series(tenant_id="t1", bucket="week")
    assert s["points"][0]["pl_sats"] is None
    assert s["points"][0]["cum_pl_sats"] is None
    assert s["totals"]["pl_sats"] is None
    # Spend is still real — only the P/L verdict is withheld.
    assert s["totals"]["spent_sats"] == 5000


def test_portfolio_series_partial_known_yield(tmp_path, monkeypatch):
    """A known bucket reports numbers; once an UNKNOWN bucket appears the
    cumulative from that point is genuinely unknown (None) — summing only
    the known pieces would understate the loss and fabricate a verdict."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series5.sqlite"))
    monkeypatch.setattr(rp, "compute_rental_pl",
                        lambda delivered, paid, **k: {"pl_sats": -100.0} if delivered else {"pl_sats": None})
    rows = [
        _series_row("1", "2026-07-20 10:00:00 UTC", 5000, delivered_thh=100.0),
        _series_row("2", "2026-07-27 10:00:00 UTC", 3000, delivered_thh=None),  # unknown
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    s = rp.compute_portfolio_series(tenant_id="t1", bucket="week")
    assert s["points"][0]["pl_sats"] == -100.0
    assert s["points"][0]["cum_pl_sats"] == -100.0
    assert s["points"][1]["pl_sats"] is None
    assert s["points"][1]["cum_pl_sats"] is None  # total through W31 is unknown


def test_series_route_returns_bucket(rclient, monkeypatch):
    """GET /api/rentals/series?bucket=month returns the server aggregation."""
    monkeypatch.setattr(
        _app_module._rental_perf, "compute_portfolio_series",
        lambda tenant_id="", bucket="week": {
            "bucket": bucket, "estimate": True,
            "points": [{"label": "2026-07", "spent_sats": 1000, "pl_sats": -50.0,
                        "cum_pl_sats": -50.0, "delivered_thh": 100.0, "rentals": 1}],
            "totals": {"spent_sats": 1000, "pl_sats": -50.0, "rentals": 1}})
    resp = rclient.get("/api/rentals/series?bucket=month")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["bucket"] == "month"
    assert data["points"][0]["spent_sats"] == 1000
    assert data["totals"]["rentals"] == 1
