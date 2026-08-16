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

    def test_register_blocks_new_devices_at_plan_cap(self, client, agent_token, registry):
        """Plan worker cap: when the tenant is at the limit, NEW devices are
        refused (blocked list) — the agent path must not bypass the plan the
        way manual POST /devices enforces it."""
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=False), \
                patch("axe_fleet.routes._get_tenant_plan",
                       return_value={"plan": "free", "max_workers": 5}):
            resp = client.post(
                "/api/agent/register",
                headers=_headers(agent_token),
                json={"devices": [
                    {"ip": "192.168.1.50", "model": "Bitaxe"},
                    {"ip": "192.168.1.60", "model": "Antminer S19"},
                ]},
            )
        assert resp.status_code == 201  # register stays 201, blocking is per-device
        data = resp.get_json()
        assert data["count"] == 0
        assert data["blocked_count"] == 2
        assert all(b["max_workers"] == 5 for b in data["blocked"])
        # Nothing persisted.
        assert registry.list_devices(tenant_id="acme") == []

    def test_register_refresh_of_existing_allowed_at_plan_cap(self, client, agent_token, registry):
        """At the cap, re-registering an ALREADY-REGISTERED IP must still
        refresh it (no new slot consumed) — only brand-new devices block."""
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=True):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.50"}]})
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=False):
            resp = client.post(
                "/api/agent/register",
                headers=_headers(agent_token),
                json={"devices": [
                    {"ip": "192.168.1.50", "model": "Bitaxe Gamma", "firmware": "AxeOS 3.2.0"},
                    {"ip": "192.168.1.60", "model": "NerdAxe"},
                ]},
            )
        data = resp.get_json()
        assert data["count"] == 1          # existing refreshed
        assert data["blocked_count"] == 1  # new blocked
        assert data["blocked"][0]["ip"] == "192.168.1.60"
        dev = registry.get_device_by_ip("192.168.1.50", tenant_id="acme")
        assert dev["model"] == "Bitaxe Gamma"  # refresh applied
        # get_device_by_ip returns {} (falsy) for a missing row.
        assert not registry.get_device_by_ip("192.168.1.60", tenant_id="acme")


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

    def test_telemetry_upsert_blocked_at_plan_cap(self, client, agent_token, registry):
        """At the plan cap an unknown IP must NOT be auto-created via the
        telemetry path (403 + no row) — otherwise telemetry would bypass the
        cap that register enforces."""
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=False), \
                patch("axe_fleet.routes._get_tenant_plan",
                       return_value={"plan": "free", "max_workers": 5}):
            resp = client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={"ip": "192.168.1.99", "telemetry": {"hashrate_hs": 1e9}},
            )
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "plan worker limit reached"
        # get_device_by_ip returns {} (falsy) for a missing row.
        assert not registry.get_device_by_ip("192.168.1.99", tenant_id="acme")

    def test_telemetry_existing_device_allowed_at_plan_cap(self, client, agent_token, registry):
        """Pushing telemetry for an EXISTING device at the cap stays allowed
        (it consumes no new slot) — the poll loop must never break for
        already-registered miners."""
        self._register_one(client, agent_token, registry)
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=False):
            resp = client.post(
                "/api/agent/telemetry",
                headers=_headers(agent_token),
                json={"ip": "192.168.1.50", "telemetry": {"hashrate_hs": 2e12}},
            )
        assert resp.status_code == 200
        dev = registry.get_device_by_ip("192.168.1.50", tenant_id="acme")
        assert dev["status"] == "ONLINE"

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


# ══════════════════════════════════════════════════════════════════════
#  Agent push → /api/snapshot fleet (write-through cache) — the fix
# ══════════════════════════════════════════════════════════════════════
# Root cause fixed: the snapshot fleet block was fed ONLY by the server-side
# poll (which skips agent-managed devices), so agent pushes reached the DB
# but never the dashboard. save_telemetry() now writes through to the cache.

