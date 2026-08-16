"""CYPHER65 // PREMIUM tier (Issue #182) — AI Operator real (LLM) $29/mo.

Covers:
  1. _key_plan: static premium > static pro > DB plan (premium/pro); free.
  2. is_premium: open mode True; licensed free/pro False; premium True.
  3. premium_required: open mode no-op; free → 402 (required_tier premium,
     upgrade 29, current_tier free); pro → 402 current_tier pro; premium →
     200. paywall_view (tier=premium) entra no funil.
  4. license_status: premium payload (tier premium, upgrade None,
     ai_configured) + pro payload (upgrade PREMIUM).
  5. payments._variant_months: LEMON_SQUEEZY_PREMIUM_VARIANT_ID → premium;
     default → pro. create_checkout usa o variant do plan.
  6. Webhook order_created com variant premium → issue_license(plan='premium').
  7. /api/ai/query: open mode 200; licensed sem premium 402; premium 200.
  8. /api/admin/licenses: plan=premium aceito; plan inválido → 400.

HERMETIC — conftest redirects DB_PATH; o fixture scruba o env por teste.
"""

import hashlib
import hmac
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module
from services import licensing, payments

app = _app_module.app

_PRO_KEY = "PRO-KEY-123"
_PREM_KEY = "PREM-KEY-123"


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch):
    """Every test starts with the gate OFF and no AI/payment env vars."""
    for name in (
        "PRO_LICENSE_KEYS",
        "PREMIUM_LICENSE_KEYS",
        "LEMON_SQUEEZY_API_KEY",
        "LEMON_SQUEEZY_WEBHOOK_SECRET",
        "LEMON_SQUEEZY_STORE_ID",
        "LEMON_SQUEEZY_VARIANT_ID",
        "LEMON_SQUEEZY_PREMIUM_VARIANT_ID",
        "PRO_KEYS_DB",
        "API_KEY",
        "AI_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    return app.test_client()


def _activate_licensed(monkeypatch, premium: bool = False):
    monkeypatch.setenv("PRO_LICENSE_KEYS", _PRO_KEY)
    if premium:
        monkeypatch.setenv("PREMIUM_LICENSE_KEYS", _PREM_KEY)


def _ls_env(monkeypatch, premium_variant: str = ""):
    monkeypatch.setenv("LEMON_SQUEEZY_API_KEY", "ls-test-key")
    monkeypatch.setenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "whsec-test")
    monkeypatch.setenv("LEMON_SQUEEZY_STORE_ID", "1")
    monkeypatch.setenv("LEMON_SQUEEZY_VARIANT_ID", "10")
    if premium_variant:
        monkeypatch.setenv("LEMON_SQUEEZY_PREMIUM_VARIANT_ID", premium_variant)


# ── _key_plan / is_premium ──────────────────────────────────────────────


def test_key_plan_free_when_empty():
    assert licensing._key_plan("") == "free"
    assert licensing._key_plan("NOPE-KEY") == "free"


def test_key_plan_static_premium_wins_over_pro(monkeypatch):
    _activate_licensed(monkeypatch, premium=True)
    assert licensing._key_plan(_PREM_KEY) == "premium"
    assert licensing._key_plan(_PRO_KEY) == "pro"


def test_key_plan_db_plans(monkeypatch):
    _activate_licensed(monkeypatch)
    pro_key = licensing.issue_license(plan="pro", source="test")
    prem_key = licensing.issue_license(plan="premium", source="test")
    assert licensing._key_plan(pro_key) == "pro"
    assert licensing._key_plan(prem_key) == "premium"


def test_key_valid_accepts_premium_static(monkeypatch):
    _activate_licensed(monkeypatch, premium=True)
    # A premium key também abre as portas PRO (pro_required passa).
    assert licensing._key_valid(_PREM_KEY) is True


def test_is_premium_open_mode():
    assert licensing.licensing_configured() is False
    with app.test_request_context("/"):
        assert licensing.is_premium() is True


