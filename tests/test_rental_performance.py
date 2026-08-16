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
        self._payload = (
            payload if payload is not None else {"success": True, "data": {}}
        )

    def json(self):
        return self._payload


def _mrr_rental(**over):
    base = {
        "id": "5657736",
        "owner": "almansoorii",
        "renter": "cypher",
        "hashrate": {
            "advertised": {"hash": "0.165", "type": "ph", "nice": "165.00T"},
            "average": {
                "hash": "0.15932150061561",
                "type": "ph",
                "nice": "159.32T",
                "percent": "96.56",
            },
        },
        "price": {
            "type": "legacy",
            "advertised": "0.00000000",
            "paid": "0.00001404",
            "currency": "BTC",
        },
        "length": "3.85",
        "extended": "0",
        "extensions": [],
        "start": "2026-07-25 19:17:20 UTC",
        "end": "2026-07-25 23:08:20 UTC",
        "start_unix": "1785007040",
        "end_unix": "1785020900",
        "ended": True,
        "rig": {
            "id": "376882",
            "name": "A02 165TH",
            "type": "sha256ab",
            "status": {"status": "available", "rented": False, "online": True},
            "online": True,
            "region": "eu-de",
            "rpi": "100.00",
        },
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
    payload = {
        "success": True,
        "data": {
            "total": 34,
            "returned": 1,
            "start": 0,
            "limit": 25,
            "rentals": [_mrr_rental()],
        },
    }
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
    monkeypatch.setattr(
        rp.requests, "get", lambda *a, **k: FakeResponse(ok=False, status_code=503)
    )
    out = rp.fetch_mrr_rentals()
    assert out["success"] is False
    assert "503" in out.get("error", "")


def test_mrr_rentals_permission_error(mrr_creds, monkeypatch):
    payload = {
        "success": False,
        "data": {"permission": "balance", "message": "No Permission - account/1285"},
    }
    monkeypatch.setattr(
        rp.requests, "get", lambda *a, **k: FakeResponse(payload=payload)
    )
    out = rp.fetch_mrr_rentals()
    assert out["success"] is False
    assert "No Permission" in out.get("error", "")
    # Permission denial is NOT a credential problem (Issue #152).
    assert out.get("auth_rejected") is False


def test_is_mrr_auth_rejection_classifier():
    """Issue #152 (c): the MRR credential-rejection classifier matches the
    classic Bad Nonce signature (and variants), never generic/other errors."""
    assert rp._is_mrr_auth_rejection("Not Authenticated - Invalid Key - Bad Nonce.")
    assert rp._is_mrr_auth_rejection("Invalid Key")
    assert rp._is_mrr_auth_rejection("bad nonce")
    assert rp._is_mrr_auth_rejection("Unauthorized: forbidden")
    assert not rp._is_mrr_auth_rejection("No Permission - account/1285")
    assert not rp._is_mrr_auth_rejection("HTTP 503")
    assert not rp._is_mrr_auth_rejection("")
    assert not rp._is_mrr_auth_rejection(None)


def test_mrr_rentals_bad_nonce_flags_auth_rejected(mrr_creds, monkeypatch):
    """A CONFIGURED key rejected by the MRR API ('Invalid Key - Bad Nonce')
    surfaces as auth_rejected=True so the panel explains 'regenerate the key'
    instead of a generic provider error — and needs_auth stays False (the
    credential EXISTS, it's just stale)."""
    payload = {"success": False, "data": "Not Authenticated - Invalid Key - Bad Nonce."}
    monkeypatch.setattr(
        rp.requests, "get", lambda *a, **k: FakeResponse(payload=payload)
    )
    out = rp.fetch_mrr_rentals()
    assert out["success"] is False
    assert out["needs_auth"] is False
    assert out["auth_rejected"] is True
    assert "Bad Nonce" in out.get("error", "")


def test_mrr_rentals_http_401_flags_auth_rejected(mrr_creds, monkeypatch):
    """An HTTP 401/403 with a configured key is also a credential rejection
    (Issue #152) — the panel must not show a generic HTTP error."""
    monkeypatch.setattr(
        rp.requests, "get", lambda *a, **k: FakeResponse(ok=False, status_code=401)
    )
    out = rp.fetch_mrr_rentals()
    assert out["success"] is False
    assert out["needs_auth"] is False
    assert out["auth_rejected"] is True


def test_mrr_rental_detail_graph_log(mrr_creds, monkeypatch):
    detail = {"success": True, "data": _mrr_rental()}
    graph = {
        "success": True,
        "data": {
            "rentalid": "5657736",
            "chartdata": {
                "time_start": "2026-07-25 15:17:20",
                "time_end": "2026-07-25 19:08:20",
                "bars": "[1785007080000,0],[1785007140000,36865135957333]",
            },
        },
    }
    log = {
        "success": True,
        "data": {
            "rental_log": [
                {"id": "43923043", "time": "t", "msg": "Rental #5657736 has finished."}
            ]
        },
    }

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
    # Success path never fabricates a rejection (Issue #174).
    assert out.get("auth_rejected") is False


def test_mrr_rental_detail_bad_nonce_flags_auth_rejected(mrr_creds, monkeypatch):
    """A CONFIGURED key rejected on the DETAIL endpoints also surfaces as
    auth_rejected (Issue #174) — the detail click explains the same fix the
    list already shows, carrying the REAL error body (not just 'HTTP 401')."""
    payload = {"success": False, "data": "Not Authenticated - Invalid Key - Bad Nonce."}
    monkeypatch.setattr(
        rp.requests,
        "get",
        lambda *a, **k: FakeResponse(ok=False, status_code=401, payload=payload),
    )
    out = rp.fetch_mrr_rental_detail("5657736")
    assert out["success"] is False
    assert out["auth_rejected"] is True
    assert "Bad Nonce" in out["detail"]["error"]


def test_mrr_rental_detail_http_error_not_rejected(mrr_creds, monkeypatch):
    """A 5xx (provider down) is NOT a credential problem — never flag it."""
    monkeypatch.setattr(
        rp.requests,
        "get",
        lambda *a, **k: FakeResponse(ok=False, status_code=503),
    )
    out = rp.fetch_mrr_rental_detail("5657736")
    assert out["success"] is False
    assert out["auth_rejected"] is False
    assert "503" in out["detail"]["error"]


def test_mrr_rental_detail_permission_error_not_rejected(mrr_creds, monkeypatch):
    """Permission denial is NOT a credential problem (same as the list fetch,
    Issue #152/#174) — the classifier must not match 'No Permission'."""
    payload = {"success": False, "data": "No Permission - account/1285"}
    monkeypatch.setattr(
        rp.requests,
        "get",
        lambda *a, **k: FakeResponse(payload=payload),
    )
    out = rp.fetch_mrr_rental_detail("5657736")
    assert out["success"] is False
    assert out["auth_rejected"] is False
    assert "No Permission" in out["detail"]["error"]


def test_braiins_contracts_needs_auth(monkeypatch):
    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
    out = rp.fetch_braiins_contracts()
    assert out["success"] is False
    assert out["needs_auth"] is True
    # Issue #187: explicit missing-credential flag so the panel ALWAYS shows
    # the config hint when the key is absent (even on replayed payloads).
    assert out.get("credentials_missing") is True
    assert "BRAIINS_API_KEY" in out.get("error", "")


def test_braiins_key_falls_back_to_settings(monkeypatch):
    """BRAIINS_API_KEY resolves from the Settings DB when the env var is unset
    (same env → Settings fallback as MRR)."""
    import services.settings as _settings_mod

    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
    monkeypatch.setattr(
        _settings_mod, "load_settings", lambda: {"braiins_api_key": "owner-token-db"}
    )
    assert rp._braiins_key() == "owner-token-db"


def test_braiins_key_env_wins_over_settings(monkeypatch):
    import services.settings as _settings_mod

    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token-env")
    monkeypatch.setattr(
        _settings_mod, "load_settings", lambda: {"braiins_api_key": "owner-token-db"}
    )
    assert rp._braiins_key() == "owner-token-env"


def test_braiins_contracts_with_key(monkeypatch):
    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token")
    contract = {
        "id": "c-1",
        "status": "RUNNING",
        "speed_limit_ph": 121.7,
        "amount_sat": 50000000,
        "price_sat": 50013000,
    }
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
    # Issue #187: parity with MRR — a configured-but-rejected key carries an
    # explicit auth_rejected flag (not only the error text).
    assert out.get("auth_rejected") is True
    assert "rejected" in out.get("error", "").lower()
    assert out["contracts"] == []


def test_braiins_contracts_spot_bid_fallback(monkeypatch):
    """Legacy /contract endpoints may 404 while the current spot API
    (/spot/bid/current, /spot/bid) still returns the caller's orders — the
    probe must fall back and parse the spot envelope + bid_status names."""
    monkeypatch.setenv("BRAIINS_API_KEY", "owner-token")
    bid = {
        "bid_id": "B123",
        "bid_status": "SPOT_BID_STATUS_ACTIVE",
        "speed_limit_ph": 100.0,
        "amount_sat": 20000000,
        "price_sat": 90000000,
        "created_ts": "2026-07-01T00:00:00Z",
    }

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
        return FakeResponse(
            payload={
                "items": [
                    {"timestamp": 1785007000, "speed_ph": 100.0},
                    {"timestamp": 1785007300, "speed_ph": 110.0},
                ]
            }
        )

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
    contract = {
        "id": "c-1",
        "status": "RUNNING",
        "speed_limit_ph": 100.0,
        "amount_sat": 50000000,
        "price_sat": 50013000,
    }

    def fake_get(url, headers=None, timeout=None):
        if "speed" in url:
            return FakeResponse(
                payload={
                    "items": [
                        {"timestamp": 1000, "speed_ph": 100.0},
                        {"timestamp": 4600, "speed_ph": 100.0},
                    ]
                }
            )
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
    contract = {
        "id": "B1",
        "status": "ACTIVE",
        "speed_limit_ph": 50.0,
        "amount_sat": 10000000,
        "price_sat": 30000000,
    }
    urls = []

    def fake_get(url, headers=None, timeout=None):
        urls.append(url)
        return FakeResponse(
            payload={
                "items": [
                    {"timestamp": 0, "speed_ph": 50.0},
                    {"timestamp": 3600, "speed_ph": 50.0},
                ]
            }
        )

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
        _mkt_offer("mrr", 0.000120),  # cheapest live → wins
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
        _mrr_rental(id="1", rig={"id": "376882", "name": "A02 165TH"}),  # same rig id
        _mrr_rental(id="2", rig={"id": "376882", "name": "A02 165TH"}),  # same rig id
        _mrr_rental(id="3", rig={"id": "999", "name": "Other rig"}),  # different rig
        _mrr_rental(id="4", rig={"id": None, "name": "a02 165th"}),  # name-only match
    ]
    # Set distinct starts so the newest-first sort is observable.
    raw[0]["start"] = "2026-07-20 10:00:00 UTC"
    raw[1]["start"] = "2026-07-25 10:00:00 UTC"
    raw[3]["start"] = "2026-07-15 10:00:00 UTC"
    rentals = [rp._normalize_rental(r) for r in raw]

    def fake_listing(**kw):
        return {
            "success": True,
            "needs_auth": False,
            "rentals": rentals,
            "total": len(rentals),
        }

    monkeypatch.setattr(rp, "fetch_mrr_rentals", fake_listing)
    # The real caller (detail route) passes BOTH id and name from the rig.
    out = rp.fetch_rig_performance_history(
        rig_id="376882", rig_name="A02 165TH", exclude_rental_id="1"
    )
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
    # The /api/rentals TTL cache is module-global — reset it per test so
    # sibling tests measure fresh provider fetches (never a stale cached
    # payload from a previous test's mocked providers).
    _app_module._RENTALS_CACHE.clear()
    with _app_module.app.test_client() as c:
        yield c
        _app_module._RENTALS_CACHE.clear()