class TestSnapshotWriteThrough:
    @pytest.fixture(autouse=True)
    def _clean(self):
        import app as app_module
        from services import state as shared_state
        for d in app_module._axe_registry.list_devices():
            app_module._axe_registry.remove_device(
                d["id"], tenant_id=d.get("tenant_id") or "default")
        shared_state.axe_telemetry_cache.clear()
        app_module.latest_snapshot.pop("axe_fleet", None)
        yield
        for d in app_module._axe_registry.list_devices():
            app_module._axe_registry.remove_device(
                d["id"], tenant_id=d.get("tenant_id") or "default")
        shared_state.axe_telemetry_cache.clear()
        app_module.latest_snapshot.pop("axe_fleet", None)

    def test_agent_push_reaches_snapshot_fleet(self, client, agent_token):
        """After the agent registers + pushes, the dashboard's snapshot
        fleet must contain the device with live telemetry."""
        import app as app_module
        from services import state as shared_state
        ip = "192.168.1.77"
        client.post("/api/agent/register", headers=_headers(agent_token),
                    json={"devices": [{"ip": ip, "model": "Gamma 900",
                                       "firmware": "AxeOS 2.13.0",
                                       "hostname": "gamma-01"}]})
        client.post("/api/agent/telemetry", headers=_headers(agent_token),
                    json={"ip": ip, "telemetry": {
                        "hashrate_hs": 912345678901, "temperature": 53.2,
                        "power_watts": 15.6, "fan_rpm": 4600,
                        "best_diff": "8.2T", "shares_accepted": 1450}})
        # _do_poll assembles snap.axe_fleet from the cache (app.py:3800);
        # simulate that single line — the write-through is what's under test.
        app_module.latest_snapshot["axe_fleet"] = list(
            shared_state.axe_telemetry_cache.values())

        viewer = create_token(subject="acme", extra_claims={"role": "admin"})
        resp = client.get("/api/snapshot", headers=_headers(viewer))
        assert resp.status_code == 200
        fleet = resp.get_json().get("axe_fleet") or []
        assert len(fleet) == 1, f"expected 1 device in snapshot fleet, got {fleet}"
        entry = fleet[0]
        assert entry["hashrate_hs"] == 912345678901
        assert entry["status"] == "ONLINE"
        assert entry["device_id"]                      # tenant-scoping key
        assert entry.get("hashrate") == 912345678901   # sidebar alias

    def test_snapshot_fleet_scoped_per_tenant(self, client, agent_token):
        """A tenant never sees another tenant's agent-pushed devices."""
        import app as app_module
        from services import state as shared_state
        ip = "192.168.1.78"
        client.post("/api/agent/register", headers=_headers(agent_token),
                    json={"devices": [{"ip": ip}]})
        client.post("/api/agent/telemetry", headers=_headers(agent_token),
                    json={"ip": ip, "telemetry": {"hashrate_hs": 1e9}})
        app_module.latest_snapshot["axe_fleet"] = list(
            shared_state.axe_telemetry_cache.values())

        mine = create_token(subject="acme", extra_claims={"role": "admin"})
        r = client.get("/api/snapshot", headers=_headers(mine))
        assert len(r.get_json().get("axe_fleet") or []) == 1
        other = create_token(subject="brave", extra_claims={"role": "admin"})
        r = client.get("/api/snapshot", headers=_headers(other))
        assert (r.get_json().get("axe_fleet") or []) == []

    def test_cache_seed_restores_after_restart(self, client, agent_token):
        """Boot seed repopulates the cache from the DB after a restart."""
        import app as app_module
        from services import state as shared_state
        ip = "192.168.1.79"
        client.post("/api/agent/register", headers=_headers(agent_token),
                    json={"devices": [{"ip": ip}]})
        client.post("/api/agent/telemetry", headers=_headers(agent_token),
                    json={"ip": ip, "telemetry": {"hashrate_hs": 5e12}})
        shared_state.axe_telemetry_cache.clear()        # simulated restart
        assert shared_state.axe_telemetry_cache == {}
        app_module._seed_axe_telemetry_cache(app_module._axe_registry)
        entries = list(shared_state.axe_telemetry_cache.values())
        assert len(entries) == 1
        assert entries[0]["hashrate_hs"] == 5e12
        assert entries[0]["device_id"]


