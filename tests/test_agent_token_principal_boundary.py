"""Security regressions for Issue #641 agent credential administration."""

import uuid

import pytest

from app import app
from services import agent_tokens
from services.auth import create_token


@pytest.fixture
def client(monkeypatch):
    secret = "agent-principal-test-secret-0123456789abcdef"
    saved = app.config.get("JWT_SECRET_KEY")
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = secret
    monkeypatch.setenv("SECRET_KEY", secret)
    monkeypatch.setenv("CLOUD_MODE", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("TENANT_API_KEYS", raising=False)
    with app.test_client() as flask_client:
        yield flask_client
    agent_tokens.invalidate_memo()
    if saved is None:
        app.config.pop("JWT_SECRET_KEY", None)
    else:
        app.config["JWT_SECRET_KEY"] = saved


def _tenant():
    return f"principal-{uuid.uuid4().hex[:10]}"


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _user(tenant, role="admin"):
    return create_token(subject=tenant, extra_claims={"role": role})


def _mint_agent(client, user_token):
    response = client.post("/api/agent/token", headers=_headers(user_token))
    assert response.status_code == 200
    return response.get_json()["token"]


def test_agent_principal_cannot_mint_or_revoke_tokens(client):
    tenant = _tenant()
    agent = _mint_agent(client, _user(tenant))

    mint = client.post("/api/agent/token", headers=_headers(agent))
    revoke = client.post("/api/agent/tokens/revoke", headers=_headers(agent))

    for response in (mint, revoke):
        assert response.status_code == 403
        assert response.get_json()["code"] == "AGENT_TOKEN_USER_REQUIRED"
        assert "token" not in response.get_json()


def test_revoked_agent_cannot_mint_a_replacement(client):
    tenant = _tenant()
    admin = _user(tenant)
    agent = _mint_agent(client, admin)
    revoked = client.post("/api/agent/tokens/revoke", headers=_headers(admin))
    assert revoked.status_code == 200

    replacement = client.post("/api/agent/token", headers=_headers(agent))

    assert replacement.status_code == 403
    assert replacement.get_json()["code"] == "AGENT_TOKEN_USER_REQUIRED"
    assert "token" not in replacement.get_json()


def test_cloud_role_is_enforced_without_api_keys(client):
    tenant = _tenant()
    member = _user(tenant, "member")
    viewer = _user(tenant, "viewer")

    assert client.post("/api/agent/token", headers=_headers(member)).status_code == 200
    denied_mint = client.post("/api/agent/token", headers=_headers(viewer))
    denied_revoke = client.post("/api/agent/tokens/revoke", headers=_headers(member))

    assert denied_mint.status_code == 403
    assert denied_mint.get_json()["required_role"] == "member"
    assert denied_revoke.status_code == 403
    assert denied_revoke.get_json()["required_role"] == "admin"