def test_rentals_payload_carries_version_and_braiins_flags(rclient, monkeypatch):
    """GET /api/rentals stamps rentals_payload_version and passes the braiins
    credential flags through (needs_auth/credentials_missing/auth_rejected) —
    the frontend needs them to tell a stale payload from a real empty account
    (Issue #187)."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_mrr_rentals",
        lambda rtype, history, limit, tenant_id="": {
            "success": True,
            "needs_auth": False,
            "rentals": [],
            "total": 0,
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_braiins_contracts",
        lambda tenant_id="": {
            "success": False,
            "needs_auth": True,
            "credentials_missing": True,
            "auth_rejected": False,
            "contracts": [],
            "error": "BRAIINS_API_KEY not configured",
        },
    )

    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("rentals_payload_version") == 2
    assert data["braiins"]["needs_auth"] is True
    assert data["braiins"]["credentials_missing"] is True
    assert data["braiins"]["auth_rejected"] is False


def test_detail_route_mrr_enriched(rclient, monkeypatch):
    """GET /api/rentals/detail?provider=mrr returns perf + rig_history + market
    computed from the RAW MRR detail (server-side analytics)."""
    raw = _mrr_rental()
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_mrr_rental_detail",
        lambda rid, tenant_id="": {
            "success": True,
            "detail": raw,
            "graph": {"chartdata": {"bars": "[1,2]"}},
            "log": {"rental_log": []},
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_rig_performance_history",
        lambda *a, **k: [{"id": "2", "start": "2026-07-01", "percent": 94.0}],
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_market_reference",
        lambda: {"available": True, "price_sats_per_thh": 500.0, "provider": "mrr"},
    )

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


def test_detail_route_mrr_propagates_auth_rejected(rclient, monkeypatch):
    """A rejected MRR key on the detail call surfaces auth_rejected so the
    modal explains 'regenerate the key' (Issue #174)."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_mrr_rental_detail",
        lambda rid, tenant_id="": {
            "success": False,
            "auth_rejected": True,
            "detail": {"error": "Not Authenticated - Invalid Key - Bad Nonce."},
            "graph": {},
            "log": {},
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_market_reference",
        lambda: {"available": False},
    )

    resp = rclient.get("/api/rentals/detail?provider=mrr&id=5657736")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["provider"] == "mrr"
    assert data["auth_rejected"] is True
    assert "Bad Nonce" in data["detail"]["error"]


def test_detail_route_braiins_market(rclient, monkeypatch):
    """POST /api/rentals/detail (braiins) carries market + empty rig_history."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_braiins_contract_detail",
        lambda cid, contract=None, tenant_id="": {
            "success": True,
            "detail": {"id": cid, "perf": {"percent": 95.0}},
            "graph": {"points": []},
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_market_reference",
        lambda: {"available": True, "price_sats_per_thh": 480.0, "provider": "braiins"},
    )

    resp = rclient.post(
        "/api/rentals/detail",
        json={"provider": "braiins", "id": "B1", "contract": {"id": "B1"}},
    )
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
    monkeypatch.setattr(
        _settings_mod, "load_settings", lambda: {"braiins_api_key": "owner-token\n  "}
    )
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
    monkeypatch.setattr(
        _tools, "braiins_credentials", lambda tenant_id="": {"api_key": ""}
    )
    monkeypatch.delenv("BRAIINS_API_KEY", raising=False)
    resp = rclient.post("/api/settings/test-braiins")
    data = resp.get_json()
    assert data["success"] is False
    assert data["configured"] is False
    assert "not configured" in data["error"]


def test_settings_test_braiins_rejected(rclient, monkeypatch):
    """Configured key that the API refuses → verdict 'rejected' with reason."""
    monkeypatch.setattr(
        _tools, "braiins_credentials", lambda tenant_id="": {"api_key": "owner-token"}
    )
    monkeypatch.setattr(
        rp,
        "fetch_braiins_contracts",
        lambda tenant_id="": {
            "success": False,
            "needs_auth": True,
            "contracts": [],
            "error": "Braiins API rejected the key (HTTP 401/403)",
        },
    )
    resp = rclient.post("/api/settings/test-braiins")
    data = resp.get_json()
    assert data["success"] is False
    assert data["configured"] is True
    assert data["verdict"] == "rejected"
    assert "401" in data["error"]


def test_settings_test_braiins_ok(rclient, monkeypatch):
    """Valid key → verdict 'ok' with the contract count."""
    monkeypatch.setattr(
        _tools, "braiins_credentials", lambda tenant_id="": {"api_key": "owner-token"}
    )
    monkeypatch.setattr(
        rp,
        "fetch_braiins_contracts",
        lambda tenant_id="": {
            "success": True,
            "needs_auth": False,
            "contracts": [{"id": "B1"}, {"id": "B2"}],
        },
    )
    resp = rclient.post("/api/settings/test-braiins")
    data = resp.get_json()
    assert data["success"] is True
    assert data["verdict"] == "ok"
    assert data["contracts"] == 2


def test_hash_to_th_units():
    """MRR hash values carry a unit (ph/mh/gh/th) — normalize to TH/s."""
    assert rp._hash_to_th("0.165", "ph") == 165.0  # 0.165 PH = 165 TH
    assert rp._hash_to_th("159.32", "th") == 159.32  # already TH
    assert rp._hash_to_th("500", "gh") == 0.5  # 500 GH = 0.5 TH
    assert rp._hash_to_th("1", "mh") == 1e-6  # 1 MH = 1e-6 TH
    assert rp._hash_to_th("7", "") == 7.0  # unknown unit → raw
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
    stable = rp.compute_speed_stability(
        [{"speed_ph": 100}, {"speed_ph": 100}, {"speed_ph": 104}]
    )
    assert stable["grade"] == "STABLE" and stable["cv_pct"] < 5
    variable = rp.compute_speed_stability(
        [{"speed_ph": 80}, {"speed_ph": 150}, {"speed_ph": 70}]
    )
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
    active = [
        rp._normalize_rental(_mrr_rental())
    ]  # paid 0.00001404 BTC · avg 159.32 TH · 3.85h
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
    out = rp.fetch_rig_performance_history(
        rig_id="376882", rig_name="A02 165TH", tenant_id="t-hist"
    )
    assert [x["id"] for x in out] == ["5657736"]


def test_fetch_rig_performance_history_remote_fallback(tmp_path, monkeypatch):
    """No local rows → falls back to the MRR history API, persists what it
    finds, and serves the NEXT call from SQLite (no second API hit)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "hist2.sqlite"))
    rentals = [rp._normalize_rental(_mrr_rental())]
    calls = {"n": 0}

    def fake_listing(**kw):
        calls["n"] += 1
        return {"success": True, "needs_auth": False, "rentals": rentals, "total": 1}

    monkeypatch.setattr(rp, "fetch_mrr_rentals", fake_listing)
    # First call: fetches + persists the matched rental.
    out = rp.fetch_rig_performance_history(
        rig_id="376882", rig_name="A02 165TH", tenant_id="t-fb"
    )
    assert len(out) == 1 and out[0]["id"] == "5657736"
    # Second call is served from SQLite — the API is NOT re-hit.
    out2 = rp.fetch_rig_performance_history(
        rig_id="376882", rig_name="A02 165TH", tenant_id="t-fb"
    )
    assert len(out2) == 1 and out2[0]["id"] == "5657736"
    assert calls["n"] == 1


def test_list_route_includes_portfolio_and_ingest(rclient, monkeypatch):
    """GET /api/rentals carries the portfolio block and ingests the fetched
    buckets into local history (track record builds with zero extra calls)."""
    rental = _mrr_rental()
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=50, tenant_id="": {
            "success": True,
            "needs_auth": False,
            "rentals": [rental] if (rtype == "renter" and history) else [],
            "total": 1,
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False, "contracts": []},
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "get_rig_blacklist", lambda tenant_id="": []
    )
    ingested = {}
    monkeypatch.setattr(
        _app_module._rental_perf,
        "ingest_rentals",
        lambda *a, **k: ingested.update({"args": a}) or True,
    )
    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["portfolio"]["spend"]["count"] == 1
    assert data["portfolio"]["split"]["mrr"] == 1
    # ingest_rentals was called with the buckets (not swallowed).
    assert ingested.get("args") and len(ingested["args"]) == 4


def test_list_route_serves_ttl_cache_without_refetch(rclient, monkeypatch):
    """The per-tenant 20s cache (hot-path fix, p95 1.1s → 5ms) means a second
    load within TTL must NOT re-hit the providers."""
    _app_module._RENTALS_CACHE.clear()
    calls = {"n": 0}

    def _fake_mrr(rtype="renter", history=False, limit=50, tenant_id=""):
        calls["n"] += 1
        return {"success": True, "needs_auth": False, "rentals": [], "total": 0}

    monkeypatch.setattr(_app_module._rental_perf, "fetch_mrr_rentals", _fake_mrr)
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False, "contracts": []},
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "get_rig_blacklist", lambda tenant_id="": []
    )

    r1 = rclient.get("/api/rentals")
    assert r1.status_code == 200
    first_calls = calls["n"]
    assert first_calls == 3  # active + history + owner

    r2 = rclient.get("/api/rentals")
    assert r2.status_code == 200
    assert r2.get_json().get("cached") is True
    assert calls["n"] == first_calls  # cache hit → providers NOT re-hit
    _app_module._RENTALS_CACHE.clear()


def test_detail_route_mrr_has_pl(rclient, monkeypatch):
    """GET /api/rentals/detail (mrr) attaches the P/L block computed from the
    perf analytics + the paid amount (server-side economics)."""
    raw = _mrr_rental()
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_mrr_rental_detail",
        lambda rid, tenant_id="": {
            "success": True,
            "detail": raw,
            "graph": {"chartdata": {"bars": "[1,2]"}},
            "log": {"rental_log": []},
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_rig_performance_history", lambda *a, **k: []
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_market_reference", lambda: {"available": False}
    )
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
    r["price"] = {
        "type": "legacy",
        "advertised": "0.00000000",
        "paid": paid_btc,
        "currency": "BTC",
    }
    r.update(over)
    return rp._normalize_rental(r)


def _pl_settings(threshold="-50", window="48"):
    return {"rental_pl_alert_pct": threshold, "rental_pl_alert_window_hours": window}


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
    assert (
        "P/L -71" in alert["message"]
        or "P/L −71" in alert["message"]
        or "P/L -7" in alert["message"]
    )

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
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _pl_settings(threshold="")
    )
    assert rp.evaluate_rental_pl_alerts(hist, [], tenant_id="t3", now=now) == []
    # non-negative threshold → off (nonsensical)
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _pl_settings(threshold="0")
    )
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
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _pl_settings(threshold="-50")
    )
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
    return {
        "provider": "mrr",
        "rental_id": rid,
        "rig_id": rig_id,
        "rig_name": rig_name,
        "start": start,
        "end": None,
        "percent": pct,
        "avg_th": 100.0,
        "advertised_th": 100.0,
        "cost_sats_per_thh": cost,
        "length_hours": 1.0,
        "delivered_thh": 100.0,
        "paid_sats": (cost * 100.0) if cost is not None else None,
    }


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
    assert rec["avoid"] == [] and rec["avoid_count"] == 0


def test_build_rental_recommendations_avoid_detailed_list(tmp_path, monkeypatch):
    """The avoid list carries the PILOT'S FULL CASE per grade-F rig — same
    card schema as top (name, median/worst, cost, trend, last rental),
    sorted worst-first (lowest median delivery), and excludes rigs already
    blacklisted (nothing left to accept)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "reco-avoid.sqlite"))
    rows = [
        # Two grade-F rigs with DIFFERENT severity (rigF2 is worse).
        _reco_hist_row("0", "rigF1", "Rig F1", 64, 690, "2026-07-20 10:00:00"),
        _reco_hist_row("1", "rigF1", "Rig F1", 60, 700, "2026-07-21 10:00:00"),
        _reco_hist_row("2", "rigF1", "Rig F1", 58, 710, "2026-07-22 10:00:00"),
        _reco_hist_row("3", "rigF2", "Rig F2", 55, 800, "2026-07-20 10:00:00"),
        _reco_hist_row("4", "rigF2", "Rig F2", 50, 810, "2026-07-21 10:00:00"),
        _reco_hist_row("5", "rigF2", "Rig F2", 48, 820, "2026-07-22 10:00:00"),
        # Already blacklisted F rig → must NOT appear (operator already acted).
        _reco_hist_row("6", "rigF3", "Rig F3", 40, 900, "2026-07-20 10:00:00"),
        _reco_hist_row("7", "rigF3", "Rig F3", 42, 910, "2026-07-21 10:00:00"),
        _reco_hist_row("8", "rigF3", "Rig F3", 45, 920, "2026-07-22 10:00:00"),
        # A good rig (grade A) must land in top, never in avoid.
        _reco_hist_row("10", "rigA", "Rig A", 97, 510, "2026-07-19 10:00:00"),
        _reco_hist_row("11", "rigA", "Rig A", 98, 515, "2026-07-20 10:00:00"),
        _reco_hist_row("12", "rigA", "Rig A", 96, 512, "2026-07-21 10:00:00"),
        _reco_hist_row("13", "rigA", "Rig A", 97, 508, "2026-07-22 10:00:00"),
    ]
    assert rp.save_rental_history(rows, tenant_id="t-avoid") is True
    monkeypatch.setattr(rp, "get_rig_blacklist", lambda tenant_id="": ["rigF3"])
    monkeypatch.setattr(rp, "_fetch_market_offers", lambda: [])

    rec = rp.build_rental_recommendations(tenant_id="t-avoid")
    avoid = rec["avoid"]
    assert rec["avoid_count"] == 2
    assert len(avoid) == 2
    # Worst first: rigF2 (median ~50) before rigF1 (median ~60).
    assert [a["rig_id"] for a in avoid] == ["rigF2", "rigF1"]
    # Full card schema — the operator can decide without opening the modal.
    for a in avoid:
        assert a["grade"] == "F"
        assert a["name"]
        assert a["median_pct"] is not None
        assert a["worst_pct"] is not None
        assert a["samples"] >= 3
        assert a["avg_cost_sats_per_thh"] is not None
        assert a["last_rental"]
        assert "score" in a
    # Blacklisted rigF3 excluded; the good rigA never lands in avoid.
    assert all(a["rig_id"] != "rigF3" for a in avoid)
    assert all(a["rig_id"] != "rigA" for a in avoid)
    # And the blacklisted rig is not double-counted in top either.
    assert all(t["rig_id"] != "rigF3" for t in rec["top"])


def _reset_trend_cache():
    """Clear the module-level market-trend cache so sibling tests measure a
    fresh DB (the cache is in-memory and shared across tests)."""
    rp._TREND_CACHE["ts"] = 0
    rp._TREND_CACHE["payload"] = None


def test_market_trend_aggregates_daily_cheapest(tmp_path, monkeypatch):
    """fetch_market_trend returns one point per day (the CHEAPEST offer) with
    the sats/TH·h conversion + a summary vs the 30d average."""
    _reset_trend_cache()
    monkeypatch.setenv("DB_PATH", str(tmp_path / "trend.sqlite"))
    conn = rp.get_db()
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS hashrate_market_history (
        ts INTEGER, provider TEXT, hashrate REAL, price_per_th_day REAL,
        duration_days REAL, fee_pct REAL, algorithm TEXT, score REAL, raw_data TEXT)"""
    )
    base = int(time.time()) - 3 * 86400
    for i in range(3):
        ts = base + i * 86400
        # Two providers per day — the MIN must win (braiins cheaper).
        c.execute(
            "INSERT INTO hashrate_market_history VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, "mrr", 100.0, 0.000240, 1.0, 0.0, "sha256", 1.0, "{}"),
        )
        c.execute(
            "INSERT INTO hashrate_market_history VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, "braiins", 100.0, 0.000120, 1.0, 0.0, "sha256", 1.0, "{}"),
        )
    conn.commit()
    conn.close()

    trend = rp.fetch_market_trend(days=30)
    assert len(trend["points"]) == 3
    # 0.00012 BTC/TH/day → 500 sats/TH·h — the cheapest per day wins.
    assert all(abs(p["sats_per_thh"] - 500.0) < 1e-6 for p in trend["points"])
    s = trend["summary"]
    assert s["days"] == 3 and s["avg_sats_per_thh"] == 500.0
    assert s["current_sats_per_thh"] == 500.0 and s["vs_avg_pct"] == 0.0


