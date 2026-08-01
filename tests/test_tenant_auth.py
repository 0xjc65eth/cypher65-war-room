"""
CYPHER65 // Tenant Auth — Test Suite (Fase 4 · B1)
====================================================
Tests for the multi-tenant login flow:

- resolve_tenant_for_api_key(): TENANT_API_KEYS JSON + legacy API_KEY fallback
- POST /api/auth/login → token sub == tenant_id + tenant_id in response
- POST /api/auth/refresh → preserves the original tenant_id subject
- axe_fleet _get_tenant_id(): reads sub from Authorization Bearer
- DeviceRegistry isolation: tenant A never sees tenant B devices

Strategy:
  - monkeypatch.setenv for TENANT_API_KEYS / API_KEY / SECRET_KEY
  - Flask test_client for endpoint tests
  - DeviceRegistry with an in-memory SQLite get_db callable
"""
import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from services.auth import (
    resolve_tenant_for_api_key,
    verify_token,
    create_token,
    authenticate_with_api_key,
)
from axe_fleet.registry import DeviceRegistry

import app as _app_module

app = _app_module.app


@pytest.fixture
def client():
    """Return a Flask test client configured for testing."""
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "tenant-test-secret"
    with app.test_client() as c:
        yield c


# ══════════════════════════════════════════════════════════════════════
#  resolve_tenant_for_api_key
# ══════════════════════════════════════════════════════════════════════

class TestResolveTenantForKey:
    def test_legacy_api_key_maps_to_default(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "legacy-key-1")
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        assert resolve_tenant_for_api_key("legacy-key-1") == "default"

    def test_unknown_key_returns_none(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "legacy-key-1")
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        assert resolve_tenant_for_api_key("wrong-key") is None

    def test_empty_key_returns_none(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "legacy-key-1")
        assert resolve_tenant_for_api_key("") is None
        assert resolve_tenant_for_api_key(None) is None

    def test_no_key_configured_returns_none(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        assert resolve_tenant_for_api_key("anything") is None

    def test_tenant_keys_json_maps_to_tenant(self, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", json.dumps({
            "acme": "key-acme-1",
            "brave": "key-brave-2",
        }))
        monkeypatch.delenv("API_KEY", raising=False)
        assert resolve_tenant_for_api_key("key-acme-1") == "acme"
        assert resolve_tenant_for_api_key("key-brave-2") == "brave"

    def test_tenant_keys_unknown_key_returns_none(self, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"acme": "key-acme-1"}))
        monkeypatch.delenv("API_KEY", raising=False)
        assert resolve_tenant_for_api_key("key-nobody-9") is None

    def test_invalid_json_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", "not-json{{{")
        monkeypatch.setenv("API_KEY", "legacy-key-1")
        assert resolve_tenant_for_api_key("legacy-key-1") == "default"


# ══════════════════════════════════════════════════════════════════════
#  POST /api/auth/login — per-tenant token
# ══════════════════════════════════════════════════════════════════════

class TestLoginTenant:
    def test_login_returns_tenant_id(self, client, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"acme": "key-acme-1"}))
        monkeypatch.setenv("SECRET_KEY", "tenant-test-secret")
        res = client.post("/api/auth/login", json={"api_key": "key-acme-1"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["tenant_id"] == "acme"
        assert "access_token" in data

    def test_login_token_sub_is_tenant_id(self, client, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"acme": "key-acme-1"}))
        monkeypatch.setenv("SECRET_KEY", "tenant-test-secret")
        res = client.post("/api/auth/login", json={"api_key": "key-acme-1"})
        token = res.get_json()["access_token"]
        payload = verify_token(token, expected_type="access")
        assert payload is not None
        assert payload["sub"] == "acme"

    def test_login_legacy_key_maps_to_default_tenant(self, client, monkeypatch):
        monkeypatch.setenv("API_KEY", "legacy-key-1")
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        monkeypatch.setenv("SECRET_KEY", "tenant-test-secret")
        res = client.post("/api/auth/login", json={"api_key": "legacy-key-1"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["tenant_id"] == "default"
        payload = verify_token(data["access_token"], expected_type="access")
        assert payload["sub"] == "default"

    def test_login_unknown_key_401(self, client, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"acme": "key-acme-1"}))
        res = client.post("/api/auth/login", json={"api_key": "key-nobody"})
        assert res.status_code == 401

    def test_login_missing_key_400(self, client, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"acme": "key-acme-1"}))
        res = client.post("/api/auth/login", json={})
        assert res.status_code == 400

    def test_login_disabled_without_keys(self, client, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        res = client.post("/api/auth/login", json={"api_key": "anything"})
        assert res.status_code == 503


class TestRefreshTenant:
    def test_refresh_preserves_tenant_subject(self, client, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"acme": "key-acme-1"}))
        monkeypatch.setenv("SECRET_KEY", "tenant-test-secret")
        login = client.post("/api/auth/login", json={"api_key": "key-acme-1"}).get_json()
        refresh_token = login["refresh_token"]

        res = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert res.status_code == 200
        data = res.get_json()
        assert data["tenant_id"] == "acme"
        payload = verify_token(data["access_token"], expected_type="access")
        assert payload["sub"] == "acme"


