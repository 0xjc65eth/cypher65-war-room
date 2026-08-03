"""
CYPHER65 // SaaS AGENT — Test Suite
===================================
The cloud dashboard (Render) cannot reach the user's home LAN, so a LOCAL
agent connects OUT and pushes telemetry. Tests:

- POST /api/agent/token       — logged-in user mints a long-lived agent JWT
- POST /api/agent/register    — agent registers discovered devices (tenant-scoped)
- POST /api/agent/telemetry   — agent pushes telemetry (status ONLINE/IDLE)
- POST /api/agent/commands/pull + /ack — queued command round-trip
- _poll_axe_fleet()           — server poll SKIPS agent_managed devices
- Tenant isolation            — tenant A never sees tenant B via the agent API
"""
import json
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

from app import app as _app
from services.auth import create_token, verify_token
from services.tenant import get_current_role
from axe_fleet.registry import DeviceRegistry


@pytest.fixture
def client(monkeypatch):
    """Test client with pinned JWT secret (app.config + env, in sync)."""
    _app.config["TESTING"] = True
    saved = _app.config.get("JWT_SECRET_KEY")
    _app.config["JWT_SECRET_KEY"] = "agent-test-secret-123"
    monkeypatch.setenv("SECRET_KEY", "agent-test-secret-123")
    c = _app.test_client()
    yield c
    if saved is not None:
        _app.config["JWT_SECRET_KEY"] = saved
    else:
        _app.config.pop("JWT_SECRET_KEY", None)


@pytest.fixture
def user_token():
    """A logged-in user token for tenant 'acme' (role admin → member+)."""
    return create_token(subject="acme", extra_claims={"role": "admin"})


@pytest.fixture
def agent_token():
    """An agent JWT for tenant 'acme' (as minted by /api/agent/token)."""
    return create_token(
        subject="acme", ttl=365 * 86400,
        extra_claims={"agent": True, "role": "agent"},
    )


@pytest.fixture
def registry(tmp_path):
    """Real DeviceRegistry on a scratch SQLite file (hermetic)."""
    db_path = str(tmp_path / "agent.sqlite")

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    r = DeviceRegistry(get_db)
    r.ensure_tables()
    return r


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════
#  POST /api/agent/token
# ══════════════════════════════════════════════════════════════════════