def test_market_trend_served_from_cache(tmp_path, monkeypatch):
    """The 30-day GROUP BY scan (the /api/rentals hot path, measured ~1.1s
    p95) runs once per TTL window: a second call within TTL reuses the cached
    payload instead of re-scanning hashrate_market_history."""
    _reset_trend_cache()
    monkeypatch.setenv("DB_PATH", str(tmp_path / "trend_cache.sqlite"))
    conn = rp.get_db()
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS hashrate_market_history (
        ts INTEGER, provider TEXT, hashrate REAL, price_per_th_day REAL,
        duration_days REAL, fee_pct REAL, algorithm TEXT, score REAL, raw_data TEXT)"""
    )
    now = int(time.time())
    c.execute(
        "INSERT INTO hashrate_market_history VALUES (?,?,?,?,?,?,?,?,?)",
        (now, "braiins", 100.0, 0.000120, 1.0, 0.0, "sha256", 1.0, "{}"),
    )
    conn.commit()
    conn.close()

    first = rp.fetch_market_trend(days=30)
    assert first["summary"]["days"] == 1
    # Wipe the DB — a cache hit must still return the SAME payload (proving
    # the second call never hit the database).
    conn = rp.get_db()
    conn.execute("DELETE FROM hashrate_market_history")
    conn.commit()
    conn.close()
    second = rp.fetch_market_trend(days=30)
    assert second["summary"]["days"] == 1
    assert second["points"] == first["points"]
    # Past the TTL window the DB is re-scanned (now empty → honest empty).
    rp._TREND_CACHE["ts"] = 0
    third = rp.fetch_market_trend(days=30)
    assert third == {"points": [], "summary": None}


def test_auto_blacklist_flow(tmp_path, monkeypatch):
    """analyze_rig auto-excludes a grade-F rig (≥2 samples) into the AUTO
    list; is_rig_blacklisted sees it; a restore clears BOTH lists AND is
    respected: the same streak never re-excludes — only NEW bad samples
    after the restore do."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "auto.sqlite"))
    bad_hist = [
        {"id": "1", "start": "2026-07-20 10:00:00", "percent": 60.0},
        {"id": "2", "start": "2026-07-21 10:00:00", "percent": 55.0},
    ]
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
        rp,
        "fetch_rig_performance_history",
        lambda *a, **k: [
            {"id": "1", "start": "2026-07-20", "percent": 97.0},
            {"id": "2", "start": "2026-07-21", "percent": 96.0},
        ],
    )
    out = rp.analyze_rig(rig_id="rigGood", tenant_id="t-auto2")
    assert out["auto_blacklisted"] is False
    assert rp.is_rig_blacklisted("rigGood", tenant_id="t-auto2") is False


def test_list_route_carries_reco_trend_and_export(rclient, monkeypatch):
    """GET /api/rentals includes recommendations + market_trend + auto list,
    and /api/rentals/export returns a CSV ledger."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=50, tenant_id="": {
            "success": True,
            "needs_auth": False,
            "rentals": (
                [rp._normalize_rental(_mrr_rental())]
                if (rtype == "renter" and not history)
                else []
            ),
            "total": 1,
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False, "contracts": []},
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "get_rig_blacklist", lambda tenant_id="": []
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "get_auto_blacklist", lambda tenant_id="": ["376882"]
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "ingest_rentals", lambda *a, **k: True
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "evaluate_rental_pl_alerts", lambda *a, **k: []
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "build_rental_recommendations",
        lambda tenant_id="": {
            "top": [
                {
                    "rig_id": "376882",
                    "name": "A02 165TH",
                    "grade": "A",
                    "score": 96.0,
                    "samples": 4,
                }
            ],
            "avoid_count": 0,
            "tracked": 1,
            "market": {"available": True, "price_sats_per_thh": 500.0},
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_market_trend",
        lambda days=30: {
            "points": [{"day": "2026-07-22", "sats_per_thh": 500.0}],
            "summary": {
                "days": 1,
                "avg_sats_per_thh": 500.0,
                "current_sats_per_thh": 500.0,
                "vs_avg_pct": 0.0,
            },
        },
    )

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
    contracts = [
        {
            "id": "B1",
            "status": "FINISHED",
            "ended_at": "2026-08-01T00:00:00Z",
            "amount_sat": 50000000,
            "speed_limit_ph": 100.0,
        }
    ]
    assert rp.evaluate_rental_pl_alerts([], contracts, tenant_id="t6", now=now) == []


def test_detail_route_braiins_has_stability_and_pl(rclient, monkeypatch):
    """POST /api/rentals/detail (braiins) surfaces the speed-series STABILITY
    grade + the P/L economics."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_braiins_contract_detail",
        lambda cid, contract=None, tenant_id="": {
            "success": True,
            "detail": {"id": cid, "perf": {"percent": 100.0, "delivered_thh": 100.0}},
            "graph": {"points": []},
            "stability": {
                "cv_pct": 2.0,
                "mean_ph": 100.0,
                "grade": "STABLE",
                "min_ph": 99.0,
                "max_ph": 101.0,
                "label": "STABLE",
            },
            "pl": {"available": False},
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_market_reference", lambda: {"available": False}
    )
    resp = rclient.post(
        "/api/rentals/detail",
        json={"provider": "braiins", "id": "B1", "contract": {"id": "B1"}},
    )
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
        _app_module._rental_perf,
        "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=50, tenant_id="": {
            "success": True,
            "needs_auth": False,
            "rentals": [],
            "total": 0,
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False, "contracts": []},
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "get_rig_blacklist", lambda tenant_id="": []
    )
    monkeypatch.setattr(
        _app_module._rental_perf, "ingest_rentals", lambda *a, **k: True
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "evaluate_rental_pl_alerts",
        lambda *a, **k: [
            {
                "severity": "WARN",
                "category": "rental_pl",
                "message": "Rental #1 fechou com prejuízo",
                "rental_id": "1",
                "provider": "mrr",
            }
        ],
    )
    fired = {"webhook": [], "push": []}
    monkeypatch.setattr(
        _up, "_fire_webhook_async", lambda kw: fired["webhook"].append(kw)
    )
    monkeypatch.setattr(
        _up, "_fire_push_async", lambda t, s, c, m: fired["push"].append((t, s, c, m))
    )
    # No webhook configured (conftest default) → only push fires.
    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    assert len(fired["push"]) == 1
    assert fired["push"][0][1] == "WARN" and fired["push"][0][2] == "rental_pl"
    assert fired["webhook"] == []

    # Tenant WITH a webhook URL → webhook fired too (tenant-aware settings).
    import services.settings as _settings_mod

    monkeypatch.setattr(
        _settings_mod,
        "load_settings",
        lambda tenant_id="": {
            "webhook_url": "https://discord.com/api/webhooks/x",
            "webhook_min_severity": "WARN",
        },
    )
    fired["webhook"].clear()
    fired["push"].clear()
    # ?refresh=1 bypasses the TTL cache so the dispatchers run again
    # (a plain second GET within 20s would be served from cache).
    resp = rclient.get("/api/rentals?refresh=1")
    assert resp.status_code == 200
    assert len(fired["webhook"]) == 1
    assert fired["webhook"][0]["url"] == "https://discord.com/api/webhooks/x"
    assert fired["webhook"][0]["category"] == "rental_pl"
    assert len(fired["push"]) == 1


# ── Braiins spot EXECUTION: quote, balance, bid (real money) ─────────────────


def _fake_braiins_key(monkeypatch, key="owner-token"):
    """Point the tenant key resolver at a known token. _braiins_key calls the
    binding IMPORTED into rp (not _tools'), so patch that one."""
    monkeypatch.setattr(
        rp, "braiins_credentials", lambda tenant_id="": {"api_key": key}
    )


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
        speed_limit_ph=1.0,
        amount_sat=500000,
        price_sat=123456,
        upstream_url="stratum+tcp://pool.example:3333",
        upstream_identity="user.worker",
        memo="bat1",
        cl_order_id="c65-abc123",
        tenant_id="",
    )
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
    monkeypatch.setattr(
        rp.requests, "post", lambda *a, **k: FakeResponse(ok=False, status_code=401)
    )
    out = rp.create_braiins_bid(
        1.0, 500000, 123456, "stratum+tcp://h:3333", tenant_id=""
    )
    assert out["success"] is False
    assert out["needs_auth"] is True


def test_create_braiins_bid_clamps_out_of_band(monkeypatch):
    """Sanity clamps run BEFORE the wire: a unit bug (e.g. TH mistaken for
    PH) must never reach the API."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(rp, "braiins_price_unit", lambda tenant_id="": "sats/PH/day")
    called = []
    monkeypatch.setattr(
        rp.requests, "post", lambda *a, **k: called.append(1) or FakeResponse()
    )
    # speed out of band (0.0005 PH = 0.5 TH < 1 TH floor; 5000 PH = 5 EH cap)
    assert (
        rp.create_braiins_bid(0.0005, 500000, 123456, "stratum+tcp://h:3333")["success"]
        is False
    )
    assert (
        rp.create_braiins_bid(5000.0, 500000, 123456, "stratum+tcp://h:3333")["success"]
        is False
    )
    # amount out of band
    assert (
        rp.create_braiins_bid(1.0, 100, 123456, "stratum+tcp://h:3333")["success"]
        is False
    )
    assert (
        rp.create_braiins_bid(1.0, 200_000_000, 123456, "stratum+tcp://h:3333")[
            "success"
        ]
        is False
    )
    # price out of band (a PH/day unit bug lands far outside 1e4..1e9)
    assert (
        rp.create_braiins_bid(1.0, 500000, 5, "stratum+tcp://h:3333")["success"]
        is False
    )
    # non-stratum upstream rejected
    assert (
        rp.create_braiins_bid(1.0, 500000, 123456, "https://pool.example")["success"]
        is False
    )
    assert called == []  # NOTHING reached the API


def test_create_braiins_bid_missing_key(monkeypatch):
    """No key anywhere → explicit needs_auth, no HTTP at all."""
    _fake_braiins_key(monkeypatch, key="")
    called = []
    monkeypatch.setattr(
        rp.requests, "post", lambda *a, **k: called.append(1) or FakeResponse()
    )
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
        rp.requests,
        "get",
        lambda *a, **k: FakeResponse(
            payload={
                "items": [
                    {"balance_type": "total", "amount": "1000000"},
                    {"balance_type": "available", "amount": "800000"},
                    {"balance_type": "blocked", "amount": "200000"},
                ]
            }
        ),
    )
    out = rp.fetch_braiins_balance()
    assert out["available"] is True
    assert out["total_sat"] == 1000000
    assert out["available_sat"] == 800000
    assert out["blocked_sat"] == 200000


def test_fetch_braiins_balance_flat_envelope(monkeypatch):
    """Flat dict envelope {total, available, blocked} also parses."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(
        rp.requests,
        "get",
        lambda *a, **k: FakeResponse(
            payload={"total": "5000000", "available": "4900000"}
        ),
    )
    out = rp.fetch_braiins_balance()
    assert out["total_sat"] == 5000000
    assert out["available_sat"] == 4900000


def test_fetch_braiins_balance_401_surfaces(monkeypatch):
    """401 from a CONFIGURED key → needs_auth error (never a zero balance)."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(
        rp.requests, "get", lambda *a, **k: FakeResponse(ok=False, status_code=401)
    )
    out = rp.fetch_braiins_balance()
    assert out["available"] is False
    assert out["needs_auth"] is True
    assert "401" in out["error"]


def test_braiins_quote_converts_units_and_includes_balance(monkeypatch):
    """quote: orderbook BTC/TH/day → sats/TH·h + raw sats/PH/day, with the
    tenant's balance attached for the buy modal prefill."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(
        _tools,
        "get_braiins_orderbook",
        lambda: {
            "price_btc_per_th_day": 0.0001230,
            "best_order_hr_ph": 500.0,
            "price_raw_unit": "sats/PH/day",
        },
    )
    monkeypatch.setattr(
        rp,
        "fetch_braiins_balance",
        lambda tenant_id="": {"available": True, "available_sat": 800000},
    )
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

    def fake_create(
        speed_limit_ph=None,
        amount_sat=None,
        price_sat=None,
        upstream_url="",
        upstream_identity="",
        memo="",
        cl_order_id="",
        tenant_id="",
    ):
        sent.update(locals())
        return {"success": True, "bid": {"id": "BID-ROUTE", "raw": {}}}

    monkeypatch.setattr(_app_module._rental_perf, "create_braiins_bid", fake_create)

    # Missing amount/price → 400 before any provider call.
    resp = rclient.post(
        "/api/rentals/braiins/bid",
        json={"speed_limit_th": 1000, "upstream_url": "stratum+tcp://h:3333"},
    )
    assert resp.status_code == 400

    # Zero hashrate → 400.
    resp = rclient.post(
        "/api/rentals/braiins/bid",
        json={
            "speed_limit_th": 0,
            "amount_sat": 500000,
            "price_sat": 123456,
            "upstream_url": "stratum+tcp://h:3333",
        },
    )
    assert resp.status_code == 400

    # Valid: 1000 TH → 1.0 PH on the wire; cl_order_id passed through.
    resp = rclient.post(
        "/api/rentals/braiins/bid",
        json={
            "speed_limit_th": 1000,
            "amount_sat": 500000,
            "price_sat": 123456,
            "upstream_url": "stratum+tcp://h:3333",
            "upstream_identity": "u.w",
            "memo": "bat",
            "cl_order_id": "c65-x",
        },
    )
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
        _app_module._rental_perf,
        "create_braiins_bid",
        lambda **k: {
            "success": False,
            "error": "speed_limit must be 0.001-1000.0 PH/s",
        },
    )
    resp = rclient.post(
        "/api/rentals/braiins/bid",
        json={
            "speed_limit_th": 5_000_000,
            "amount_sat": 500000,
            "price_sat": 123456,
            "upstream_url": "stratum+tcp://h:3333",
        },
    )
    assert resp.status_code == 400
    assert "speed_limit" in resp.get_json()["error"]