def test_is_premium_licensed_tiers(monkeypatch):
    _activate_licensed(monkeypatch, premium=True)
    with app.test_request_context("/", headers={"X-License-Key": _PREM_KEY}):
        assert licensing.is_premium() is True
    with app.test_request_context("/", headers={"X-License-Key": _PRO_KEY}):
        assert licensing.is_premium() is False
    with app.test_request_context("/"):
        assert licensing.is_premium() is False


# ── premium_required ────────────────────────────────────────────────────


def _premium_view():
    @licensing.premium_required
    def _stub():
        return ("ok", 200)

    return _stub


def test_premium_required_open_mode_noop():
    with app.test_request_context("/"):
        status, code = _premium_view()()
        assert code == 200 and status == "ok"


def test_premium_required_free_402_payload(monkeypatch):
    _activate_licensed(monkeypatch)  # gate on, sem chave
    with app.test_request_context("/"):
        resp, code = _premium_view()()
    assert code == 402
    d = resp.get_json()
    assert d["code"] == "LICENSE_REQUIRED"
    assert d["required_tier"] == "premium"
    assert d["current_tier"] == "free"
    assert d["upgrade"] == {"plan": "PREMIUM", "price_usd_month": 29}
    assert d["features"] == licensing.PREMIUM_FEATURES


def test_premium_required_pro_402_current_tier(monkeypatch):
    _activate_licensed(monkeypatch)
    with app.test_request_context("/", headers={"X-License-Key": _PRO_KEY}):
        resp, code = _premium_view()()
    assert code == 402
    assert resp.get_json()["current_tier"] == "pro"


def test_premium_required_premium_200(monkeypatch):
    _activate_licensed(monkeypatch, premium=True)
    with app.test_request_context("/", headers={"X-License-Key": _PREM_KEY}):
        status, code = _premium_view()()
    assert code == 200 and status == "ok"


def test_premium_required_tracks_paywall(monkeypatch):
    _activate_licensed(monkeypatch)
    calls = []

    def fake_track(event, tenant_id="", meta=None):
        calls.append((event, tenant_id, meta))

    monkeypatch.setattr("services.conversion.track_event", fake_track)
    with app.test_request_context("/"):
        _premium_view()()
    assert len(calls) == 1
    event, tenant_id, meta = calls[0]
    assert event == "paywall_view"
    assert meta.get("tier") == "premium"


# ── license_status ──────────────────────────────────────────────────────


def test_license_status_premium(monkeypatch, client):
    _activate_licensed(monkeypatch, premium=True)
    d = client.get(
        "/api/license-status", headers={"X-License-Key": _PREM_KEY}
    ).get_json()
    assert d["tier"] == "premium"
    assert d["premium"] is True
    assert d["pro"] is True
    assert d["upgrade"] is None
    assert "ai_configured" in d
    assert d["features"].get("ai_operator") == "unlocked"


def test_license_status_pro_upgrade_premium(monkeypatch, client):
    _activate_licensed(monkeypatch)
    d = client.get(
        "/api/license-status", headers={"X-License-Key": _PRO_KEY}
    ).get_json()
    assert d["tier"] == "pro"
    assert d["premium"] is False
    assert d["upgrade"] == {"plan": "PREMIUM", "price_usd_month": 29}
    assert d["features"].get("ai_operator") == "locked"


def test_license_status_ai_configured_flag(monkeypatch, client):
    # Sem AI_API_KEY → ai_configured False (o PREMIUM surface precisa de LLM).
    d = client.get("/api/license-status").get_json()
    assert d["ai_configured"] is False


# ── payments: variant premium + checkout + webhook ─────────────────────


def test_variant_months_premium(monkeypatch):
    _ls_env(monkeypatch, premium_variant="99")
    assert payments._variant_months("99") == ("premium", 12)
    assert payments._variant_months("10") == ("pro", 12)
    assert payments._variant_months("") == ("pro", 12)