class TestAgentToken:
    def test_logged_in_user_mints_agent_token(self, client, user_token):
        resp = client.post("/api/agent/token", headers=_headers(user_token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["tenant_id"] == "acme"
        assert data["expires_in"] == 365 * 86400
        payload = verify_token(data["token"], expected_type="access")
        assert payload is not None
        assert payload["sub"] == "acme"
        assert payload["agent"] is True  # distinguishes agent from user tokens

    def test_minted_token_works_on_agent_routes(self, client, user_token, registry):
        """The token returned by /token must be accepted by _require_agent."""
        mint = client.post("/api/agent/token", headers=_headers(user_token)).get_json()
        with patch("axe_fleet.routes._registry", registry):
            resp = client.post(
                "/api/agent/register",
                headers=_headers(mint["token"]),
                json={"devices": [{"ip": "192.168.1.50", "model": "Bitaxe"}]},
            )
            assert resp.status_code == 201
            assert resp.get_json()["count"] == 1


# ══════════════════════════════════════════════════════════════════════
#  POST /api/agent/register
# ══════════════════════════════════════════════════════════════════════

class TestAgentRegister:
    def test_requires_agent_token(self, client):
        resp = client.post("/api/agent/register",
                           json={"devices": [{"ip": "192.168.1.50"}]})
        assert resp.status_code == 401

    def test_rejects_user_token(self, client, user_token):
        """A plain user JWT (no agent claim) must NOT authenticate the agent."""
        resp = client.post("/api/agent/register",
                           headers=_headers(user_token),
                           json={"devices": [{"ip": "192.168.1.50"}]})
        assert resp.status_code == 401

    def test_registers_devices_tenant_scoped(self, client, agent_token, registry):
        with patch("axe_fleet.routes._registry", registry):
            resp = client.post(
                "/api/agent/register",
                headers=_headers(agent_token),
                json={"devices": [
                    {"ip": "192.168.1.50", "model": "Bitaxe", "firmware": "AxeOS 3.1.4"},
                    {"ip": "192.168.1.60", "model": "Antminer S19", "hostname": "s19-01"},
                ]},
            )
            assert resp.status_code == 201
            data = resp.get_json()
            assert data["count"] == 2
        # Devices landed in tenant acme, marked agent-managed.
        devices = registry.list_devices(tenant_id="acme")
        assert len(devices) == 2
        ips = {d["ip_address"] for d in devices}
        assert ips == {"192.168.1.50", "192.168.1.60"}
        assert all(int(d.get("agent_managed", 0) or 0) == 1 for d in devices)

    def test_register_is_idempotent_by_ip(self, client, agent_token, registry):
        with patch("axe_fleet.routes._registry", registry):
            for _ in range(2):
                r = client.post("/api/agent/register", headers=_headers(agent_token),
                                json={"devices": [{"ip": "192.168.1.50"}]})
                assert r.status_code == 201
        assert len(registry.list_devices(tenant_id="acme")) == 1

    def test_re_register_updates_firmware(self, client, agent_token, registry):
        """Re-registering an existing IP must persist firmware/version
        updates (regression: update_device dropped those fields silently)."""
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.50",
                                           "firmware": "AxeOS 3.1.4"}]})
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.50",
                                           "firmware": "AxeOS 3.2.0",
                                           "version": "3.2.0"}]})
        dev = registry.get_device_by_ip("192.168.1.50", tenant_id="acme")
        assert dev["firmware"] == "AxeOS 3.2.0"
        assert dev["firmware_version"] == "3.2.0"


# ══════════════════════════════════════════════════════════════════════
#  POST /api/agent/telemetry
# ══════════════════════════════════════════════════════════════════════

class TestAgentTelemetry:
    def _register_one(self, client, agent_token, registry, ip="192.168.1.50"):
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": ip}]})

    def test_telemetry_marks_online(self, client, agent_token, registry):
        self._register_one(client, agent_token, registry)
        with patch("axe_fleet.routes._registry", registry):
            resp = client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={"ip": "192.168.1.50", "telemetry": {
                    "hashrate_hs": 500_000_000_000, "temperature": 62.0,
                    "fan_rpm": 4200, "power_watts": 45.0,
                }},
            )
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "ONLINE"
        dev = registry.get_device_by_ip("192.168.1.50", tenant_id="acme")
        assert dev["status"] == "ONLINE"

    def test_telemetry_idle_when_no_hashrate(self, client, agent_token, registry):
        self._register_one(client, agent_token, registry)
        with patch("axe_fleet.routes._registry", registry):
            resp = client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={"ip": "192.168.1.50", "telemetry": {"hashrate_hs": 0}},
            )
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "IDLE"

    def test_telemetry_upserts_unknown_device(self, client, agent_token, registry):
        """Agent may report a device whose row vanished (server DB reset)."""
        with patch("axe_fleet.routes._registry", registry):
            resp = client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={"ip": "192.168.1.99", "telemetry": {"hashrate_hs": 1e9,
                                                         "model": "Bitaxe"}},
            )
            assert resp.status_code == 200
        assert registry.get_device_by_ip("192.168.1.99", tenant_id="acme") is not None

    def test_telemetry_requires_body(self, client, agent_token):
        resp = client.post("/api/agent/telemetry", headers=_headers(agent_token),
                           json={"ip": "192.168.1.50"})
        assert resp.status_code == 400

    def test_telemetry_requires_agent_token(self, client):
        resp = client.post("/api/agent/telemetry",
                           json={"ip": "x", "telemetry": {}})
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
#  Command queue: enqueue (server) → pull (agent) → ack (agent)
# ══════════════════════════════════════════════════════════════════════