def test_quote_and_balance_routes(rclient, monkeypatch):
    """GET quote/balance routes surface the tenant data (mocked at module)."""
    _fake_braiins_key(monkeypatch)
    monkeypatch.setattr(
        _tools,
        "get_braiins_orderbook",
        lambda: {"price_btc_per_th_day": 0.0001230, "price_raw_unit": "sats/PH/day"},
    )
    monkeypatch.setattr(
        rp,
        "fetch_braiins_balance",
        lambda tenant_id="": {"available": True, "available_sat": 800000},
    )
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
    monkeypatch.setattr(
        rp.requests, "get", lambda *a, **k: FakeResponse(ok=False, status_code=503)
    )
    assert rp.braiins_price_unit() == "sats/PH/day"
    monkeypatch.setattr(
        rp.requests,
        "get",
        lambda *a, **k: FakeResponse(payload={"price_unit": "sats/TH/h"}),
    )
    assert rp.braiins_price_unit() == "sats/TH/h"


# ── Portfolio TIME SERIES: spent + estimated P/L per week/month ─────────────


def _series_row(rid, start, paid_sats, delivered_thh=100.0, tenant="t1"):
    return {
        "provider": "mrr",
        "rental_id": rid,
        "rig_id": "rig1",
        "rig_name": "Rig 1",
        "start": start,
        "end": None,
        "percent": 96.0,
        "avg_th": 100.0,
        "advertised_th": 100.0,
        "cost_sats_per_thh": None,
        "length_hours": 1.0,
        "delivered_thh": delivered_thh,
        "paid_sats": paid_sats,
    }


def test_portfolio_series_buckets_week_with_tenant_isolation(tmp_path, monkeypatch):
    """compute_portfolio_series aggregates spent + estimated P/L per ISO week
    from the LOCAL table, scoped to the tenant (never cross-tenant)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series.sqlite"))
    monkeypatch.setattr(
        rp,
        "compute_rental_pl",
        lambda delivered, paid, **k: {"pl_sats": -100.0, "pl_pct": -50.0},
    )
    rows = [
        _series_row("1", "2026-07-20 10:00:00 UTC", 5000),  # W30
        _series_row("2", "2026-07-21 10:00:00 UTC", 3000),  # W30
        _series_row("3", "2026-07-28 10:00:00 UTC", 8000),  # W31
        _series_row("4", "2026-07-29 10:00:00 UTC", 2000),  # W31 (other tenant? no)
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    assert (
        rp.save_rental_history(
            [_series_row("9", "2026-07-29 10:00:00 UTC", 999999)], tenant_id="t2"
        )
        is True
    )

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
    monkeypatch.setattr(
        rp, "compute_rental_pl", lambda delivered, paid, **k: {"pl_sats": -50.0}
    )
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
    monkeypatch.setattr(
        rp,
        "compute_rental_pl",
        lambda delivered, paid, **k: {"pl_sats": None, "pl_pct": None},
    )
    assert (
        rp.save_rental_history(
            [_series_row("1", "2026-07-20 10:00:00 UTC", 5000)], tenant_id="t1"
        )
        is True
    )
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
    monkeypatch.setattr(
        rp,
        "compute_rental_pl",
        lambda delivered, paid, **k: (
            {"pl_sats": -100.0} if delivered else {"pl_sats": None}
        ),
    )
    rows = [
        _series_row("1", "2026-07-20 10:00:00 UTC", 5000, delivered_thh=100.0),
        _series_row(
            "2", "2026-07-27 10:00:00 UTC", 3000, delivered_thh=None
        ),  # unknown
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    s = rp.compute_portfolio_series(tenant_id="t1", bucket="week")
    assert s["points"][0]["pl_sats"] == -100.0
    assert s["points"][0]["cum_pl_sats"] == -100.0
    assert s["points"][1]["pl_sats"] is None
    assert s["points"][1]["cum_pl_sats"] is None  # total through W31 is unknown


# ── Issue #146 (21-C): self-mining EV merged into the series ──────────────


def _ts_utc(y, m, d, hh=12):
    import datetime as _dt

    return _dt.datetime(y, m, d, hh, tzinfo=_dt.timezone.utc).timestamp()


def test_portfolio_series_own_ev_included_full_week(tmp_path, monkeypatch):
    """Issue #146 (21-C): own_ev_daily_sats merges the self-mining EV per
    bucket — a fully-past ISO week carries 7 days of EV, the consolidated
    total = rentals P/L + own EV, and the ESTIMATE labels are honest."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series_ev.sqlite"))
    monkeypatch.setattr(
        rp, "compute_rental_pl", lambda delivered, paid, **k: {"pl_sats": -200.0}
    )
    assert (
        rp.save_rental_history(
            [_series_row("1", "2026-07-20 10:00:00 UTC", 5000)], tenant_id="t1"
        )
        is True
    )
    s = rp.compute_portfolio_series(
        tenant_id="t1", bucket="week", own_ev_daily_sats=100, now_ts=_ts_utc(2026, 8, 1)
    )
    p = s["points"][0]
    assert p["label"] == "2026-W30"
    assert p["own_ev_sats"] == 700  # 7 days × 100 sats/day
    assert p["pl_sats"] == -200.0
    assert p["total_pl_sats"] == 500.0  # -200 rentals + 700 own EV
    assert p["cum_total_sats"] == 500.0
    assert s["own_ev_estimate"] is True
    assert s["own_ev_daily_sats"] == 100
    assert s["totals"]["own_ev_sats"] == 700
    assert s["totals"]["total_pl_sats"] == 500.0
    assert s["estimate"] is True


def test_portfolio_series_own_ev_month_full_days(tmp_path, monkeypatch):
    """Own EV in a calendar-month bucket = daily EV × the month's days
    (February 2026 → 28 days)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series_ev2.sqlite"))
    monkeypatch.setattr(
        rp, "compute_rental_pl", lambda delivered, paid, **k: {"pl_sats": -50.0}
    )
    assert (
        rp.save_rental_history(
            [_series_row("1", "2026-02-10 10:00:00 UTC", 3000)], tenant_id="t1"
        )
        is True
    )
    s = rp.compute_portfolio_series(
        tenant_id="t1",
        bucket="month",
        own_ev_daily_sats=100,
        now_ts=_ts_utc(2026, 3, 1),
    )
    p = s["points"][0]
    assert p["label"] == "2026-02"
    assert p["own_ev_sats"] == 2800  # 28 days × 100
    assert p["total_pl_sats"] == 2750.0  # -50 + 2800


def test_portfolio_series_own_ev_current_partial_week_capped(tmp_path, monkeypatch):
    """The CURRENT partial bucket is capped at the days elapsed so far
    (mid-week → 3 days), never a fabricated full week."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series_ev3.sqlite"))
    monkeypatch.setattr(
        rp, "compute_rental_pl", lambda delivered, paid, **k: {"pl_sats": 0.0}
    )
    # 2026-07-20 is a Monday (W30); 'now' = Wednesday 2026-07-22.
    assert (
        rp.save_rental_history(
            [_series_row("1", "2026-07-21 10:00:00 UTC", 2000)], tenant_id="t1"
        )
        is True
    )
    s = rp.compute_portfolio_series(
        tenant_id="t1",
        bucket="week",
        own_ev_daily_sats=100,
        now_ts=_ts_utc(2026, 7, 22),
    )
    assert s["points"][0]["own_ev_sats"] == 300  # Mon + Tue + Wed = 3 days


def test_portfolio_series_own_ev_absent_is_backward_compatible(tmp_path, monkeypatch):
    """Without own_ev_daily_sats the payload keeps the legacy shape: EV
    fields exist but are None (honest '—'), totals never fabricate EV."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series_ev4.sqlite"))
    monkeypatch.setattr(
        rp, "compute_rental_pl", lambda delivered, paid, **k: {"pl_sats": -100.0}
    )
    assert (
        rp.save_rental_history(
            [_series_row("1", "2026-07-20 10:00:00 UTC", 5000)], tenant_id="t1"
        )
        is True
    )
    s = rp.compute_portfolio_series(tenant_id="t1", bucket="week")
    p = s["points"][0]
    assert p["own_ev_sats"] is None
    assert p["total_pl_sats"] is None
    assert p["cum_total_sats"] is None
    assert s["own_ev_estimate"] is False
    assert s["own_ev_daily_sats"] is None
    assert s["totals"]["own_ev_sats"] is None
    assert s["totals"]["total_pl_sats"] is None
    # Legacy fields untouched.
    assert p["pl_sats"] == -100.0
    assert p["cum_pl_sats"] == -100.0


def test_series_route_returns_bucket(rclient, monkeypatch):
    """GET /api/rentals/series?bucket=month returns the server aggregation."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "compute_portfolio_series",
        lambda tenant_id="", bucket="week", **k: {
            "bucket": bucket,
            "estimate": True,
            "points": [
                {
                    "label": "2026-07",
                    "spent_sats": 1000,
                    "pl_sats": -50.0,
                    "cum_pl_sats": -50.0,
                    "delivered_thh": 100.0,
                    "rentals": 1,
                }
            ],
            "totals": {"spent_sats": 1000, "pl_sats": -50.0, "rentals": 1},
        },
    )
    resp = rclient.get("/api/rentals/series?bucket=month")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["bucket"] == "month"
    assert data["points"][0]["spent_sats"] == 1000
    assert data["totals"]["rentals"] == 1


# ── Click-first analytics (rankings / heatmap / expiring / drill-down) ─────


def test_provider_rankings_averages_and_order():
    """compute_provider_rankings aggregates delivery/cost/P·L per provider and
    sorts by avg delivery desc; providers without data are never fabricated."""
    # The ranking consumes the NORMALIZED list shape (flat fields that
    # fetch_mrr_rentals produces), not the raw API envelope.
    h1 = {
        "id": "1",
        "hashrate_percent": 99.0,
        "price_paid_btc": 0.00001,
        "hashrate_average_th": 100.0,
        "length_hours": 1.0,
    }
    h2 = {
        "id": "2",
        "hashrate_percent": 95.0,
        "price_paid_btc": 0.00002,
        "hashrate_average_th": 100.0,
        "length_hours": 2.0,
    }
    contracts = [{"id": "c1", "amount_sat": 15000}]
    rows = rp.compute_provider_rankings([h1], [h2], [], contracts)
    assert len(rows) == 2
    mrr = next(r for r in rows if r["provider"] == "mrr")
    braiins = next(r for r in rows if r["provider"] == "braiins")
    assert mrr["avg_delivery_pct"] == 97.0  # (99+95)/2
    assert mrr["rentals"] == 2
    assert braiins["spend_sats"] == 15000
    # No fabricated rows when a provider has no data.
    rows2 = rp.compute_provider_rankings([], [], [], [])
    assert rows2 == []


