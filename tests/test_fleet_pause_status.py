"""Tests for Issue #13 — Fleet card must reflect PAUSED after Pause.

Covers the full propagation chain:
  1. derive_device_status() — PAUSED wins over hashrate (the core rule).
  2. AxeOSConnector.extract_telemetry() — captures miningPaused from /system/info.
  3. DeviceRegistry.poll_device() — derives PAUSED (not IDLE/ONLINE) when the
     device reports miningPaused=true.
  4. POST /api/axe-fleet/devices/<id>/pause — flips the DB row + snapshot cache
     to PAUSED immediately (never waits for the next poll).
  5. POST .../resume — re-polls and derives ONLINE/IDLE from the real hashrate.
  6. Agent telemetry push — derives PAUSED from miningPaused in the payload.
"""

import json
import sqlite3

import pytest
from unittest.mock import MagicMock, patch

from axe_fleet.models import (
    STATUS_PAUSED,
    STATUS_ONLINE,
    STATUS_OFFLINE,
    derive_device_status,
    new_telemetry,
)


# ══════════════════════════════════════════════════════════════════════════
# 1. derive_device_status — pure helper
# ══════════════════════════════════════════════════════════════════════════
class TestDeriveDeviceStatus:
    def test_mining_paused_wins_even_with_hashrate(self):
        """PAUSED must beat a stale hashrate (explicit operator intent)."""
        tel = new_telemetry("d")
        tel["hashrate_hs"] = 1.2e12
        tel["mining_paused"] = True
        assert derive_device_status(tel) == STATUS_PAUSED

    def test_mining_paused_with_zero_hashrate(self):
        tel = new_telemetry("d")
        tel["hashrate_hs"] = 0
        tel["mining_paused"] = True
        assert derive_device_status(tel) == STATUS_PAUSED

    def test_hashing_is_online(self):
        tel = new_telemetry("d")
        tel["hashrate_hs"] = 5e11
        tel["mining_paused"] = False
        assert derive_device_status(tel) == STATUS_ONLINE

    def test_idle_when_zero_hashrate(self):
        tel = new_telemetry("d")
        tel["hashrate_hs"] = 0
        assert derive_device_status(tel) == "IDLE"

    def test_empty_telemetry_is_idle(self):
        assert derive_device_status(None) == "IDLE"
        assert derive_device_status({}) == "IDLE"

    def test_string_false_never_pauses(self):
        """`bool("false")` is True in Python — a stringy value must not pause."""
        tel = new_telemetry("d")
        tel["hashrate_hs"] = 1e12
        tel["mining_paused"] = "false"
        assert derive_device_status(tel) == STATUS_ONLINE

    def test_mining_paused_true_is_strict(self):
        tel = new_telemetry("d")
        tel["hashrate_hs"] = 0
        tel["mining_paused"] = 1  # int 1 is NOT the JSON boolean True
        assert derive_device_status(tel) == "IDLE"

    def test_explicit_hashrate_override(self):
        tel = {"mining_paused": False}
        assert derive_device_status(tel, hashrate=2e12) == STATUS_ONLINE
        assert derive_device_status(tel, hashrate=0) == "IDLE"


# ══════════════════════════════════════════════════════════════════════════
# 2. connector extract_telemetry — captures miningPaused
# ══════════════════════════════════════════════════════════════════════════
class TestConnectorExtractMiningPaused:
    def _extract(self, info):
        from axe_fleet.connector import AxeOSConnector

        with patch.object(AxeOSConnector, "fetch_info", return_value=info):
            return AxeOSConnector("192.168.1.100").extract_telemetry()

    def test_extracts_mining_paused_true(self):
        tel = self._extract({"miningPaused": True, "hashrate": 0})
        assert tel["mining_paused"] is True

    def test_extracts_mining_paused_false(self):
        tel = self._extract({"miningPaused": False, "hashrate": 1e12})
        assert tel["mining_paused"] is False

    def test_missing_field_defaults_false(self):
        tel = self._extract({"hashrate": 1e12})
        assert tel["mining_paused"] is False

    def test_string_false_not_paused(self):
        tel = self._extract({"miningPaused": "false", "hashrate": 1e12})
        assert tel["mining_paused"] is False


# ══════════════════════════════════════════════════════════════════════════
# 3. registry poll_device — derives PAUSED from miningPaused
# ══════════════════════════════════════════════════════════════════════════
def _make_registry(tmp_path):
    db_path = tmp_path / "test_pause.sqlite"

    def _get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # registry expects sqlite3.Row rows
        return conn

    reg = __import__("axe_fleet.registry", fromlist=["DeviceRegistry"]).DeviceRegistry(
        _get_db
    )
    reg.ensure_tables()
    return reg, db_path