# ══════════════════════════════════════════════════════════════════════
#  list_devices joins latest telemetry (Fix 3)
# ══════════════════════════════════════════════════════════════════════

class TestDevicesJoinTelemetry:
    def test_list_devices_with_telemetry_joins_latest(self, registry):
        dev = registry.upsert_agent_device("192.168.1.60", tenant_id="acme")
        registry.save_telemetry(dev["id"], {"hashrate_hs": 5e12, "temperature": 61.0},
                                tenant_id="acme")
        with_tel = registry.list_devices(tenant_id="acme", with_telemetry=True)
        assert with_tel[0]["telemetry"]["hashrate_hs"] == 5e12
        assert with_tel[0]["hashrate_hs"] == 5e12
        # Default stays cheap (no join) — poll path unchanged.
        plain = registry.list_devices(tenant_id="acme")
        assert "telemetry" not in plain[0]

    def test_devices_route_includes_telemetry(self, client, agent_token, user_token, registry):
        """The fleet list the grid renders must show live hashrate."""
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.60",
                                           "model": "Antminer S19j Pro"}]})
            client.post("/api/agent/telemetry", headers=_headers(agent_token),
                        json={"ip": "192.168.1.60", "telemetry": {
                            "hashrate_hs": 91_200_000_000, "temperature": 62.5,
                            "fan_rpm": 4200}})
            resp = client.get("/api/axe-fleet/devices", headers=_headers(user_token))
            assert resp.status_code == 200
            devs = resp.get_json()["devices"]
            assert len(devs) == 1
            d = devs[0]
            assert d["hashrate_hs"] == 91_200_000_000    # was None before the fix
            assert d["telemetry"]["temperature"] == 62.5

    def test_empty_heartbeat_does_not_erase_telemetry(self, registry):
        dev = registry.upsert_agent_device("192.168.1.61", tenant_id="acme")
        registry.save_telemetry(dev["id"], {"hashrate_hs": 5e12}, tenant_id="acme")
        # Fix 4: agent now pushes {} heartbeats — they must NOT be joined
        # as trusted telemetry (the last real reading wins).
        registry.save_telemetry(dev["id"], {}, tenant_id="acme")
        with_tel = registry.list_devices(tenant_id="acme", with_telemetry=True)
        assert with_tel[0]["telemetry"]["hashrate_hs"] == 5e12


class TestEmptyHeartbeatAccepted:
    def test_server_accepts_empty_telemetry_and_marks_idle(self, client, agent_token, registry):
        """Fix 4 contract: the agent pushes {} when a poll fails; the server
        must accept it (updating last_seen) instead of rejecting."""
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.80"}]})
            resp = client.post("/api/agent/telemetry", headers=_headers(agent_token),
                               json={"ip": "192.168.1.80", "telemetry": {}})
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "IDLE"
        dev = registry.get_device_by_ip("192.168.1.80", tenant_id="acme")
        assert dev["status"] == "IDLE"
        assert dev["last_seen"] > 0


# ══════════════════════════════════════════════════════════════════════
#  CFO audit fixes — command round-trip, heartbeat cache, caps by type,
#  agent_managed latency skip, re-scan ordering, tombstone (no zombies)
# ══════════════════════════════════════════════════════════════════════

class TestCommandPayloadCarriesIp:
    """Fix 1: the agent must receive the device's LAN ip_address in the
    pull payload — the registry UUID alone is useless for opening a socket."""

    def test_pull_commands_include_ip_address(self, client, agent_token, registry):
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.50"}]})
            dev = registry.get_device_by_ip("192.168.1.50", tenant_id="acme")
            registry.enqueue_agent_command(dev["id"], "restart", tenant_id="acme")
            pull = client.post("/api/agent/commands/pull",
                               headers=_headers(agent_token), json={})
            assert pull.status_code == 200
            cmds = pull.get_json()["commands"]
            assert len(cmds) == 1
            assert cmds[0]["ip_address"] == "192.168.1.50"

    def test_pull_missing_device_uses_empty_ip(self, client, agent_token, registry):
        """A queued command for a vanished device still pulls (empty ip) —
        the agent acks failure instead of the pull 500ing."""
        with patch("axe_fleet.routes._registry", registry):
            registry.enqueue_agent_command("ghost-device", "restart", tenant_id="acme")
            pull = client.post("/api/agent/commands/pull",
                               headers=_headers(agent_token), json={})
            assert pull.status_code == 200
            assert pull.get_json()["commands"][0]["ip_address"] == ""