def test_rig_heatmap_requires_two_samples_and_scopes_tenant(tmp_path, monkeypatch):
    """compute_rig_heatmap builds rig-name cells but skips rigs with <2
    samples (one-off noise) and never leaks another tenant's rows."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "heatmap.sqlite"))
    rows = [
        _reco_hist_row("1", "rigA", "Rig A", 96, 500, "2026-07-20"),
        _reco_hist_row("2", "rigA", "Rig A", 98, 510, "2026-07-21"),
        _reco_hist_row("3", "rigB", "Rig B", 80, 700, "2026-07-20"),  # 1 sample only
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    assert (
        rp.save_rental_history(
            [_reco_hist_row("9", "rigC", "Rig C", 100, 400, "2026-07-22")],
            tenant_id="t2",
        )
        is True
    )
    # Rig B with cost=None carries only a delivery sample (1) — the cell
    # threshold is "≥2 measured samples" (delivery + cost counts), so a
    # single measurement is noise and must be excluded.
    rows[2]["cost_sats_per_thh"] = None
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    cells = rp.compute_rig_heatmap([], [], tenant_id="t1")
    names = [c["rig"] for c in cells]
    assert "Rig A" in names
    assert "Rig B" not in names  # <2 samples
    assert "Rig C" not in names  # t2's rig
    a = next(c for c in cells if c["rig"] == "Rig A")
    assert a["avg_delivery_pct"] == 97.0
    assert a["samples"] == 2


def test_expiring_rentals_filters_window_and_sorts():
    """compute_expiring_rentals keeps only active rentals ending within the
    window, sorted by time left (soonest first)."""
    now = time.time()
    soon = _mrr_rental(id="1")
    soon["end_unix"] = str(int(now + 3600))  # 1h left
    later = _mrr_rental(id="2")
    later["end_unix"] = str(int(now + 48 * 3600))  # 48h left
    far = _mrr_rental(id="3")
    far["end_unix"] = str(int(now + 200 * 3600))  # outside window
    past = _mrr_rental(id="4")
    past["end_unix"] = str(int(now - 3600))  # already ended
    out = rp.compute_expiring_rentals([far, soon, later, past], hours=72.0)
    assert [r["id"] for r in out] == ["1", "2"]
    assert out[0]["ends_in_hours"] == 1.0


def test_compute_backtest_honest_without_market(monkeypatch):
    """compute_backtest computes cost + expected yield + P/L from the live
    market; when yield is unknown only the cost side is returned (no
    fabricated P/L)."""
    mkt = {"available": True, "price_sats_per_thh": 12.5}
    monkeypatch.setattr(rp, "compute_expected_yield_sats_per_thh", lambda: 15.0)
    bt = rp.compute_backtest(500, 24, market=mkt)
    assert bt["thh"] == 12000
    assert bt["cost_sats"] == 12.5 * 12000
    assert bt["expected_yield_sats"] == 15.0 * 12000
    assert bt["pl_sats"] == (15.0 - 12.5) * 12000
    assert bt["yield_known"] is True
    monkeypatch.setattr(rp, "compute_expected_yield_sats_per_thh", lambda: None)
    bt2 = rp.compute_backtest(500, 24, market=mkt)
    assert bt2["expected_yield_sats"] is None
    assert bt2["pl_sats"] is None  # never fabricate P/L
    assert bt2["yield_known"] is False
    # No market at all → cost side also unknown.
    bt3 = rp.compute_backtest(500, 24, market={"available": False})
    assert bt3["cost_sats"] is None


def test_series_carries_rental_ids_and_drill_down_returns_rows(tmp_path, monkeypatch):
    """The portfolio series ships rental_ids per bucket so the chart can
    drill down; series_bucket_rentals returns the exact local rows behind a
    label, tenant-scoped."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "drill.sqlite"))
    monkeypatch.setattr(
        rp, "compute_rental_pl", lambda delivered, paid, **k: {"pl_sats": -100.0}
    )
    rows = [
        _series_row("1", "2026-07-20 10:00:00 UTC", 5000),
        _series_row("2", "2026-07-21 10:00:00 UTC", 3000),
        _series_row("3", "2026-07-28 10:00:00 UTC", 8000),
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    assert (
        rp.save_rental_history(
            [_series_row("9", "2026-07-28 10:00:00 UTC", 9000)], tenant_id="t2"
        )
        is True
    )
    s = rp.compute_portfolio_series(tenant_id="t1", bucket="week")
    w30 = next(p for p in s["points"] if p["label"] == "2026-W30")
    assert sorted(w30["rental_ids"]) == ["1", "2"]
    w31 = next(p for p in s["points"] if p["label"] == "2026-W31")
    assert w31["rental_ids"] == ["3"]
    rows30 = rp.series_bucket_rentals(tenant_id="t1", bucket="week", label="2026-W30")
    assert [r["rental_id"] for r in rows30] == ["1", "2"]
    assert all(r["provider"] == "mrr" and r["rig_name"] for r in rows30)
    # t2's row never leaks into t1's drill-down; unknown label → empty.
    rows_nope = rp.series_bucket_rentals(
        tenant_id="t1", bucket="week", label="2099-W01"
    )
    assert rows_nope == []
    assert (
        rp.series_bucket_rentals(tenant_id="t1", bucket="week", label="2026-W31")[0][
            "rental_id"
        ]
        == "3"
    )


def test_drill_route_requires_label_and_scopes(rclient, monkeypatch):
    """GET /api/rentals/series/rentals validates label and delegates to the
    tenant-scoped drill-down function."""
    resp = rclient.get("/api/rentals/series/rentals")
    assert resp.status_code == 400
    monkeypatch.setattr(
        _app_module._rental_perf,
        "series_bucket_rentals",
        lambda tenant_id="", bucket="week", label="": [
            {"provider": "mrr", "rental_id": "1"}
        ],
    )
    resp2 = rclient.get("/api/rentals/series/rentals?bucket=week&label=2026-W30")
    assert resp2.status_code == 200
    data = resp2.get_json()
    assert data["label"] == "2026-W30"
    assert data["rentals"][0]["rental_id"] == "1"


def test_rig_route_returns_track_record(rclient, monkeypatch):
    """GET /api/rentals/rig returns the analyze_rig shape (trust grade,
    summary, blacklist) for a reco-card click."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "rig_track_record",
        lambda rig_id=None, rig_name="", tenant_id="": {
            "history": [],
            "trust": {"grade": "A", "score": 95},
            "blacklisted": False,
            "auto_blacklisted": False,
            "summary": {
                "rentals": 0,
                "avg_pct": None,
                "cost_avg_sats_thh": None,
                "trend_pct": None,
            },
        },
    )
    resp = rclient.get("/api/rentals/rig?rig_id=376882")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["trust"]["grade"] == "A"
    resp2 = rclient.get("/api/rentals/rig")
    assert resp2.status_code == 400


def test_backtest_route_validation_and_result(rclient, monkeypatch):
    """GET /api/rentals/backtest validates inputs and returns the honest
    cost/yield/P·L summary."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "compute_backtest",
        lambda th, hours, market=None: {
            "thh": 12000,
            "cost_sats": 150000,
            "expected_yield_sats": 180000,
            "pl_sats": 30000,
            "yield_known": True,
            "market_sats_per_thh": 12.5,
            "available": True,
        },
    )
    assert rclient.get("/api/rentals/backtest?th=0&hours=24").status_code == 400
    assert rclient.get("/api/rentals/backtest?th=500&hours=9999").status_code == 400
    resp = rclient.get("/api/rentals/backtest?th=500&hours=24")
    assert resp.status_code == 200
    assert resp.get_json()["pl_sats"] == 30000


# ── Worst-rig leaderboard + concentration risk (CFO risk view) ──────────────


def _worst_row(
    rid, rig_name, start, percent, paid_sats=1000, delivered_thh=10.0, tenant="t1"
):
    return {
        "provider": "mrr",
        "rental_id": f"r-{rid}-{start}",
        "rig_id": str(rid),
        "rig_name": rig_name,
        "start": start,
        "end": None,
        "percent": percent,
        "avg_th": 100.0,
        "advertised_th": 100.0,
        "cost_sats_per_thh": None,
        "length_hours": 1.0,
        "delivered_thh": delivered_thh,
        "paid_sats": paid_sats,
    }


def test_worst_rigs_ewma_ordering_and_min_samples(tmp_path, monkeypatch):
    """compute_worst_rigs ranks the worst rigs first, EWMA weights recent
    rentals, and a rig with a single sample is never ranked (noise)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "worst.sqlite"))
    # Rig A: was great (99%) then collapsed to 40% recently → must top.
    # Rig B: consistently mediocre (80, 82, 79).
    # Rig C: one terrible rental only → filtered by the ≥2 samples gate.
    rows = [
        _worst_row("A", "Rig A", "2026-06-01 10:00:00 UTC", 99.0),
        _worst_row("A", "Rig A", "2026-06-02 10:00:00 UTC", 98.0),
        _worst_row("A", "Rig A", "2026-06-03 10:00:00 UTC", 40.0),
        _worst_row("B", "Rig B", "2026-06-01 10:00:00 UTC", 80.0),
        _worst_row("B", "Rig B", "2026-06-02 10:00:00 UTC", 82.0),
        _worst_row("B", "Rig B", "2026-06-03 10:00:00 UTC", 79.0),
        _worst_row("C", "Rig C", "2026-06-01 10:00:00 UTC", 30.0),
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True

    d = rp.compute_worst_rigs(tenant_id="t1")
    assert d["min_samples"] == 2
    assert d["count"] == 2  # rig C excluded (1 sample)
    ids = [w["rig_id"] for w in d["worst"]]
    assert ids[0] == "A"  # collapsed recently → worst
    assert ids[1] == "B"
    a = d["worst"][0]
    # EWMA(99, 98, 40) with α=0.5: 0.5*40 + 0.5*(0.5*98+0.5*99) = 20 + 49.25 = 69.25
    assert abs(a["ewma_delivery_pct"] - 69.25) < 0.1
    assert a["worst_pct"] == 40.0
    assert a["fail_rate_pct"] == 33.3  # 1 of 3 below 90%
    # The trust grade rides along (same engine as the rig modal): rig A's
    # median of [40,98,99] = 98 → B/C band — the DANGER score tells the
    # 'recent collapse' story while the grade reflects the overall record.
    assert d["worst"][0]["grade"] in ("A", "B", "C", "D", "F")
    # EWMA far below the plain average (79) — the recent collapse dominates.
    assert a["ewma_delivery_pct"] < a["avg_delivery_pct"]
    assert a["danger_score"] > d["worst"][1]["danger_score"]
    # A rig that collapsed to 40% must land at least in the WARN band (≥45).
    assert a["danger_score"] >= 45.0


def test_worst_rigs_tenant_isolation_and_blacklist(tmp_path, monkeypatch):
    """worst-rig ranking is tenant-scoped and flags manual/auto blacklists."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "worst_t.sqlite"))
    # Each tenant saves ITS OWN rows only (save_rental_history stamps the
    # passed tenant_id onto every row — a shared list would leak both rigs
    # into both tenants and defeat the isolation check).
    assert (
        rp.save_rental_history(
            [
                _worst_row("X", "Rig X", "2026-06-01 10:00:00 UTC", 55.0),
                _worst_row("X", "Rig X", "2026-06-02 10:00:00 UTC", 58.0),
            ],
            tenant_id="t1",
        )
        is True
    )
    assert (
        rp.save_rental_history(
            [
                _worst_row("Y", "Rig Y", "2026-06-01 10:00:00 UTC", 99.0),
                _worst_row("Y", "Rig Y", "2026-06-02 10:00:00 UTC", 97.0),
            ],
            tenant_id="t2",
        )
        is True
    )
    # t1's view must not include t2's good rig Y.
    d1 = rp.compute_worst_rigs(tenant_id="t1")
    assert [w["rig_id"] for w in d1["worst"]] == ["X"]

    # Blacklist flag: rig X is a bad performer → manual blacklist it.
    assert rp.add_rig_to_blacklist("X", tenant_id="t1") is True
    d1b = rp.compute_worst_rigs(tenant_id="t1")
    assert d1b["worst"][0]["blacklisted"] is True
    assert d1b["worst"][0]["auto_blacklisted"] is False
    # t2 (with its own history) still sees its rig unblacklisted.
    d2 = rp.compute_worst_rigs(tenant_id="t2")
    assert [w["rig_id"] for w in d2["worst"]] == ["Y"]
    assert d2["worst"][0]["blacklisted"] is False


def test_worst_rigs_empty_and_never_raises(tmp_path, monkeypatch):
    """Empty/local-table-missing DB → clean empty result, never an exception."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "worst_e.sqlite"))
    d = rp.compute_worst_rigs(tenant_id="t1")
    assert d["worst"] == [] and d["count"] == 0


def test_concentration_risk_provider_split_hhi_and_top_rig():
    """compute_concentration_risk derives provider/rig spend shares + HHI."""
    active = [
        {"price_paid_btc": 0.0001, "rig": {"id": "1", "name": "Rig 1"}},  # 10k sats
        {"price_paid_btc": 0.0003, "rig": {"id": "2", "name": "Rig 2"}},  # 30k sats
    ]
    contracts = [{"amount_sat": 60000}]  # Braiins: 60k sats
    c = rp.compute_concentration_risk(active, [], [], contracts)
    assert c["available"] is True
    assert c["total_spend_sats"] == 100000
    provs = {p["provider"]: p for p in c["providers"]}
    assert provs["mrr"]["spend_sats"] == 40000 and provs["mrr"]["share_pct"] == 40.0
    assert (
        provs["braiins"]["spend_sats"] == 60000
        and provs["braiins"]["share_pct"] == 60.0
    )
    # HHI = 40² + 60² = 5200 → 'alta concentração' band.
    assert c["hhi"] == 5200.0
    assert c["top_provider"]["provider"] == "braiins"
    assert c["top_rig"]["rig_id"] == "2"
    assert c["top_rig"]["share_pct"] == 30.0


def test_concentration_risk_honest_empty():
    """No measurable spend → available False (honest '—', never a fake 0)."""
    c = rp.compute_concentration_risk([], [], [], [])
    assert c["available"] is False
    # A zero-paid rental is not spend either.
    c2 = rp.compute_concentration_risk(
        [{"price_paid_btc": 0.0, "rig": {"id": "1"}}], [], [], []
    )
    assert c2["available"] is False


def test_list_route_carries_worst_and_concentration(rclient, monkeypatch):
    """The /api/rentals payload ships worst_rigs + concentration (risk view)."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "compute_worst_rigs",
        lambda tenant_id="": {
            "worst": [{"rig_id": "1", "danger_score": 80.0}],
            "count": 1,
            "min_samples": 2,
        },
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "compute_concentration_risk",
        lambda *a, **k: {"available": True, "hhi": 5200.0},
    )
    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["worst_rigs"]["worst"][0]["rig_id"] == "1"
    assert data["concentration"]["hhi"] == 5200.0


# ── Difficulty forecast + risk alerts (market timing + risk view) ───────────


def _risk_settings():
    return {
        "rental_risk_alerts": "1",
        "rental_risk_danger": "40",
        "rental_risk_top_n": "5",
        "rental_risk_conc_pct": "55",
    }