class TestRegistryPollPaused:
    def test_poll_device_marks_paused(self, tmp_path):
        reg, _ = _make_registry(tmp_path)
        dev = reg.add_device("192.168.1.99", "Paused-Bitaxe", tenant_id="t1")
        assert dev["status"] == STATUS_OFFLINE

        class FakeConn:
            def __init__(self, ip):
                pass

            def extract_telemetry(self):
                tel = new_telemetry(dev["id"])
                tel["hashrate_hs"] = 0
                tel["mining_paused"] = True
                return tel

        with patch("axe_fleet.registry.AxeOSConnector", FakeConn):
            out = reg.poll_device(dev["id"], tenant_id="t1")
        assert out["mining_paused"] is True
        row = reg.get_device(dev["id"], tenant_id="t1")
        assert row["status"] == STATUS_PAUSED

    def test_poll_device_marks_paused_even_with_stale_hashrate(self, tmp_path):
        """The exact Issue #13 regression: firmware reports a stale hashrate
        while paused — the card must still flip to PAUSED."""
        reg, _ = _make_registry(tmp_path)
        dev = reg.add_device("192.168.1.98", "Stale-HR", tenant_id="t1")

        class FakeConn:
            def __init__(self, ip):
                pass

            def extract_telemetry(self):
                tel = new_telemetry(dev["id"])
                tel["hashrate_hs"] = 1.4e12  # stale reading
                tel["mining_paused"] = True
                return tel

        with patch("axe_fleet.registry.AxeOSConnector", FakeConn):
            reg.poll_device(dev["id"], tenant_id="t1")
        assert reg.get_device(dev["id"], tenant_id="t1")["status"] == STATUS_PAUSED

    def test_save_agent_telemetry_marks_paused(self, tmp_path):
        reg, _ = _make_registry(tmp_path)
        dev = reg.add_device("192.168.1.97", "Agent-Paused", tenant_id="t2")
        tel = {"hashrate_hs": 0, "mining_paused": True, "ts": 1700000000}
        reg.save_agent_telemetry(dev["id"], tel, tenant_id="t2")
        assert reg.get_device(dev["id"], tenant_id="t2")["status"] == STATUS_PAUSED


# ══════════════════════════════════════════════════════════════════════════
# 4-5. Routes — pause/resume flip status immediately (Issue #13 core fix)
# ══════════════════════════════════════════════════════════════════════════
DEVICE = {
    "id": "dev-pause-1",
    "name": "Pause-Test",
    "ip_address": "192.168.1.55",
    "status": "ONLINE",
    "agent_managed": 0,
    "capabilities": {"restart": True, "pause": True, "resume": True},
}


def _mock_registry(device=DEVICE):
    m = MagicMock()
    m.get_device.return_value = dict(device)
    m.update_device.return_value = True
    return m


def _confirmed_post(client, endpoint):
    prepared = client.post(endpoint, json={"dry_run": False})
    assert prepared.status_code == 202
    token = prepared.get_json()["confirmation_token"]
    return client.post(
        endpoint, json={"dry_run": False, "confirmation_token": token}
    )


@pytest.fixture
def client():
    import app as _app_module

    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as c:
        yield c