class TestAgentCommands:
    def _registered_device(self, client, agent_token, registry):
        self._reg = registry
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.50"}]})
        return registry.get_device_by_ip("192.168.1.50", tenant_id="acme")

    def test_pull_and_ack_round_trip(self, client, agent_token, registry):
        dev = self._registered_device(client, agent_token, registry)
        # Server queues a restart for the agent-managed device.
        queued = registry.enqueue_agent_command(dev["id"], "restart",
                                                tenant_id="acme")
        assert queued["status"] == "pending"

        with patch("axe_fleet.routes._registry", registry):
            pull = client.post("/api/agent/commands/pull",
                               headers=_headers(agent_token), json={})
            assert pull.status_code == 200
            cmds = pull.get_json()["commands"]
            assert len(cmds) == 1
            assert cmds[0]["command"] == "restart"
            assert cmds[0]["device_id"] == dev["id"]

            ack = client.post(f"/api/agent/commands/{cmds[0]['id']}/ack",
                              headers=_headers(agent_token),
                              json={"success": True, "result": "HTTP 200"})
            assert ack.status_code == 200
            assert ack.get_json()["success"] is True

        # Command no longer pending; second pull returns nothing.
        with patch("axe_fleet.routes._registry", registry):
            pull2 = client.post("/api/agent/commands/pull",
                                headers=_headers(agent_token), json={})
            assert pull2.get_json()["commands"] == []

    def test_pull_isolated_by_tenant(self, client, registry):
        """Tenant A pulling commands must not see tenant B's queue."""
        dev_a = registry.upsert_agent_device("192.168.1.10", tenant_id="acme")
        registry.upsert_agent_device("192.168.1.20", tenant_id="brave")
        registry.enqueue_agent_command(dev_a["id"], "identify", tenant_id="acme")

        token_a = create_token(subject="acme", ttl=86400,
                               extra_claims={"agent": True, "role": "agent"})
        token_b = create_token(subject="brave", ttl=86400,
                               extra_claims={"agent": True, "role": "agent"})

        with patch("axe_fleet.routes._registry", registry):
            pull_a = client.post("/api/agent/commands/pull",
                                 headers=_headers(token_a), json={}).get_json()
            pull_b = client.post("/api/agent/commands/pull",
                                 headers=_headers(token_b), json={}).get_json()
        assert len(pull_a["commands"]) == 1
        assert pull_b["commands"] == []

    def test_duplicate_ack_is_idempotent(self, client, agent_token, registry):
        """A network retry re-sends the ack — it must return 200, not 404."""
        dev = self._registered_device(client, agent_token, registry)
        queued = registry.enqueue_agent_command(dev["id"], "restart",
                                                tenant_id="acme")
        with patch("axe_fleet.routes._registry", registry):
            pull = client.post("/api/agent/commands/pull",
                               headers=_headers(agent_token), json={}).get_json()
            cmd_id = pull["commands"][0]["id"]
            ack1 = client.post(f"/api/agent/commands/{cmd_id}/ack",
                               headers=_headers(agent_token),
                               json={"success": True, "result": "HTTP 200"})
            ack2 = client.post(f"/api/agent/commands/{cmd_id}/ack",
                               headers=_headers(agent_token),
                               json={"success": True, "result": "HTTP 200"})
        assert ack1.status_code == 200
        assert ack2.status_code == 200  # idempotent: no false 404
        assert ack2.get_json()["success"] is True

    def test_ack_wrong_tenant_404(self, client, registry):
        dev = registry.upsert_agent_device("192.168.1.10", tenant_id="acme")
        q = registry.enqueue_agent_command(dev["id"], "restart", tenant_id="acme")
        # Another tenant's agent tries to ack it.
        token_b = create_token(subject="brave", ttl=86400,
                               extra_claims={"agent": True, "role": "agent"})
        with patch("axe_fleet.routes._registry", registry):
            resp = client.post(f"/api/agent/commands/{q['id']}/ack",
                               headers=_headers(token_b),
                               json={"success": True, "result": "nope"})
            assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