def _seed_snapshots(heights):
    """Create the snapshots table and insert (ts, height) rows the forecast
    reads for the block-cadence measurement."""
    from services.db import get_db

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS snapshots (ts INTEGER, network_height INTEGER)"
    )
    for i, h in enumerate(heights):
        c.execute(
            "INSERT OR REPLACE INTO snapshots(ts,network_height) VALUES(?,?)",
            (1_800_000_000 + i * 500, h),
        )  # 500s between polls, +1 height
    conn.commit()
    conn.close()


def test_difficulty_forecast_projects_from_block_cadence(tmp_path, monkeypatch):
    """Faster-than-10min blocks (500s cadence) → difficulty projected UP;
    slower blocks → DOWN. Both derived from the LOCAL snapshots table."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "fc.sqlite"))
    # +1 height every 500s → avg block time 500s (faster than 600 target).
    _seed_snapshots([890000 + i for i in range(20)])
    import services.state as _state

    monkeypatch.setattr(
        _state,
        "latest_snapshot",
        {"network": {"difficulty": 90e12, "height": 890050, "hashrate": 1e20}},
    )
    f = rp.compute_difficulty_forecast()
    assert f["available"] is True
    assert 450 <= f["avg_block_time_s"] <= 560
    assert f["direction"] == "up"
    assert f["projected_change_pct"] > 5.0
    assert 0 < f["blocks_remaining"] <= 2016
    assert f["hours_to_adjustment"] > 0
    assert "difficulty" in f["verdict"].lower()


def test_difficulty_forecast_down_when_blocks_slower(tmp_path, monkeypatch):
    """Slower-than-10min blocks (700s cadence) → difficulty projected DOWN."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "fc2.sqlite"))
    from services.db import get_db

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS snapshots (ts INTEGER, network_height INTEGER)"
    )
    for i in range(20):
        c.execute(
            "INSERT OR REPLACE INTO snapshots(ts,network_height) VALUES(?,?)",
            (1_800_000_000 + i * 700, 900000 + i),
        )
    conn.commit()
    conn.close()
    import services.state as _state

    monkeypatch.setattr(
        _state,
        "latest_snapshot",
        {"network": {"difficulty": 90e12, "height": 900050, "hashrate": 1e20}},
    )
    f = rp.compute_difficulty_forecast()
    assert f["available"] is True
    assert f["direction"] == "down"
    assert f["projected_change_pct"] < -5.0


def test_difficulty_forecast_unavailable_cold_box(tmp_path, monkeypatch):
    """Cold box (no height/difficulty or no snapshots) → available False —
    never a fabricated projection."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "fc3.sqlite"))
    import services.state as _state

    monkeypatch.setattr(
        _state, "latest_snapshot", {"network": {"difficulty": None, "height": None}}
    )
    f = rp.compute_difficulty_forecast()
    assert f["available"] is False


def test_risk_alerts_worst_rig_fires_once_with_dedup(tmp_path, monkeypatch):
    """A rig in the top-N with danger ≥ threshold fires ONE alert per rig;
    the same rig never alerts again (persisted dedup)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "risk.sqlite"))
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _risk_settings())
    rows = [
        _worst_row("A", "Rig A", "2026-06-01 10:00:00 UTC", 55.0),
        _worst_row("A", "Rig A", "2026-06-02 10:00:00 UTC", 58.0),
        _worst_row("A", "Rig A", "2026-06-03 10:00:00 UTC", 52.0),
        _worst_row("B", "Rig B", "2026-06-01 10:00:00 UTC", 99.0),
        _worst_row("B", "Rig B", "2026-06-02 10:00:00 UTC", 97.0),
        _worst_row("B", "Rig B", "2026-06-03 10:00:00 UTC", 96.0),
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True

    a = rp.evaluate_risk_alerts(tenant_id="t1")
    assert len(a) == 1  # only rig A crosses the danger threshold
    assert a[0]["category"] == "rental_risk_rig"
    assert "PIORES" in a[0]["message"] or "piores" in a[0]["message"]
    assert a[0]["severity"] in ("CRIT", "WARN")

    # Dedup: same rig never alerts again.
    assert rp.evaluate_risk_alerts(tenant_id="t1") == []


def test_risk_alerts_disabled_when_setting_off(tmp_path, monkeypatch):
    """No setting (or '0') → no alerts, even with bad rigs present."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "risk2.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": {"rental_risk_alerts": "0"}
    )
    rows = [
        _worst_row("A", "Rig A", "2026-06-01 10:00:00 UTC", 40.0),
        _worst_row("A", "Rig A", "2026-06-02 10:00:00 UTC", 45.0),
        _worst_row("A", "Rig A", "2026-06-03 10:00:00 UTC", 42.0),
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    assert rp.evaluate_risk_alerts(tenant_id="t1") == []


def test_risk_alerts_concentration_crossing_fires_once(tmp_path, monkeypatch):
    """Top-provider share ≥ threshold fires a concentration alert once per
    provider crossing (deduped)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "risk3.sqlite"))
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _risk_settings())
    conc = {
        "available": True,
        "hhi": 7800.0,
        "top_provider": {"provider": "mrr", "label": "MRR", "share_pct": 88.0},
    }
    a = rp.evaluate_risk_alerts(tenant_id="t1", concentration=conc)
    assert len(a) == 1
    assert a[0]["category"] == "rental_risk_concentration"
    assert "88%" in a[0]["message"]
    assert rp.evaluate_risk_alerts(tenant_id="t1", concentration=conc) == []


def test_risk_alerts_tenant_isolation(tmp_path, monkeypatch):
    """Tenant t1's worst rig does NOT fire an alert for t2 (no data)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "risk4.sqlite"))
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _risk_settings())
    rows = [
        _worst_row("A", "Rig A", "2026-06-01 10:00:00 UTC", 55.0),
        _worst_row("A", "Rig A", "2026-06-02 10:00:00 UTC", 58.0),
        _worst_row("A", "Rig A", "2026-06-03 10:00:00 UTC", 52.0),
    ]
    assert rp.save_rental_history(rows, tenant_id="t1") is True
    assert len(rp.evaluate_risk_alerts(tenant_id="t1")) == 1
    # t2 has its own empty history → no alert, and t1's dedup is untouched.
    assert rp.evaluate_risk_alerts(tenant_id="t2") == []


def test_risk_alert_enabled_tenants_scan(tmp_path, monkeypatch):
    """risk_alert_enabled_tenants returns opted-in tenants (no credential
    gate — the worst-rig half is local)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "risk5.sqlite"))
    from services.db import get_db

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS tenant_settings (tenant_id TEXT, key TEXT, value TEXT, updated_ts INTEGER, PRIMARY KEY(tenant_id,key))"
    )
    c.execute(
        "INSERT OR REPLACE INTO tenant_settings VALUES ('t-on', 'rental_risk_alerts', '1', 0)"
    )
    c.execute(
        "INSERT OR REPLACE INTO tenant_settings VALUES ('t-off', 'rental_risk_alerts', '0', 0)"
    )
    conn.commit()
    conn.close()
    tenants = rp.risk_alert_enabled_tenants()
    assert "t-on" in tenants
    assert "t-off" not in tenants


def test_risk_alerts_never_raises_on_missing_db(tmp_path, monkeypatch):
    """A fresh DB without the risk table → clean empty result, never throws."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "risk6.sqlite"))
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _risk_settings())
    assert rp.evaluate_risk_alerts(tenant_id="t1") == []


def test_list_route_carries_forecast_and_risk_alerts(rclient, monkeypatch):
    """The /api/rentals payload ships difficulty_forecast + risk_alerts_fired."""
    monkeypatch.setattr(
        _app_module._rental_perf,
        "compute_difficulty_forecast",
        lambda: {"available": True, "direction": "up", "projected_change_pct": 12.0},
    )
    monkeypatch.setattr(
        _app_module._rental_perf,
        "evaluate_risk_alerts",
        lambda tenant_id="", concentration=None, worst_rigs=None: [
            {
                "severity": "WARN",
                "category": "rental_risk_rig",
                "message": "Rig #1 entrou no top-5 dos PIORES",
            }
        ],
    )
    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["difficulty_forecast"]["projected_change_pct"] == 12.0
    assert data["risk_alerts_fired"][0]["category"] == "rental_risk_rig"


def test_risk_alerts_top_n_slices_precomputed_list(tmp_path, monkeypatch):
    """evaluate_risk_alerts honors the tenant's top_n even when handed a
    precomputed (wider) worst-rigs list from the panel — a rig ranked beyond
    top_n must never fire, regardless of its danger score."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "risk_topn.sqlite"))
    monkeypatch.setattr(
        rp,
        "_risk_alert_settings",
        lambda tenant_id="": {
            "enabled": True,
            "danger": 0.0,
            "top_n": 2,
            "conc_pct": 99.0,
        },
    )
    worst = {
        "worst": [
            {"rig_id": "r1", "name": "R1", "danger_score": 80.0},
            {"rig_id": "r2", "name": "R2", "danger_score": 70.0},
            {"rig_id": "r3", "name": "R3", "danger_score": 60.0},  # ranked #3
        ],
        "count": 3,
    }
    alerts = rp.evaluate_risk_alerts(
        tenant_id="t1", concentration=None, worst_rigs=worst
    )
    assert len(alerts) == 2
    assert {a["value"] for a in alerts} == {"r1", "r2"}


def test_portfolio_series_excludes_owner_income(tmp_path, monkeypatch):
    """compute_portfolio_series 'spent' counts RENTER spend only — owner
    rentals (rigs leased out = money RECEIVED) are excluded, never added."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series_owner.sqlite"))
    renter = _series_row("1", "2026-07-20 10:00:00 UTC", 5000)
    owner_row = _series_row("2", "2026-07-21 10:00:00 UTC", 9000)
    owner_row["bucket"] = "owner"
    assert rp.save_rental_history([renter, owner_row], tenant_id="t-own") is True
    series = rp.compute_portfolio_series(tenant_id="t-own", bucket="week")
    assert series["totals"]["spent_sats"] == 5000  # 9000 owner income NOT counted
    assert series["totals"]["rentals"] == 1


def test_worst_rigs_and_heatmap_ignore_owner_rows(tmp_path, monkeypatch):
    """The renter risk analytics (worst-rigs leaderboard + rig heatmap) must
    ignore OWNER rentals — the operator's own rig under-delivering to renters
    is income-side, not 'who burned me when I rented'."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "worst_owner.sqlite"))
    bad1 = _reco_hist_row("r1", "rigA", "Rig A", 60, 100, "2026-07-20")
    bad2 = _reco_hist_row("r2", "rigA", "Rig A", 55, 100, "2026-07-21")
    owner_bad = _reco_hist_row("o1", "rigB", "Rig B", 30, 100, "2026-07-22")
    owner_bad["bucket"] = "owner"
    assert rp.save_rental_history([bad1, bad2, owner_bad], tenant_id="t-wo") is True
    worst = rp.compute_worst_rigs(tenant_id="t-wo")
    rig_ids = {w["rig_id"] for w in worst["worst"]}
    assert "rigA" in rig_ids
    assert "rigB" not in rig_ids  # owner-only rig never on the leaderboard
    heat = rp.compute_rig_heatmap([], [], tenant_id="t-wo")
    assert "Rig A" in {c["rig"] for c in heat}
    assert "Rig B" not in {c["rig"] for c in heat}


def test_save_rental_history_conflict_self_heals_bucket(tmp_path, monkeypatch):
    """Re-ingesting a rental corrects a legacy mislabeled bucket — the ON
    CONFLICT update must carry bucket=excluded.bucket so rows migrated with
    the 'renter' default self-heal to 'owner' on the next panel load."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bucket_heal.sqlite"))
    row = _series_row("1", "2026-07-20 10:00:00 UTC", 5000)
    row["bucket"] = "renter"  # legacy default applied by the ALTER migration
    assert rp.save_rental_history([row], tenant_id="t-heal") is True
    row["bucket"] = "owner"  # new ingest now marks owner rentals correctly
    assert rp.save_rental_history([row], tenant_id="t-heal") is True
    series = rp.compute_portfolio_series(tenant_id="t-heal", bucket="week")
    assert series["totals"]["spent_sats"] == 0  # healed to 'owner' → excluded
    assert series["totals"]["rentals"] == 0


def test_market_trend_ignores_subfloor_glitch_rows(tmp_path, monkeypatch):
    """fetch_market_trend must exclude legacy sub-floor rows (1e-8 parasite
    glitch ≈ 0 sats/TH·h) — otherwise 'cheapest market' reads 0 and the
    MARKET TIMING card misleads the operator."""
    _reset_trend_cache()
    monkeypatch.setenv("DB_PATH", str(tmp_path / "trend_floor.sqlite"))
    from services.db import get_db

    conn = get_db()
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS hashrate_market_history (
        ts INTEGER, provider TEXT, hashrate REAL,
        price_per_th_day REAL, duration_days REAL, fee_pct REAL,
        algorithm TEXT, score REAL, raw_data TEXT)"""
    )
    now = int(__import__("time").time())
    c.execute(
        "INSERT INTO hashrate_market_history(ts,provider,hashrate,price_per_th_day,duration_days,fee_pct,algorithm,score,raw_data) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (now, "parasite", 1000.0, 1e-8, 1.0, 0.0, "sha256", 0.0, "{}"),
    )
    c.execute(
        "INSERT INTO hashrate_market_history(ts,provider,hashrate,price_per_th_day,duration_days,fee_pct,algorithm,score,raw_data) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (now - 3600, "braiins", 1000.0, 5e-5, 1.0, 0.0, "sha256", 0.0, "{}"),
    )
    conn.commit()
    conn.close()
    trend = rp.fetch_market_trend(days=7)
    assert trend["points"], "expected real-price points to survive"
    for p in trend["points"]:
        assert p["sats_per_thh"] > 1.0  # ~0.04 sats glitch must never appear
    assert trend["summary"]["current_sats_per_thh"] > 1.0