# ══════════════════════════════════════════════════════════════════════
#  authenticate_with_api_key — X-API-Key header
# ══════════════════════════════════════════════════════════════════════

class TestAuthenticateWithApiKey:
    def test_passes_when_no_key_configured(self, monkeypatch):
        """No API_KEY/TENANT_API_KEYS → open access (unchanged legacy behavior)."""
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        with Flask("test").test_request_context("/", headers={"X-API-Key": "anything"}):
            assert authenticate_with_api_key() is True

    def test_valid_legacy_key(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "legacy-key-1")
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        with Flask("test").test_request_context("/", headers={"X-API-Key": "legacy-key-1"}):
            assert authenticate_with_api_key() is True

    def test_invalid_key_rejected(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "legacy-key-1")
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        with Flask("test").test_request_context("/", headers={"X-API-Key": "wrong"}):
            assert authenticate_with_api_key() is False

    def test_valid_tenant_key(self, monkeypatch):
        monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"acme": "key-acme-1"}))
        monkeypatch.delenv("API_KEY", raising=False)
        with Flask("test").test_request_context("/", headers={"X-API-Key": "key-acme-1"}):
            assert authenticate_with_api_key() is True

    def test_no_header_rejected_when_configured(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "legacy-key-1")
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)
        with Flask("test").test_request_context("/"):
            assert authenticate_with_api_key() is False


# ══════════════════════════════════════════════════════════════════════
#  axe_fleet _get_tenant_id — reads sub from Authorization Bearer
# ══════════════════════════════════════════════════════════════════════

class TestGetTenantId:
    def test_bearer_token_is_used_as_tenant(self, client, monkeypatch):
        """list_devices receives tenant_id derived from the Bearer token."""
        monkeypatch.setenv("SECRET_KEY", "tenant-test-secret")
        token = create_token(subject="acme")

        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(
                "/api/axe-fleet/devices",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["tenant_id"] == "acme"
            mock_registry.list_devices.assert_called_once_with(tenant_id="acme")

    def test_no_token_falls_back_to_default(self, client, monkeypatch):
        """Without a token, tenant defaults to 'default' (single-user mode)."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get("/api/axe-fleet/devices")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["tenant_id"] == "default"
            mock_registry.list_devices.assert_called_once_with(tenant_id="default")

    def test_invalid_token_falls_back_to_default(self, client, monkeypatch):
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(
                "/api/axe-fleet/devices",
                headers={"Authorization": "Bearer not.a.real.token"},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["tenant_id"] == "default"


# ══════════════════════════════════════════════════════════════════════
#  DeviceRegistry — real tenant isolation at the persistence layer
# ══════════════════════════════════════════════════════════════════════

class TestRegistryIsolation:
    @pytest.fixture
    def registry(self, tmp_path):
        db_path = str(tmp_path / "tenant_isolation.sqlite")

        def get_db():
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn

        # Hermetic: never attempt a real socket connect to 192.168.1.x —
        # force add_device() to take the OFFLINE path immediately.
        from axe_fleet.connector import AxeOSConnectorError

        class _FakeConn:
            def fetch_info(self):
                raise AxeOSConnectorError("hermetic")

            def detect_capabilities(self):
                return {}

        with patch("axe_fleet.registry.AxeOSConnector", return_value=_FakeConn()):
            r = DeviceRegistry(get_db)
            r.ensure_tables()
            yield r

    def _add_device(self, registry, name, tenant, ip_suffix):
        """Add a device via the registry and return the stored device dict."""
        return registry.add_device(
            ip_address=f"192.168.1.{ip_suffix}",
            name=name,
            tenant_id=tenant,
        )

    def test_tenant_a_does_not_see_tenant_b_devices(self, registry):
        self._add_device(registry, "Alice Miner", "acme", 10)
        self._add_device(registry, "Bob Miner", "brave", 20)

        devices_a = registry.list_devices(tenant_id="acme")
        devices_b = registry.list_devices(tenant_id="brave")

        a_names = {d["name"] for d in devices_a}
        b_names = {d["name"] for d in devices_b}
        assert "Alice Miner" in a_names
        assert "Bob Miner" not in a_names
        assert "Bob Miner" in b_names
        assert "Alice Miner" not in b_names

    def test_default_tenant_isolated_from_named_tenants(self, registry):
        self._add_device(registry, "Default Device", "default", 30)
        named = registry.list_devices(tenant_id="acme")
        assert len(named) == 0

    def test_remove_device_scoped_to_tenant(self, registry):
        a = self._add_device(registry, "Alice Miner", "acme", 10)
        b = self._add_device(registry, "Bob Miner", "brave", 20)
        a_id = a["id"]
        b_id = b["id"]
        assert a_id != b_id

        # Attempt removal of A's device while authenticated as tenant B
        removed = registry.remove_device(a_id, tenant_id="brave")
        assert removed is False  # dev-a1 belongs to acme, not brave
        assert len(registry.list_devices(tenant_id="acme")) == 1

        # Correct tenant removes it
        removed = registry.remove_device(a_id, tenant_id="acme")
        assert removed is True
        assert registry.list_devices(tenant_id="acme") == []
        # Bob's device is untouched
        assert len(registry.list_devices(tenant_id="brave")) == 1
        assert registry.get_device(b_id, tenant_id="brave") is not None