class TestHeartbeatKeepsCacheHashrate:
    """Fix 2: a {} heartbeat must refresh status but NEVER wipe the last
    real hashrate from the snapshot cache (top bar / host core)."""

    def test_heartbeat_does_not_zero_cache_hashrate(self, client, agent_token):
        import app as app_module
        from services import state as shared_state
        for d in app_module._axe_registry.list_devices():
            app_module._axe_registry.remove_device(
                d["id"], tenant_id=d.get("tenant_id") or "default")
        shared_state.axe_telemetry_cache.clear()
        try:
            ip = "192.168.1.91"
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": ip}]})
            client.post("/api/agent/telemetry", headers=_headers(agent_token),
                        json={"ip": ip, "telemetry": {"hashrate_hs": 7e12}})
            # Poll hiccup → agent pushes {} heartbeat.
            client.post("/api/agent/telemetry", headers=_headers(agent_token),
                        json={"ip": ip, "telemetry": {}})
            entry = shared_state.axe_telemetry_cache.get(
                app_module._axe_registry.get_device_by_ip(ip, tenant_id="acme")["id"])
            assert entry["hashrate_hs"] == 7e12, "heartbeat wiped real hashrate!"
            assert entry["hashrate"] == 7e12
            assert entry["status"] == "IDLE"   # freshness flag still updates
        finally:
            for d in app_module._axe_registry.list_devices():
                app_module._axe_registry.remove_device(
                    d["id"], tenant_id=d.get("tenant_id") or "default")
            shared_state.axe_telemetry_cache.clear()

    def test_heartbeat_for_unknown_device_creates_idle_marker(self, client, agent_token):
        """Heartbeat with no prior data still marks the device present+IDLE
        (no hashrate invented, no crash)."""
        import app as app_module
        from services import state as shared_state
        shared_state.axe_telemetry_cache.clear()
        try:
            ip = "192.168.1.92"
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": ip}]})
            client.post("/api/agent/telemetry", headers=_headers(agent_token),
                        json={"ip": ip, "telemetry": {}})
            entry = shared_state.axe_telemetry_cache.get(
                app_module._axe_registry.get_device_by_ip(ip, tenant_id="acme")["id"])
            assert entry["status"] == "IDLE"
            assert entry.get("hashrate_hs") is None
        finally:
            for d in app_module._axe_registry.list_devices():
                app_module._axe_registry.remove_device(
                    d["id"], tenant_id=d.get("tenant_id") or "default")
            shared_state.axe_telemetry_cache.clear()


