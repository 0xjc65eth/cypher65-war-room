"""Safe, read-only MRR/Braiins diagnostic contracts (Issue #385)."""

import requests

import app as app_module
from services import rental_performance as rp


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload or {}

    def json(self):
        return self._payload


def _token(tenant_id="diagnostic-tenant"):
    from services.auth import create_token

    with app_module.app.app_context():
        return create_token(subject=tenant_id, extra_claims={"role": "admin"})


def test_mrr_probe_missing_credentials_never_calls_provider(monkeypatch):
    monkeypatch.setattr(rp, "_mrr_creds", lambda tenant_id="": {"api_key": "", "api_secret": ""})
    monkeypatch.setattr(rp.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert rp.probe_mrr_credentials("tenant-a")["status"] == "missing"


def test_mrr_probe_distinguishes_acceptance_rejection_and_timeout(monkeypatch):
    monkeypatch.setattr(
        rp, "_mrr_creds", lambda tenant_id="": {"api_key": "private-key", "api_secret": "private-secret"}
    )

    monkeypatch.setattr(
        rp.requests,
        "get",
        lambda *a, **k: FakeResponse(200, {"data": {"authed": True}}),
    )
    accepted = rp.probe_mrr_credentials("tenant-a")
    assert accepted["status"] == "accepted"
    assert "private-key" not in str(accepted)
    assert "private-secret" not in str(accepted)

    monkeypatch.setattr(rp.requests, "get", lambda *a, **k: FakeResponse(403))
    assert rp.probe_mrr_credentials("tenant-a")["status"] == "rejected"

    monkeypatch.setattr(
        rp.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout())
    )
    assert rp.probe_mrr_credentials("tenant-a")["status"] == "timeout"


def test_mrr_diagnostic_route_is_tenant_scoped_and_audited(monkeypatch):
    app_module.app.config["TESTING"] = True
    monkeypatch.setitem(
        app_module.app.config,
        "JWT_SECRET_KEY",
        "provider-diagnostic-secret-0123456789",
    )
    seen = {}

    def probe(tenant_id=""):
        seen["tenant_id"] = tenant_id
        return {"success": True, "configured": True, "status": "accepted", "provider": "mrr"}

    monkeypatch.setattr(rp, "probe_mrr_credentials", probe)
    with app_module.app.test_client() as client:
        response = client.post(
            "/api/settings/test-mrr",
            headers={"Authorization": "Bearer " + _token()},
        )

    assert response.status_code == 200
    assert seen["tenant_id"] == "diagnostic-tenant"
    payload = response.get_json()
    assert payload["read_only"] is True
    assert payload["endpoint"] == "/whoami"

    from services.tenant import recent_audit_logs

    assert any(
        row["action"] == "settings.provider_diagnostic" and row["target"] == "mrr"
        for row in recent_audit_logs("diagnostic-tenant")
    )