# ── Historical network hashrate (exact past P/L) ───────────────────────────


def test_parse_start_ts_handles_rfc3339():
    """Braiins RFC3339 starts (T separator, Z, fractional seconds) parse to
    the same UTC instant as the space-separated MRR format."""
    t1 = rp._parse_start_ts("2026-07-20T10:00:00Z")
    t2 = rp._parse_start_ts("2026-07-20 10:00:00 UTC")
    assert t1 is not None and t1 == t2
    t3 = rp._parse_start_ts("2026-07-20T10:00:00.500Z")
    assert t3 is not None and abs(t3 - t1 - 0.5) < 1e-6
    assert rp._parse_start_ts("garbage") is None


def test_resolve_network_hashrate_from_snapshots(tmp_path, monkeypatch):
    """The nearest snapshot to a rental's start supplies the EXACT historical
    network hashrate (within ±3 days); end fallback works when start is missing."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "nhr.sqlite"))
    rp._snapshot_hr_cache.clear()
    import datetime as _dt
    from services.db import get_db

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS snapshots (ts INTEGER NOT NULL, network_hashrate REAL)"
    )
    base = int(_dt.datetime(2026, 7, 20, 10, 0, 0, tzinfo=_dt.timezone.utc).timestamp())
    c.execute("INSERT INTO snapshots(ts, network_hashrate) VALUES(?,?)", (base, 6e20))
    c.execute(
        "INSERT INTO snapshots(ts, network_hashrate) VALUES(?,?)",
        (base - 86400, 5.5e20),
    )
    conn.commit()
    conn.close()

    # Nearest snapshot to the rental start (10:00:00 UTC) → 6e20 wins over
    # the one 24h earlier (closer timestamp).
    hs = rp._resolve_network_hashrate_for_ts(base)
    assert hs == 6e20
    assert rp._resolve_network_hashrate_for_rental("2026-07-20T10:00:00Z") == 6e20
    # Missing start → end fallback.
    assert (
        rp._resolve_network_hashrate_for_rental(None, "2026-07-20 10:00:00 UTC") == 6e20
    )
    # Far outside the ±3d window → current fallback (mock the live value).
    monkeypatch.setattr(rp, "_network_hashrate_hs", lambda: 9e20)
    assert rp._resolve_network_hashrate_for_rental("2030-01-01 00:00:00 UTC") == 9e20


def test_portfolio_series_uses_persisted_historical_hashrate(tmp_path, monkeypatch):
    """The series must price past rentals against the network hashrate OBSERVED
    at their time (persisted network_hashrate_hs), NOT today's value — so
    historical P/L stops moving when the network grows."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "series_nhr.sqlite"))
    rp._snapshot_hr_cache.clear()
    row = _series_row("1", "2026-07-20 10:00:00 UTC", 400)  # 100 TH·h, paid 400 sats
    row["network_hashrate_hs"] = 6e20  # yield 3.125 sats/TH·h → 312.5 sats → P/L −87.5
    assert rp.save_rental_history([row], tenant_id="t1") is True
    # Today's network is DOUBLE that — if the series used it, P/L would be −243.75.
    monkeypatch.setattr(rp, "_network_hashrate_hs", lambda: 1.2e21)
    s = rp.compute_portfolio_series(tenant_id="t1", bucket="week")
    assert s["points"][0]["pl_sats"] == -87.5
    # Drill-down rows expose the persisted hashrate for transparency.
    rows = rp.series_bucket_rentals(tenant_id="t1", bucket="week", label="2026-W30")
    assert rows and rows[0]["network_hashrate_hs"] == int(6e20)


def test_network_hashrate_roundtrip_and_self_heal(tmp_path, monkeypatch):
    """network_hashrate_hs survives save→read, and the ON CONFLICT self-heals
    a legacy row (NULL) on the next ingest of the same rental."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "nhr_rt.sqlite"))
    rp._snapshot_hr_cache.clear()
    # Legacy ingest: row WITHOUT the field (pre-fix DB) → stored as NULL.
    legacy = _series_row("1", "2026-07-20 10:00:00 UTC", 400)
    legacy.pop("network_hashrate_hs", None)
    assert rp.save_rental_history([legacy], tenant_id="t1") is True
    from services.db import get_db

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT network_hashrate_hs FROM rental_history WHERE tenant_id='t1' AND rental_id='1'"
    )
    assert c.fetchone()[0] is None
    conn.close()
    # Re-ingest WITH the historical hashrate → ON CONFLICT updates it.
    fixed = _series_row("1", "2026-07-20 10:00:00 UTC", 400)
    fixed["network_hashrate_hs"] = 6e20
    assert rp.save_rental_history([fixed], tenant_id="t1") is True
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT network_hashrate_hs FROM rental_history WHERE tenant_id='t1' AND rental_id='1'"
    )
    assert c.fetchone()[0] == 6e20
    conn.close()


# ── Auto-alert: price paid X% above the market at purchase time ────────────


def _overpay_settings(threshold="100", window="48"):
    return {
        "rental_market_overpay_pct": threshold,
        "rental_pl_alert_window_hours": window,
    }


def _overpay_rental(
    rid,
    ended=True,
    paid_btc=0.001,
    adv_th=100.0,
    lenh=10.0,
    start_u=None,
    end_u=None,
    now=None,
):
    """Normalized MRR rental. Default: paid 0.001 BTC (100k sats) ÷ (100 TH ×
    10 h = 1000 TH·h) → agreed cost 100 sats/TH·h."""
    now = now or int(time.time())
    return {
        "id": rid,
        "ended": ended,
        "start": "2026-07-20 10:00:00 UTC",
        "end": "2026-07-20 20:00:00 UTC",
        "start_unix": start_u or (now - 3600),
        "end_unix": end_u or (now - 1000),
        "price_paid_btc": paid_btc,
        "hashrate_advertised_th": adv_th,
        "hashrate_average_th": adv_th,
        "hashrate_percent": 100.0,
        "length_hours": lenh,
    }


def test_market_overpay_alert_fires_and_dedups(tmp_path, monkeypatch):
    """A rental whose AGREED price is ≥ X% above the market at purchase fires
    ONE alert; the same rental never alerts again (persisted dedup)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ovp.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _overpay_settings("100")
    )
    monkeypatch.setattr(rp, "_historical_market_sats_per_thh", lambda ts: 40.0)
    now = int(time.time())
    # cost 100 sats/TH·h vs market 40 → overpay 150% ≥ 100 → fires (WARN).
    hist = [_overpay_rental("r1", end_u=now - 1000, now=now)]
    # cost 200 sats/TH·h (paid 2×) vs market 40 → overpay 400% ≥ 200 → CRIT.
    hist.append(_overpay_rental("r2", paid_btc=0.002, end_u=now - 900, now=now))

    a = rp.evaluate_market_overpay_alerts(hist, [], tenant_id="t1", now=now)
    by_id = {x["rental_id"]: x for x in a}
    assert set(by_id) == {"r1", "r2"}
    assert by_id["r1"]["severity"] == "WARN"
    assert by_id["r1"]["category"] == "rental_overpay"
    assert "pagou 150% acima" in by_id["r1"]["message"]
    assert "100 sats/TH" in by_id["r1"]["message"]
    assert "40 sats/TH" in by_id["r1"]["message"]
    assert by_id["r2"]["severity"] == "CRIT"  # ≥200% overpay

    # Second evaluation: deduped (one alert per rental EVER).
    assert rp.evaluate_market_overpay_alerts(hist, [], tenant_id="t1", now=now) == []


def test_market_overpay_threshold_not_met_or_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ovp2.sqlite"))
    now = int(time.time())
    hist = [_overpay_rental("r1", end_u=now - 1000, now=now)]
    # cost 100 vs market 60 → overpay 66.7% < 100 → silent.
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _overpay_settings("100")
    )
    monkeypatch.setattr(rp, "_historical_market_sats_per_thh", lambda ts: 60.0)
    assert rp.evaluate_market_overpay_alerts(hist, [], tenant_id="t1", now=now) == []
    # disabled (empty) / non-positive → off.
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _overpay_settings(""))
    assert rp.evaluate_market_overpay_alerts(hist, [], tenant_id="t1", now=now) == []
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _overpay_settings("0")
    )
    assert rp.evaluate_market_overpay_alerts(hist, [], tenant_id="t1", now=now) == []


def test_market_overpay_active_rental_extra_and_window(tmp_path, monkeypatch):
    """ACTIVE rentals bought recently ('na hora da compra') fire via extra;
    old active rentals stay silent (window)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ovp3.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _overpay_settings("100")
    )
    monkeypatch.setattr(rp, "_historical_market_sats_per_thh", lambda ts: 40.0)
    now = int(time.time())
    fresh = _overpay_rental("a1", ended=False, start_u=now - 1200, now=now)
    old = _overpay_rental("a2", ended=False, start_u=now - 200 * 3600, now=now)
    alerts = rp.evaluate_market_overpay_alerts(
        [], [], tenant_id="t1", now=now, extra=[fresh, old]
    )
    assert [x["rental_id"] for x in alerts] == ["a1"]
    assert (
        rp.evaluate_market_overpay_alerts([], [], tenant_id="t1", now=now, extra=[old])
        == []
    )


def test_market_overpay_prefers_historical_and_live_is_last_resort(
    tmp_path, monkeypatch
):
    """The market reference is the historical price at purchase — the live
    fetcher must NOT run when history covers; live only when history misses."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ovp4.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _overpay_settings("100")
    )
    now = int(time.time())

    # History covers → the live fetcher would raise if called.
    def _boom():
        raise AssertionError("live market must not run when history covers")

    monkeypatch.setattr(rp, "fetch_market_reference", _boom)
    monkeypatch.setattr(rp, "_historical_market_sats_per_thh", lambda ts: 40.0)
    hist = [_overpay_rental("r1", end_u=now - 1000, now=now)]
    assert (
        len(rp.evaluate_market_overpay_alerts(hist, [], tenant_id="t1", now=now)) == 1
    )

    # History misses → live fallback: cost 100 vs live 50 → 100% ≥ 100 → fires.
    monkeypatch.setattr(rp, "_historical_market_sats_per_thh", lambda ts: None)
    monkeypatch.setattr(
        rp,
        "fetch_market_reference",
        lambda: {"available": True, "price_sats_per_thh": 50.0},
    )
    hist2 = [_overpay_rental("r2", end_u=now - 1000, now=now)]
    a = rp.evaluate_market_overpay_alerts(hist2, [], tenant_id="t1", now=now)
    assert len(a) == 1 and "pagou 100% acima" in a[0]["message"]


# ── Arbitrage-opportunity alerts (market vs the tenant's own avg cost) ─────


def _arb_settings(threshold="30", cooldown="24"):
    return {
        "rental_market_arb_pct": threshold,
        "rental_market_arb_cooldown_hours": cooldown,
    }


def _seed_avg_cost(
    tmp_path,
    paid_sats,
    thh=1000.0,
    tenant_id="t1",
    delivered_thh=None,
    rid="arb-hist-1",
    start=None,
):
    """Seed rental_history (renter bucket) so the tenant's weighted average
    cost = paid_sats / thh sats/TH·h. ``delivered_thh`` (when given) feeds the
    EFFECTIVE cost baseline; ``start`` orders the 'last rental' baseline."""
    from services.db import get_db

    rp._ensure_history_table()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO rental_history(tenant_id,provider,bucket,rental_id,"
        "advertised_th,length_hours,delivered_thh,paid_sats,created_ts,start) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            tenant_id,
            "mrr",
            "renter",
            rid,
            100.0,
            thh / 100.0,
            delivered_thh,
            paid_sats,
            int(time.time()),
            start or f"2026-08-01 {rid}:00:00 UTC",
        ),
    )
    conn.commit()
    conn.close()


def test_market_arb_alert_fires_and_dedup_cooldown(tmp_path, monkeypatch):
    """Market ≥X% below the tenant's OWN avg cost fires; the SAME cooldown
    bucket dedups; a later bucket can fire again (persistent cheap market
    repeats daily, never spam)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "arb.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _arb_settings("30", "24")
    )
    monkeypatch.setattr(
        rp, "_recent_market_sats_per_thh", lambda now=0, window_h=12.0: 40.0
    )
    _seed_avg_cost(tmp_path, paid_sats=100_000, thh=1000.0)  # avg/last cost 100
    now = int(time.time())

    # avg 100 vs market 40 → 60% below ≥ 30 → fires (GOLD ≥50%).
    a = rp.evaluate_market_arb_alerts(tenant_id="t1", now=now)
    assert len(a) == 1
    assert a[0]["category"] == "market_arb"
    assert a[0]["severity"] == "GOLD"
    assert "ARBITRAGEM" in a[0]["message"]
    assert "60% abaixo" in a[0]["message"]
    assert a[0]["discount_pct"] == 60.0
    # The payload reports all three baselines + which drove the signal.
    assert a[0]["avg_cost_sats_per_thh"] == 100.0
    assert a[0]["ref_basis"] in ("average", "last")

    # Same cooldown bucket → deduped.
    assert rp.evaluate_market_arb_alerts(tenant_id="t1", now=now + 3600) == []
    # Next bucket (24h later) → fires again.
    assert len(rp.evaluate_market_arb_alerts(tenant_id="t1", now=now + 25 * 3600)) == 1


def test_market_signals_dry_run_never_consumes_dedup(tmp_path, monkeypatch):
    """dry_run (panel banner) computes the signal WITHOUT claiming the dedup
    slots — a signal already fired via dispatch must STAY visible in the
    banner, and a dry-run banner must never suppress a later real dispatch."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "arb-dry.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _arb_settings("30", "24")
    )
    monkeypatch.setattr(
        rp, "_recent_market_sats_per_thh", lambda now=0, window_h=12.0: 40.0
    )
    _seed_avg_cost(tmp_path, paid_sats=100_000, thh=1000.0)  # avg/last 100
    now = int(time.time())

    # Banner (dry_run) shows the window WITHOUT claiming the cooldown slot.
    assert (
        len(rp.evaluate_market_arb_alerts(tenant_id="t1", now=now, dry_run=True)) == 1
    )
    assert (
        len(rp.evaluate_market_arb_alerts(tenant_id="t1", now=now, dry_run=True)) == 1
    )
    # A real dispatch right after still fires (slot was never consumed).
    assert len(rp.evaluate_market_arb_alerts(tenant_id="t1", now=now)) == 1
    # After the real dispatch claimed the bucket, dry_run STILL shows it.
    assert (
        len(rp.evaluate_market_arb_alerts(tenant_id="t1", now=now, dry_run=True)) == 1
    )
    # …but a second real dispatch is deduped.
    assert rp.evaluate_market_arb_alerts(tenant_id="t1", now=now) == []