class TestCapabilitiesByType:
    """Fix 4: capabilities follow the device type — cgminer has no identify
    (its API has no such command), AxeOS does. No more dead buttons."""

    def test_cgminer_device_has_no_identify_cap(self, client, agent_token, registry):
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.55", "type": "cgminer",
                                           "model": "Antminer S19",
                                           "firmware": "Braiins OS+"}]})
        dev = registry.get_device_by_ip("192.168.1.55", tenant_id="acme")
        caps = dev["capabilities"]
        assert caps["restart"] is True
        assert caps["identify"] is False     # no identify in cgminer API
        assert caps["configure"] is False    # not AxeOS

    def test_bitaxe_device_keeps_identify_cap(self, client, agent_token, registry):
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.56", "type": "bitaxe",
                                           "model": "Gamma 900",
                                           "firmware": "AxeOS 2.13.0"}]})
        dev = registry.get_device_by_ip("192.168.1.56", tenant_id="acme")
        caps = dev["capabilities"]
        assert caps["restart"] is True
        assert caps["identify"] is True
        assert caps["configure"] is True

    def test_upsert_refresh_updates_caps_when_type_arrives(self, client, agent_token, registry):
        """A device first seen via telemetry-only upsert (no type) must get
        honest caps once a later register carries type=cgminer — otherwise
        the cgminer card would keep an identify button that always fails."""
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=True):
            # Telemetry-only upsert: no type → conservative (identify True).
            client.post("/api/agent/telemetry", headers=_headers(agent_token),
                        json={"ip": "192.168.1.57",
                              "telemetry": {"hashrate_hs": 1e9, "model": "Antminer S19"}})
        dev = registry.get_device_by_ip("192.168.1.57", tenant_id="acme")
        assert dev["capabilities"]["identify"] is True  # unknown type
        # Register now reports cgminer → caps must be recomputed.
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.57", "type": "cgminer",
                                           "model": "Antminer S19",
                                           "firmware": "Braiins OS+"}]})
        dev = registry.get_device_by_ip("192.168.1.57", tenant_id="acme")
        assert dev["capabilities"]["identify"] is False
        assert dev["capabilities"]["restart"] is True
        assert dev["capabilities"]["configure"] is False


class TestAgentManagedLatencySkip:
    """Fix 3: /health and /summary must not TCP-probe agent-managed IPs
    (unreachable from the cloud — it only added N×0.75s blocking)."""

    def _seed_agent_device(self, client, agent_token, registry):
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.60", "model": "Gamma"}]})
            client.post("/api/agent/telemetry", headers=_headers(agent_token),
                        json={"ip": "192.168.1.60", "telemetry": {"hashrate_hs": 1e9}})
        return registry.get_device_by_ip("192.168.1.60", tenant_id="acme")

    def test_health_skips_probe_for_agent_managed(self, client, agent_token, registry):
        self._seed_agent_device(client, agent_token, registry)
        with patch("axe_fleet.routes._probe_miner_latency_ms") as mock_probe, \
                patch("axe_fleet.routes._registry", registry):
            resp = client.get("/api/axe-fleet/health", headers=_headers(agent_token))
            mock_probe.assert_not_called()
        assert resp.status_code == 200
        data = resp.get_json()
        dev = next(d for d in data["device_health"] if d["id"] == registry.get_device_by_ip("192.168.1.60", tenant_id="acme")["id"])
        assert dev["latency_ms"] is None

    def test_summary_skips_probe_for_agent_managed(self, client, agent_token, registry):
        self._seed_agent_device(client, agent_token, registry)
        with patch("axe_fleet.routes._probe_miner_latency_ms") as mock_probe, \
                patch("axe_fleet.routes._registry", registry):
            resp = client.get("/api/axe-fleet/summary", headers=_headers(agent_token))
            mock_probe.assert_not_called()
        assert resp.status_code == 200