def test_create_checkout_uses_premium_variant(monkeypatch):
    _ls_env(monkeypatch, premium_variant="99")

    captured = {}

    class FakeResp:
        ok = True

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"attributes": {"url": "https://ls.test/checkout"}}}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json") or {}
        return FakeResp()

    monkeypatch.setattr(payments.requests, "post", fake_post)
    url = payments.create_checkout(plan="premium", funnel_id="f_abc")
    assert url == "https://ls.test/checkout"
    attrs = captured["json"]["data"]["attributes"]
    rel_variant = captured["json"]["data"]["relationships"]["variant"]["data"]["id"]
    assert rel_variant == "99"
    assert attrs["checkout_data"]["custom"]["plan"] == "premium"


def test_create_checkout_unknown_plan_falls_back_to_pro(monkeypatch):
    _ls_env(monkeypatch, premium_variant="99")

    def fake_post(url, **kwargs):
        return FakeResp()

    class FakeResp:
        ok = True

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"attributes": {"url": "u"}}}

    monkeypatch.setattr(payments.requests, "post", fake_post)
    assert payments.create_checkout(plan="bogus") is not None


def test_webhook_premium_variant_issues_premium_key(client, monkeypatch):
    _ls_env(monkeypatch, premium_variant="99")
    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": "order-prem-1",
            "attributes": {
                "user_email": "buyer@example.com",
                "first_order_item": {"variant_id": 99},
            },
        },
    }
    raw = bytes(__import__("json").dumps(payload), "utf-8")  # sign the raw body we post
    sig = hmac.new(b"whsec-test", raw, hashlib.sha256).hexdigest()
    r = client.post(
        "/api/payments/webhook",
        data=raw,
        headers={"X-Signature": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    issued = r.get_json().get("license_key")
    assert issued
    assert licensing._key_valid(issued) is True
    assert licensing._key_plan(issued) == "premium"


# ── /api/ai/query gate ──────────────────────────────────────────────────


def test_ai_query_open_mode_allowed(client):
    r = client.post("/api/ai/query", json={"query": "hi"})
    # Sem gate (open mode) → o handler roda (stream 200 com erro de LLM
    # ausente, sem rede).
    assert r.status_code == 200


def test_ai_query_licensed_free_402(client, monkeypatch):
    _activate_licensed(monkeypatch)
    r = client.post("/api/ai/query", json={"query": "hi"})
    assert r.status_code == 402
    d = r.get_json()
    assert d["required_tier"] == "premium"
    assert d["upgrade"]["plan"] == "PREMIUM"


def test_ai_query_licensed_pro_402(client, monkeypatch):
    _activate_licensed(monkeypatch)
    r = client.post(
        "/api/ai/query", json={"query": "hi"}, headers={"X-License-Key": _PRO_KEY}
    )
    assert r.status_code == 402
    assert r.get_json()["current_tier"] == "pro"


def test_ai_query_licensed_premium_allowed(client, monkeypatch):
    _activate_licensed(monkeypatch, premium=True)
    r = client.post(
        "/api/ai/query", json={"query": "hi"}, headers={"X-License-Key": _PREM_KEY}
    )
    assert r.status_code == 200


# ── /api/admin/licenses plan validation ────────────────────────────────


def test_admin_issue_premium_license(client, monkeypatch):
    _activate_licensed(monkeypatch)
    monkeypatch.setenv("API_KEY", "op-key")
    r = client.post(
        "/api/admin/licenses",
        json={"plan": "premium", "email": "a@b.c"},
        headers={"X-API-Key": "op-key"},
    )
    assert r.status_code == 200
    key = r.get_json()["license_key"]
    assert licensing._key_plan(key) == "premium"


def test_admin_issue_invalid_plan_400(client, monkeypatch):
    _activate_licensed(monkeypatch)
    monkeypatch.setenv("API_KEY", "op-key")
    r = client.post(
        "/api/admin/licenses",
        json={"plan": "mega"},
        headers={"X-API-Key": "op-key"},
    )
    assert r.status_code == 400