def test_market_overpay_dry_run_never_consumes_dedup(tmp_path, monkeypatch):
    """Same contract for the overpay family: dry_run repeats without claiming
    per-rental slots, and never suppresses a later real dispatch."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ovp-dry.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _overpay_settings("100")
    )
    monkeypatch.setattr(rp, "_historical_market_sats_per_thh", lambda ts: 40.0)
    now = int(time.time())
    hist = [_overpay_rental("r1", end_u=now - 1000, now=now)]  # cost 100 vs 40 → 150%

    # Banner shows it repeatedly (dry_run), then a real dispatch fires once.
    assert (
        len(
            rp.evaluate_market_overpay_alerts(
                hist, [], tenant_id="t1", now=now, dry_run=True
            )
        )
        == 1
    )
    assert (
        len(
            rp.evaluate_market_overpay_alerts(
                hist, [], tenant_id="t1", now=now, dry_run=True
            )
        )
        == 1
    )
    assert (
        len(rp.evaluate_market_overpay_alerts(hist, [], tenant_id="t1", now=now)) == 1
    )
    # Real dispatch claimed the slot; dry_run banner STAYS visible.
    assert (
        len(
            rp.evaluate_market_overpay_alerts(
                hist, [], tenant_id="t1", now=now, dry_run=True
            )
        )
        == 1
    )
    assert rp.evaluate_market_overpay_alerts(hist, [], tenant_id="t1", now=now) == []


def test_market_arb_last_rental_baseline_dominates(tmp_path, monkeypatch):
    """The LAST rental's cost is a baseline: a market price that is NOT cheap
    vs the average can still be a real window vs what the user paid most
    recently (the highest baseline drives the signal)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "arb-last.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _arb_settings("30", "24")
    )
    monkeypatch.setattr(
        rp, "_recent_market_sats_per_thh", lambda now=0, window_h=12.0: 160.0
    )
    # avg = (100k + 300k) / 2000 TH·h = 200; last rental paid 300k → 300.
    _seed_avg_cost(
        tmp_path,
        paid_sats=100_000,
        thh=1000.0,
        rid="old",
        start="2026-07-01 00:00:00 UTC",
    )
    _seed_avg_cost(
        tmp_path,
        paid_sats=300_000,
        thh=1000.0,
        rid="recent",
        start="2026-08-01 00:00:00 UTC",
    )
    now = int(time.time())

    a = rp.evaluate_market_arb_alerts(tenant_id="t1", now=now)
    assert len(a) == 1
    # avg 200 → market 160 is only 20% below (silent); last 300 → 47% (fires).
    assert a[0]["ref_basis"] == "last"
    assert a[0]["last_cost_sats_per_thh"] == 300.0
    assert a[0]["discount_pct"] == round((1 - 160 / 300) * 100, 1)
    assert "último aluguel" in a[0]["message"]
    assert "média 200" in a[0]["message"]


def test_market_arb_effective_cost_with_delivery(tmp_path, monkeypatch):
    """The EFFECTIVE baseline (paid ÷ actually-delivered TH·h) is the real
    cost when delivery < 100%: a market price ABOVE the advertised average can
    still be a buying window vs what the user effectively paid."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "arb-eff.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _arb_settings("30", "24")
    )
    monkeypatch.setattr(
        rp, "_recent_market_sats_per_thh", lambda now=0, window_h=12.0: 140.0
    )
    # Advertised avg = 100k/1000 TH·h = 100; delivered only 500 TH·h (50%)
    # → effective = 100k/500 = 200. Market 140: 40% below avg (silent), 30%
    # below effective (fires) — the delivery loss is the deciding reference.
    _seed_avg_cost(tmp_path, paid_sats=100_000, thh=1000.0, delivered_thh=500.0)
    now = int(time.time())

    a = rp.evaluate_market_arb_alerts(tenant_id="t1", now=now)
    assert len(a) == 1
    assert a[0]["ref_basis"] == "effective"
    assert a[0]["effective_cost_sats_per_thh"] == 200.0
    assert a[0]["discount_pct"] == 30.0
    assert "custo efetivo" in a[0]["message"]
    assert "média 100" in a[0]["message"]


def test_market_arb_last_baseline_with_mixed_start_formats(tmp_path, monkeypatch):
    """'last' must resolve the real most-recent rental even when start mixes
    formats (MRR 'YYYY-MM-DD HH:MM:SS UTC' vs Braiins RFC3339 '…T…Z') — a
    lexical ORDER BY would sort ALL space-form rows before T-form rows and
    pick the wrong one."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "arb-mix.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _arb_settings("30", "24")
    )
    monkeypatch.setattr(
        rp, "_recent_market_sats_per_thh", lambda now=0, window_h=12.0: 160.0
    )
    # Space-form (MRR) is LATER in wall time…
    _seed_avg_cost(
        tmp_path,
        paid_sats=300_000,
        thh=1000.0,
        rid="mrr-later",
        start="2026-08-05 00:00:00 UTC",
    )
    # …but T-form (Braiins) comes EARLIER in time — yet lexicographically
    # '2026-08-01T…' sorts AFTER '2026-08-05 ' (space < 'T'). The parser must
    # pick the MRR row as 'last'.
    _seed_avg_cost(
        tmp_path,
        paid_sats=100_000,
        thh=1000.0,
        rid="braiins-earlier",
        start="2026-08-01T10:00:00Z",
    )
    now = int(time.time())

    bases = rp._tenant_cost_baselines(tenant_id="t1")
    assert bases["last"] == 300.0  # the MRR row (later wall time) — not 100
    a = rp.evaluate_market_arb_alerts(tenant_id="t1", now=now)
    assert len(a) == 1
    assert a[0]["ref_basis"] == "last"
    assert a[0]["last_cost_sats_per_thh"] == 300.0


def test_market_arb_threshold_not_met_or_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "arb2.sqlite"))
    monkeypatch.setattr(
        rp, "_recent_market_sats_per_thh", lambda now=0, window_h=12.0: 80.0
    )
    _seed_avg_cost(tmp_path, paid_sats=100_000, thh=1000.0)  # avg 100
    now = int(time.time())
    # avg 100 vs market 80 → 20% below < 30 → silent.
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _arb_settings("30"))
    assert rp.evaluate_market_arb_alerts(tenant_id="t1", now=now) == []
    # Disabled (empty / 0 / garbage).
    for bad in ("", "0", "abc"):
        monkeypatch.setattr(
            rp, "load_settings", lambda tenant_id="", _bad=bad: _arb_settings(_bad)
        )
        assert rp.evaluate_market_arb_alerts(tenant_id="t1", now=now) == []


def test_market_arb_skips_without_history_or_market(tmp_path, monkeypatch):
    """No track record (empty rental_history) or no market reference → honest
    skip — never fabricates a baseline."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "arb3.sqlite"))
    monkeypatch.setattr(rp, "load_settings", lambda tenant_id="": _arb_settings("30"))
    now = int(time.time())
    # No history at all → skip.
    assert rp.evaluate_market_arb_alerts(tenant_id="t1", now=now) == []
    # History but no market reference → skip.
    _seed_avg_cost(tmp_path, paid_sats=100_000, thh=1000.0)
    monkeypatch.setattr(
        rp, "_recent_market_sats_per_thh", lambda now=0, window_h=12.0: None
    )
    assert rp.evaluate_market_arb_alerts(tenant_id="t1", now=now) == []


def test_tenant_typical_th_median_and_fallback(tmp_path, monkeypatch):
    """_tenant_typical_th = MEDIAN advertised TH of the tenant's rentals
    (robust to outliers) for prefilling the Braiins buy modal; None with no
    usable history so the frontend falls back to 1000 TH."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "th.sqlite"))
    rp._ensure_history_table()
    from services.db import get_db

    conn = get_db()
    c = conn.cursor()
    # Odd count → middle value: [100, 100, 1000, 5000, 10000] → 1000.
    for i, th in enumerate((100, 100, 1000, 5000, 10000)):
        c.execute(
            "INSERT INTO rental_history(tenant_id,provider,bucket,rental_id,"
            "advertised_th,length_hours,paid_sats,created_ts) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("t1", "mrr", "renter", f"th-{i}", th, 10.0, 100_000, int(time.time())),
        )
    conn.commit()
    conn.close()
    assert rp._tenant_typical_th(tenant_id="t1") == 1000.0
    # Even count → mean of the two middle: [100, 1000] → 550, rounded to 600.
    monkeypatch.setenv("DB_PATH", str(tmp_path / "th2.sqlite"))
    rp._ensure_history_table()
    conn = get_db()
    c = conn.cursor()
    for i, th in enumerate((100, 1000)):
        c.execute(
            "INSERT INTO rental_history(tenant_id,provider,bucket,rental_id,"
            "advertised_th,length_hours,paid_sats,created_ts) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("t2", "mrr", "renter", f"th-{i}", th, 10.0, 100_000, int(time.time())),
        )
    conn.commit()
    conn.close()
    assert rp._tenant_typical_th(tenant_id="t2") == 600.0
    # No history → None (frontend falls back to 1000).
    assert rp._tenant_typical_th(tenant_id="nobody") is None


def test_market_arb_signal_carries_suggested_th(tmp_path, monkeypatch):
    """The arbitrage alert payload carries suggested_th (tenant's typical
    order size) so the buy-modal prefill uses it instead of a fixed 1000."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "arb-th.sqlite"))
    monkeypatch.setattr(
        rp, "load_settings", lambda tenant_id="": _arb_settings("30", "24")
    )
    monkeypatch.setattr(
        rp, "_recent_market_sats_per_thh", lambda now=0, window_h=12.0: 40.0
    )
    _seed_avg_cost(
        tmp_path,
        paid_sats=100_000,
        thh=1000.0,
        rid="old",
        start="2026-07-01 00:00:00 UTC",
    )
    _seed_avg_cost(
        tmp_path,
        paid_sats=100_000,
        thh=1000.0,
        rid="recent",
        start="2026-08-01 00:00:00 UTC",
    )
    # One BIG outlier that still PAYS its hashrate (3M sats for 5000 TH×10h =
    # 60 sats/TH·h) so the baseline stays above the market 40 → fires, and
    # suggested_th = median of [100,100,5000] = 100 (robust vs the outlier).
    from services.db import get_db

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO rental_history(tenant_id,provider,bucket,rental_id,"
        "advertised_th,length_hours,paid_sats,created_ts) "
        "VALUES(?,?,?,?,?,?,?,?)",
        ("t1", "mrr", "renter", "big", 5000.0, 10.0, 3_000_000, int(time.time())),
    )
    conn.commit()
    conn.close()
    a = rp.evaluate_market_arb_alerts(
        tenant_id="t1", now=int(time.time()), dry_run=True
    )
    assert len(a) == 1
    assert a[0]["suggested_th"] == 100.0  # median of [100,100,5000] → 100


def test_market_arb_enabled_tenants_no_mrr_key_needed(tmp_path, monkeypatch):
    """Arbitrage gating is PURELY the threshold setting — unlike the other
    market families it needs NO MRR credentials (local eval, zero provider
    cost). Same tenant with BOTH settings: empty key → arb includes it,
    overpay excludes it (the key is the deciding factor for overpay)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "arb4.sqlite"))
    rp._ensure_rig_settings_tables()
    from services.db import get_db

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO tenant_settings VALUES ('t-arb', 'rental_market_arb_pct', '40', 0)"
    )
    c.execute(
        "INSERT OR REPLACE INTO tenant_settings VALUES ('t-arb', 'rental_market_overpay_pct', '100', 0)"
    )
    c.execute(
        "INSERT OR REPLACE INTO tenant_settings VALUES ('t-off', 'rental_market_arb_pct', '0', 0)"
    )
    conn.commit()
    conn.close()

    # With an EMPTY MRR key, arbitrage still lists the tenant…
    def _no_key(tenant_id=""):
        return {"api_key": ""}

    monkeypatch.setattr(rp, "mrr_credentials", _no_key)
    out = rp.market_arb_enabled_tenants()
    assert "t-arb" in out
    assert "t-off" not in out
    # …while the overpay family (same tenant, same DB) excludes it BECAUSE
    # of the missing key — proving arb is the credential-free family.
    ovp = rp.market_overpay_enabled_tenants()
    assert "t-arb" not in ovp
