"""Tests for POST /api/settings/test-auto-exclude-alert (Issue #104).

The button in Settings validates the tenant's AUTO-EXCLUSION alert channel
(webhook + push) with the SAME message shape the periodic sweep dispatches
on a real exclusion (Issue #102) — through the SAME builders the async
dispatch path uses (send_webhook_for_alert + notify_tenant_alert).

Contract locked here:
  - 403 when a webhook is configured but the PRO gate is closed
  - 200 verdict always: webhook_configured / webhook_ok / webhook_reason /
    webhook_min_severity / push_targets / sent_any / guidance
  - message mirrors the real sweep message (auto-excluído por sub-entrega)
  - webhook below webhook_min_severity → webhook_ok False + reason, push
    still fires
  - never raises (webhook/push exceptions degrade to verdicts)
"""

import pytest

from app import app

import routes.settings_routes as settings_routes

import services.push_notifier as _pn


@pytest.fixture
def client():
    app.config["TESTING"] = True
    yield app.test_client()


def _settings(**over):
    base = {
        "webhook_url": "",
        "webhook_min_severity": "WARN",
    }
    base.update(over)
    return base


# ── POST /api/settings/test-auto-exclude-alert ────────────────────────────

class TestTestAutoExcludeAlert:
    def test_no_channel_configured_returns_guidance(self, client, monkeypatch):
        monkeypatch.setattr(settings_routes, "load_settings", lambda **kw: _settings())
        monkeypatch.setattr(_pn, "notify_tenant_alert", lambda *a, **k: 0)
        r = client.post("/api/settings/test-auto-exclude-alert")
        assert r.status_code == 200
        d = r.get_json()
        assert d["success"] is False
        assert d["webhook_configured"] is False
        assert d["push_targets"] == 0
        assert "webhook_url" in d["guidance"]

    def test_403_when_not_pro_with_webhook(self, client, monkeypatch):
        monkeypatch.setattr(settings_routes, "load_settings",
                            lambda **kw: _settings(webhook_url="https://hooks.example.com/abc"))
        monkeypatch.setattr(settings_routes, "is_pro", lambda: False)
        r = client.post("/api/settings/test-auto-exclude-alert")
        assert r.status_code == 403
        assert "PRO" in r.get_json()["error"]

    def test_sends_webhook_and_push_with_sample_message(self, client, monkeypatch):
        monkeypatch.setattr(settings_routes, "load_settings",
                            lambda **kw: _settings(webhook_url="https://hooks.example.com/abc"))
        monkeypatch.setattr(settings_routes, "is_pro", lambda: True)
        wh_kwargs = {}
        monkeypatch.setattr(_pn, "send_webhook_for_alert",
                            lambda **kw: (wh_kwargs.update(kw) or True))
        push_calls = {}

        def _fake_push(*a, **k):
            push_calls["args"] = a
            return 2

        monkeypatch.setattr(_pn, "notify_tenant_alert", _fake_push)
        r = client.post("/api/settings/test-auto-exclude-alert")
        assert r.status_code == 200
        d = r.get_json()
        assert d["success"] is True
        assert d["webhook_ok"] is True
        assert d["webhook_reason"] == "ok"
        assert d["push_targets"] == 2
        # Same message shape the sweep fires (Issue #102).
        assert "auto-excluído por sub-entrega" in d["message"]
        assert "grade F" in d["message"]
        assert "entrega 57.5%" in d["message"]
        assert "2 amostras" in d["message"]
        # Same builders/args as the async dispatch path.
        assert wh_kwargs["url"] == "https://hooks.example.com/abc"
        assert wh_kwargs["severity"] == "WARN"
        assert wh_kwargs["category"] == "rental_auto_exclude"
        assert wh_kwargs["message"] == d["message"]
        assert wh_kwargs["min_severity"] == "WARN"
        assert push_calls["args"][0] == "default"  # require_tenant normalizes
        assert push_calls["args"][1] == "WARN"
        assert push_calls["args"][2] == "rental_auto_exclude"

    def test_webhook_below_threshold_reports_reason_but_push_still_fires(self, client, monkeypatch):
        monkeypatch.setattr(settings_routes, "load_settings",
                            lambda **kw: _settings(
                                webhook_url="https://hooks.example.com/abc",
                                webhook_min_severity="CRIT"))
        monkeypatch.setattr(settings_routes, "is_pro", lambda: True)
        # The real send_webhook_for_alert returns False below the threshold
        # (severity gate) — mirror that behavior with the real gate function.
        real_gate = _pn.severity_meets_threshold
        monkeypatch.setattr(_pn, "send_webhook_for_alert",
                            lambda **kw: real_gate(kw["severity"], kw["min_severity"]))
        monkeypatch.setattr(_pn, "notify_tenant_alert", lambda *a, **k: 2)
        r = client.post("/api/settings/test-auto-exclude-alert")
        assert r.status_code == 200
        d = r.get_json()
        assert d["webhook_ok"] is False
        assert "below threshold" in d["webhook_reason"]
        assert d["webhook_min_severity"] == "CRIT"
        # Push is NOT severity-gated — the sample still reaches devices.
        assert d["push_targets"] == 2
        assert d["success"] is True

    def test_not_pro_without_webhook_still_validates_push(self, client, monkeypatch):
        """The PRO gate only covers the webhook channel — a push-only tenant
        with no license can still test its push channel (200 verdict)."""
        monkeypatch.setattr(settings_routes, "load_settings", lambda **kw: _settings())
        monkeypatch.setattr(settings_routes, "is_pro", lambda: False)
        monkeypatch.setattr(_pn, "notify_tenant_alert", lambda *a, **k: 1)
        r = client.post("/api/settings/test-auto-exclude-alert")
        assert r.status_code == 200
        d = r.get_json()
        assert d["success"] is True
        assert d["webhook_configured"] is False
        assert d["push_targets"] == 1

    def test_push_default_tenant_normalization(self, client, monkeypatch):
        """The operator's dashboard subscription is stored under '' by
        /api/push/subscribe, but require_tenant normalizes anonymous to
        'default'. notify_tenant_alert must treat them as the same tenant,
        or the sweep/button verdict lies about push delivery."""
        captured = {}
        monkeypatch.setattr(settings_routes, "load_settings", lambda **kw: _settings())

        def _fake_get_subs(tenant_id):
            captured["tenant"] = tenant_id
            return []

        monkeypatch.setattr(_pn, "get_subscriptions_for_tenant", _fake_get_subs)
        monkeypatch.setattr(_pn, "VAPID_PRIVATE_KEY", "k")
        monkeypatch.setattr(_pn, "VAPID_PUBLIC_KEY", "k")
        _pn.notify_tenant_alert("default", "WARN", "rental_auto_exclude", "msg")
        assert captured["tenant"] == ""  # canonical operator tenant

    def test_webhook_exception_degrades_to_verdict(self, client, monkeypatch):
        monkeypatch.setattr(settings_routes, "load_settings",
                            lambda **kw: _settings(webhook_url="https://hooks.example.com/abc"))
        monkeypatch.setattr(settings_routes, "is_pro", lambda: True)

        def boom(**kw):
            raise ConnectionError("no route to host")

        monkeypatch.setattr(_pn, "send_webhook_for_alert", boom)
        monkeypatch.setattr(_pn, "notify_tenant_alert", lambda *a, **k: 1)
        r = client.post("/api/settings/test-auto-exclude-alert")
        assert r.status_code == 200
        d = r.get_json()
        assert d["webhook_ok"] is False
        assert "POST failed" in d["webhook_reason"]
        # Push survived the webhook failure.
        assert d["push_targets"] == 1
        assert d["success"] is True

    def test_push_exception_degrades_to_zero_targets(self, client, monkeypatch):
        monkeypatch.setattr(settings_routes, "load_settings", lambda **kw: _settings())
        monkeypatch.setattr(_pn, "notify_tenant_alert",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        r = client.post("/api/settings/test-auto-exclude-alert")
        assert r.status_code == 200
        d = r.get_json()
        assert d["success"] is False
        assert d["push_targets"] == 0
