"""Dangerous POSTs refuse anonymous and localhost callers without a principal."""

import json

import pytest

import app as app_module
from services.mutation_auth import has_mutation_principal, is_dangerous_mutation

KEY = "mutation-principal-key"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("TENANT_API_KEYS", raising=False)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _post(client, path, **kwargs):
    return client.post(path, json=kwargs.pop("json", {}) or {}, **kwargs)


class TestPathGate:
    @pytest.mark.parametrize(
        "path",
        (
            "/api/devices/miner-1/command",
            "/api/devices/miner-1/command/confirmation",
            "/api/devices/miner-1/commands/op-1/rollback",
            "/api/devices/miner-1/commands/op-1/rollback/confirmation",
            "/api/axe-fleet/devices/miner-1/restart",
            "/api/axe-fleet/devices/miner-1/identify",
            "/api/axe-fleet/devices/miner-1/pause",
            "/api/axe-fleet/devices/miner-1/resume",
            "/api/axe-fleet/devices/miner-1/config",
            "/api/axe-fleet/power-plugs/save-credentials",
            "/api/axe-fleet/power-plugs/plug-1/on",
            "/api/axe-fleet/power-plugs/plug-1/off",
            "/api/axe-fleet/power-plugs/plug-1/toggle",
            "/api/axe-fleet/miners/miner-1/power-cycle",
            "/api/connect-wallet",
            "/api/set-address",
            "/api/settings",
            "/api/rentals/braiins/bid",
            "/api/upgrade/checkout",
            "/api/upgrade/webln/confirm",
        ),
    )
    def test_locked_posts(self, path):
        assert is_dangerous_mutation(path, "POST") is True

    @pytest.mark.parametrize(
        "path,method",
        (
            ("/api/snapshot", "GET"),
            ("/api/settings", "GET"),
            ("/api/pool/resolve", "POST"),
            ("/api/settings/test-webhook", "POST"),
            ("/api/settings/test-braiins", "POST"),
            ("/api/axe-fleet/devices/miner-1/refresh", "POST"),
            ("/api/axe-fleet/scan", "POST"),
            ("/api/axe-fleet/devices", "POST"),
            ("/api/agent/heartbeat", "POST"),
            ("/api/agent/commands/pull", "POST"),
            ("/api/devices/miner-1/test", "POST"),
            ("/api/devices/miner-1/command", "GET"),
        ),
    )
    def test_open_paths_stay_out_of_the_gate(self, path, method):
        assert is_dangerous_mutation(path, method) is False


class TestAnonymousAndLocalhost:
    @pytest.mark.parametrize("remote", ("127.0.0.1", "::1", "203.0.113.9"))
    def test_command_post_requires_principal(self, client, remote):
        response = client.post(
            "/api/devices/miner-1/command",
            json={"command": "restart"},
            environ_overrides={"REMOTE_ADDR": remote},
        )
        assert response.status_code == 401
        assert response.get_json()["code"] == "PRINCIPAL_REQUIRED"

    def test_pool_command_and_rollback_require_principal(self, client):
        pool = client.post(
            "/api/devices/miner-1/command",
            json={
                "command": "update_pool",
                "parameters": {"url": "stratum+tcp://x:3333"},
            },
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        rollback = client.post(
            "/api/devices/miner-1/commands/op-1/rollback",
            json={},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert pool.status_code == 401
        assert rollback.status_code == 401
        assert pool.get_json()["code"] == "PRINCIPAL_REQUIRED"

    @pytest.mark.parametrize("path", ("/api/connect-wallet", "/api/set-address"))
    def test_wallet_posts_require_principal(self, client, path):
        response = client.post(
            path,
            json={"address": "bc1q" + "a" * 39},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert response.status_code == 401
        assert response.get_json()["code"] == "PRINCIPAL_REQUIRED"

    @pytest.mark.parametrize(
        "path",
        (
            "/api/rentals/braiins/bid",
            "/api/upgrade/checkout",
            "/api/upgrade/webln/confirm",
        ),
    )
    def test_purchase_posts_require_principal(self, client, path):
        response = client.post(
            path,
            json={"plan": "pro", "method": "btc"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert response.status_code == 401
        assert response.get_json()["code"] == "PRINCIPAL_REQUIRED"

    @pytest.mark.parametrize(
        "path",
        (
            "/api/settings",
            "/api/axe-fleet/power-plugs/save-credentials",
        ),
    )
    def test_secret_posts_require_principal(self, client, path):
        response = client.post(
            path,
            json={"webhook_url": "https://example.invalid/hook"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert response.status_code == 401
        assert response.get_json()["code"] == "PRINCIPAL_REQUIRED"

    def test_fleet_command_post_requires_principal(self, client):
        response = client.post(
            "/api/axe-fleet/devices/miner-1/pause",
            json={"dry_run": True},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert response.status_code == 401
        assert response.get_json()["code"] == "PRINCIPAL_REQUIRED"


class TestSnapshotStaysOpen:
    def test_loopback_snapshot_without_key_is_200(self, client):
        response = client.get(
            "/api/snapshot",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert response.status_code == 200


class TestRealPrincipalPassesTheGate:
    def test_api_key_is_not_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", KEY)
        response = client.post(
            "/api/devices/missing-miner/command",
            json={"command": "restart"},
            headers={"X-API-Key": KEY},
            environ_overrides={"REMOTE_ADDR": "203.0.113.9"},
        )
        assert response.status_code != 401
        assert response.status_code == 404

    def test_tenant_api_key_is_not_401(self, client, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"default": KEY}))
        response = client.post(
            "/api/devices/missing-miner/command",
            json={"command": "restart"},
            headers={"X-API-Key": KEY},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert response.status_code == 404

    def test_wrong_api_key_stays_401_on_localhost(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", KEY)
        response = client.post(
            "/api/devices/miner-1/command",
            json={"command": "restart"},
            headers={"X-API-Key": "not-the-key"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert response.status_code == 401
        assert response.get_json()["code"] == "PRINCIPAL_REQUIRED"

    def test_access_jwt_is_not_401(self, client):
        from services.auth import create_token

        with app_module.app.app_context():
            token = create_token("operator-1")
        response = client.post(
            "/api/devices/missing-miner/command",
            json={"command": "restart"},
            headers={"Authorization": "Bearer " + token},
            environ_overrides={"REMOTE_ADDR": "203.0.113.9"},
        )
        assert response.status_code == 404

    def test_authenticated_session_is_not_401(self, client):
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["tenant_id"] = "default"
            sess["role"] = "admin"
        response = client.post(
            "/api/devices/missing-miner/command",
            json={"command": "restart"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.9"},
        )
        assert response.status_code == 404

    def test_localhost_without_session_is_not_a_principal(self):
        with app_module.app.test_request_context(
            "/api/devices/miner-1/command",
            method="POST",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            assert has_mutation_principal() is False