#  Agent assets: one-line installer + stdlib-only agent.py download
# ══════════════════════════════════════════════════════════════════════

class TestAgentAssets:
    def test_install_script_served(self, client):
        resp = client.get("/agent/install.sh")
        assert resp.status_code == 200
        assert b"curl -sSL" in resp.data or b"CYPHER65_AGENT_TOKEN" in resp.data

    def test_agent_py_served_and_stdlib(self, client):
        resp = client.get("/agent/agent.py")
        assert resp.status_code == 200
        src = resp.data.decode()
        # Zero-dependency promise: no third-party imports.
        assert "import requests" not in src
        assert "urllib.request" in src

    def test_install_script_is_executable_bash(self, client):
        resp = client.get("/agent/install.sh")
        assert resp.status_code == 200
        text = resp.data.decode()
        assert text.lstrip().startswith("#!/usr/bin/env bash")
        assert "systemctl" in text or "launchctl" in text  # service wiring


# ══════════════════════════════════════════════════════════════════════
#  Server poll skip: agent_managed devices are polled by the LOCAL agent
# ══════════════════════════════════════════════════════════════════════

class TestPollSkip:
    def test_agent_managed_devices_are_not_polled(self, monkeypatch):
        import app as app_module
        from services import state

        # One agent-managed device + one server-polled device.
        agent_dev = {"id": "agent-1", "agent_managed": 1}
        normal_dev = {"id": "normal-1", "agent_managed": 0}

        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [agent_dev, normal_dev]

        monkeypatch.setattr(app_module, "_axe_registry", mock_registry)
        state.axe_last_poll_ts.clear()
        state.axe_telemetry_cache.clear()

        # Give the normal device a first poll (so its interval is fresh).
        app_module._poll_axe_fleet(int(time.time()))
        # Second tick: normal device within interval → still no poll_device.
        app_module._poll_axe_fleet(int(time.time()) + 10)

        # The agent-managed device must NEVER be polled by the server.
        for call in mock_registry.poll_device.call_args_list:
            assert "agent-1" not in call.args, "agent-managed device was polled!"

        # A fresh tick after the interval passes polls the normal device only.
        state.axe_last_poll_ts["normal-1"] = 0
        state.axe_last_poll_ts["agent-1"] = 0
        app_module._poll_axe_fleet(int(time.time()) + 120)
        polled_ids = [c.args[0] for c in mock_registry.poll_device.call_args_list]
        assert "normal-1" in polled_ids
        assert "agent-1" not in polled_ids


# ══════════════════════════════════════════════════════════════════════
#  /docs/agent — guia do usuário renderizado dentro do app
# ══════════════════════════════════════════════════════════════════════

class TestDocsAgent:
    def test_docs_agent_renders_guide(self, client):
        """GET /docs/agent returns the rendered markdown guide (200)."""
        resp = client.get("/docs/agent")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Template chrome present.
        assert "CYPHER65" in html
        assert "VOLTAR AO DASHBOARD" in html
        # Markdown source was converted: headings, code, table.
        assert "<h1" in html
        assert "<h2" in html
        assert "<pre" in html
        assert "<table" in html
        # Real guide content survived conversion (one-liner + docker + FAQ).
        assert "curl -sSL" in html
        assert "ghcr.io/0xjc65eth/cypher65-agent" in html
        assert "Perguntas frequentes" in html

    def test_docs_agent_guide_is_public(self, client):
        """The guide needs no auth — users read it before installing."""
        resp = client.get("/docs/agent")
        assert resp.status_code == 200
        # No login redirect (302 to /login or similar).
        assert resp.status_code != 302

    def test_docs_agent_missing_file_404(self, client, monkeypatch):
        """If the guide file is absent the route 404s instead of crashing."""
        import app as app_module
        monkeypatch.setattr(app_module, "_GUIDE_MD_PATH", "/nonexistent/guide.md")
        resp = client.get("/docs/agent")
        assert resp.status_code == 404