class TestTombstoneNoZombies:
    """Fix 6: a device the operator removed must stay removed — the agent
    path (register + telemetry) can't resurrect it; only a manual add can."""

    def test_removed_device_not_in_list(self, client, agent_token, registry):
        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.70"}]})
        dev = registry.get_device_by_ip("192.168.1.70", tenant_id="acme")
        assert registry.remove_device(dev["id"], tenant_id="acme") is True
        assert registry.get_device_by_ip("192.168.1.70", tenant_id="acme") == {}
        assert registry.list_devices(tenant_id="acme") == []

    def test_agent_register_refuses_tombstoned_ip(self, client, agent_token, registry):
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=True):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.71"}]})
        dev = registry.get_device_by_ip("192.168.1.71", tenant_id="acme")
        registry.remove_device(dev["id"], tenant_id="acme")
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=True):
            resp = client.post("/api/agent/register", headers=_headers(agent_token),
                               json={"devices": [{"ip": "192.168.1.71"}]})
        data = resp.get_json()
        assert data["count"] == 0
        assert any(b["ip"] == "192.168.1.71" and "removed" in b.get("error", "")
                   for b in data["blocked"]), f"no tombstone block: {data}"
        # Still gone — the agent could not resurrect it.
        assert registry.get_device_by_ip("192.168.1.71", tenant_id="acme") == {}

    def test_telemetry_for_tombstoned_ip_410(self, client, agent_token, registry):
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=True):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.72"}]})
        dev = registry.get_device_by_ip("192.168.1.72", tenant_id="acme")
        registry.remove_device(dev["id"], tenant_id="acme")
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=True):
            resp = client.post("/api/agent/telemetry", headers=_headers(agent_token),
                               json={"ip": "192.168.1.72", "telemetry": {"hashrate_hs": 1e9}})
        assert resp.status_code == 410
        assert resp.get_json()["removed"] is True
        assert registry.get_device_by_ip("192.168.1.72", tenant_id="acme") == {}

    def test_manual_add_revives_tombstoned_ip(self, client, agent_token, registry):
        """The operator explicitly re-adding a removed device via + ADD must
        work (tombstone cleared by the manual path)."""
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=True):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.73"}]})
        dev = registry.get_device_by_ip("192.168.1.73", tenant_id="acme")
        registry.remove_device(dev["id"], tenant_id="acme")
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes.AxeOSConnector") as mock_conn, \
                patch("axe_fleet.routes._can_add_worker", return_value=True):
            mock_conn.side_effect = Exception("unreachable")
            resp = client.post("/api/axe-fleet/devices", headers=_headers(agent_token),
                               json={"ip_address": "192.168.1.73", "name": "Revived"})
        assert resp.status_code == 201, resp.get_json()
        revived = registry.get_device_by_ip("192.168.1.73", tenant_id="acme")
        assert revived, "manual add did not revive the IP"
        assert revived["name"] == "Revived"

    def test_removed_device_frees_plan_slot(self, client, agent_token, registry,
                                            monkeypatch, tmp_path):
        """A tombstoned device must not count against the worker cap.
        Hermetic: point services.tenant's DB at the SAME scratch file the
        registry fixture uses, so the count reflects this test's rows only."""
        import services.tenant as tenant_mod
        conn = registry._get_db()
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        conn.close()

        def _same_db():
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            return c

        monkeypatch.setattr(tenant_mod, "_db_conn", _same_db)
        with patch("axe_fleet.routes._registry", registry), \
                patch("axe_fleet.routes._can_add_worker", return_value=True):
            client.post("/api/agent/register", headers=_headers(agent_token),
                        json={"devices": [{"ip": "192.168.1.74"}]})
        assert tenant_mod.count_tenant_workers("acme") == 1
        dev = registry.get_device_by_ip("192.168.1.74", tenant_id="acme")
        registry.remove_device(dev["id"], tenant_id="acme")
        assert tenant_mod.count_tenant_workers("acme") == 0

    def test_gc_purges_old_tombstones_and_telemetry(self, registry):
        """Soft-deleted rows older than the GC window are physically purged
        (row + telemetry) so the tombstone guard never grows the DB forever."""
        dev = registry.upsert_agent_device("192.168.1.75", tenant_id="acme")
        registry.save_telemetry(dev["id"], {"hashrate_hs": 1e9}, tenant_id="acme")
        assert registry.remove_device(dev["id"], tenant_id="acme") is True
        # Fresh tombstone survives the GC.
        assert registry.gc_tombstones(max_age_days=30) == 0
        assert registry.get_removed_by_ip("192.168.1.75", tenant_id="acme")
        # Age it past the window and re-run.
        conn = registry._get_db()
        c = conn.cursor()
        c.execute("UPDATE axe_devices SET removed_at=? WHERE id=?",
                  (int(time.time()) - 31 * 86400, dev["id"]))
        conn.commit()
        conn.close()
        assert registry.gc_tombstones(max_age_days=30) == 1
        assert registry.get_removed_by_ip("192.168.1.75", tenant_id="acme") == {}
        assert registry.get_recent_telemetry(dev["id"], tenant_id="acme") == []