class TestPauseResumeRoutes:
    def test_pause_sets_status_paused_immediately(self, client):
        reg = _mock_registry()

        class FakeConn:
            def __init__(self, ip):
                pass

            def pause(self):
                return {"success": True}

        with patch("axe_fleet.routes._registry", reg), patch(
            "axe_fleet.routes.AxeOSConnector", FakeConn
        ):
            resp = _confirmed_post(client, "/api/axe-fleet/devices/dev-pause-1/pause")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        # DB row flipped to PAUSED, scoped to the request tenant.
        call = reg.update_device.call_args
        assert call is not None
        assert call[0][0] == "dev-pause-1"
        assert call[0][1]["status"] == STATUS_PAUSED

    def test_pause_updates_snapshot_cache(self, client):
        reg = _mock_registry()
        import services.state as _shared_state

        _shared_state.axe_telemetry_cache["dev-pause-1"] = {
            "device_id": "dev-pause-1",
            "hashrate_hs": 1.4e12,
            "status": "ONLINE",
            "hashrate": 1.4e12,
        }
        try:

            class FakeConn:
                def __init__(self, ip):
                    pass

                def pause(self):
                    return {"success": True}

            with patch("axe_fleet.routes._registry", reg), patch(
                "axe_fleet.routes.AxeOSConnector", FakeConn
            ):
                resp = _confirmed_post(
                    client, "/api/axe-fleet/devices/dev-pause-1/pause"
                )
            assert resp.status_code == 200
            cached = _shared_state.axe_telemetry_cache["dev-pause-1"]
            assert cached["status"] == STATUS_PAUSED
        finally:
            # Module-level cache: never leak the entry into later tests.
            _shared_state.axe_telemetry_cache.pop("dev-pause-1", None)

    def test_resume_repolls_and_derives_online(self, client):
        reg = _mock_registry()
        state = {"paused": True}

        class FakeConn:
            def __init__(self, ip):
                pass

            def resume(self):
                state["paused"] = False
                return {"success": True}

            def extract_telemetry(self):
                tel = new_telemetry("dev-pause-1")
                tel["hashrate_hs"] = 1.3e12
                tel["mining_paused"] = state["paused"]
                return tel

        with patch("axe_fleet.routes._registry", reg), patch(
            "axe_fleet.routes.AxeOSConnector", FakeConn
        ):
            resp = _confirmed_post(
                client, "/api/axe-fleet/devices/dev-pause-1/resume"
            )
        assert resp.status_code == 200
        calls = reg.update_device.call_args_list
        assert len(calls) >= 1
        assert calls[-1][0][1]["status"] == STATUS_ONLINE

    def test_pause_queued_for_agent_managed_flips_status_optimistically(self, client):
        """Agent-managed pause is enqueued but the card must reflect PAUSED
        right away (the agent's next telemetry push confirms/self-heals)."""
        dev = dict(DEVICE, agent_managed=1)
        reg = _mock_registry(dev)
        reg.enqueue_agent_command.return_value = {"id": "cmd-1"}

        with patch("axe_fleet.routes._registry", reg):
            resp = _confirmed_post(client, "/api/axe-fleet/devices/dev-pause-1/pause")
        assert resp.status_code == 200
        assert resp.get_json()["queued"] is True
        assert reg.update_device.call_args[0][1]["status"] == STATUS_PAUSED

    def test_resume_with_zero_hashrate_becomes_idle(self, client):
        reg = _mock_registry()

        class FakeConn:
            def __init__(self, ip):
                pass

            def resume(self):
                return {"success": True}

            def extract_telemetry(self):
                tel = new_telemetry("dev-pause-1")
                tel["hashrate_hs"] = 0  # still warming up
                tel["mining_paused"] = False
                return tel

        with patch("axe_fleet.routes._registry", reg), patch(
            "axe_fleet.routes.AxeOSConnector", FakeConn
        ):
            resp = _confirmed_post(
                client, "/api/axe-fleet/devices/dev-pause-1/resume"
            )
        assert resp.status_code == 200
        assert reg.update_device.call_args[0][1]["status"] == "IDLE"

    def test_resume_when_repoll_fails_keeps_result_ok(self, client):
        """A failed re-poll after resume must not 500 — the command succeeded."""
        reg = _mock_registry()

        class FakeConn:
            def __init__(self, ip):
                pass

            def resume(self):
                return {"success": True}

            def extract_telemetry(self):
                from axe_fleet.connector import AxeOSConnectorError

                raise AxeOSConnectorError("device busy")

        with patch("axe_fleet.routes._registry", reg), patch(
            "axe_fleet.routes.AxeOSConnector", FakeConn
        ):
            resp = _confirmed_post(
                client, "/api/axe-fleet/devices/dev-pause-1/resume"
            )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 6. Agent telemetry endpoint — derives PAUSED from the pushed payload
# ══════════════════════════════════════════════════════════════════════════
class TestAgentTelemetryPaused:
    def test_agent_telemetry_response_reports_paused(self, client):
        reg = _mock_registry()
        reg.get_device_by_ip.return_value = {
            "id": "dev-pause-1",
            "name": "T",
            "ip_address": "192.168.1.55",
        }

        from services import auth as _auth

        with patch("axe_fleet.routes._registry", reg), patch.object(
            _auth, "verify_token", return_value={"sub": "t1", "agent": True}
        ):
            resp = client.post(
                "/api/agent/telemetry",
                json={
                    "ip": "192.168.1.55",
                    "telemetry": {"hashrate_hs": 0, "mining_paused": True},
                },
                headers={"Authorization": "Bearer fake-agent-token"},
            )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == STATUS_PAUSED
