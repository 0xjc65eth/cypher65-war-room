"""Official ESP-Miner / AxeOS contract — agent, connector, detector, lab.

These tests MUST talk to the real parsers (HTTP patched at the socket
layer for the virtual miner). They lock the production firmware shape
that Issue #627 accidentally trained the lab away from.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from axe_fleet.axeos_contract import (
    extract_axeos_telemetry,
    hashrate_hs_from_axeos,
    looks_like_axeos,
    official_esp_miner_info,
)
from axe_fleet.connector import AxeOSConnector
from core.registry.detector import _looks_like_axeos, detect_firmware
from tests.virtual_hardware.nerdqaxe import VirtualNerdQaxe

import agent.agent as agent_mod


OFFICIAL = official_esp_miner_info()
# 4800 GH/s → 4.8e12 H/s
OFFICIAL_HS = 4_800_000_000_000


class TestLooksLikeAxeOS:
    def test_official_payload_is_axeos(self):
        assert looks_like_axeos(OFFICIAL) is True
        assert _looks_like_axeos(OFFICIAL) is True
        assert agent_mod._probe_axeos_payload(OFFICIAL) is True

    def test_router_json_is_not_axeos(self):
        blob = {"status": "ok", "device": "router", "uptime": 12}
        assert looks_like_axeos(blob) is False
        assert _looks_like_axeos(blob) is False

    def test_home_assistant_frequency_alone_is_not_axeos(self):
        blob = {"frequency": 2412, "ssid": "home", "message": "ok"}
        assert looks_like_axeos(blob) is False
        assert _looks_like_axeos(blob) is False

    def test_ip_camera_json_is_not_axeos(self):
        blob = {"fps": 30, "frequency": 24, "codec": "h264"}
        assert looks_like_axeos(blob) is False

    def test_nas_catch_all_is_not_axeos(self):
        blob = {"success": True, "data": {"cpu": 12}}
        assert looks_like_axeos(blob) is False


class TestHashrateUnits:
    def test_official_ghs_hashRate_converts_to_hs(self):
        assert hashrate_hs_from_axeos(OFFICIAL) == OFFICIAL_HS
        tel = extract_axeos_telemetry(OFFICIAL)
        assert tel["hashrate_hs"] == OFFICIAL_HS
        assert tel["hashrate_1m"] == 4_750_000_000_000
        assert tel["expected_hashrate"] == 5_000_000_000_000

    def test_legacy_lowercase_hashrate_stays_hs(self):
        info = {"hashrate": 1.5e12, "ASICModel": "BM1366"}
        assert hashrate_hs_from_axeos(info) == 1_500_000_000_000

    def test_legacy_camel_already_hs_is_not_multiplied(self):
        info = {"hashRate": 1.5e12}
        assert hashrate_hs_from_axeos(info) == 1_500_000_000_000

    def test_zero_is_zero_not_unsupported(self):
        assert hashrate_hs_from_axeos({"hashRate": 0}) == 0
        assert (
            extract_axeos_telemetry({"hashRate": 0, "bestDiff": 0})["best_diff"] == "0"
        )

    def test_missing_hashrate_is_none_not_zero(self):
        tel = extract_axeos_telemetry({"ASICModel": "BM1370", "boardVersion": "401"})
        assert tel["hashrate_hs"] is None
        assert tel["shares_accepted"] is None

    def test_nan_and_infinity_are_none(self):
        assert hashrate_hs_from_axeos({"hashRate": "N/A"}) is None
        assert hashrate_hs_from_axeos({"hashRate": float("inf")}) is None
        assert hashrate_hs_from_axeos({"hashRate": "Infinity"}) is None


class TestFieldAliases:
    def test_official_worker_mac_uptime(self):
        tel = extract_axeos_telemetry(OFFICIAL)
        assert tel["pool_user"] == "virtual.worker"
        assert tel["pool_url"] == "solo.ckpool.org"
        assert tel["uptime_seconds"] == 7200
        assert tel["mac"] == "AA:BB:CC:DD:EE:FF"
        assert tel["shares_accepted"] == 42
        assert tel["shares_rejected"] == 1
        assert tel["best_session_diff"] == "0"
        assert tel["fan_rpm"] == 4200
        assert tel["temperature"] == 58.0


class TestConnectorUsesOfficialContract:
    def test_extract_telemetry_reads_hashRate_ghs(self):
        conn = AxeOSConnector("127.0.0.1")
        tel = conn.extract_telemetry(OFFICIAL)
        assert tel["hashrate_hs"] == OFFICIAL_HS
        assert tel["pool_user"] == "virtual.worker"
        assert tel["uptime_seconds"] == 7200
        assert tel["shares_accepted"] == 42


class TestAgentUsesOfficialContract:
    def test_probe_accepts_official_payload(self):
        discovered = agent_mod._identity_from_axeos("192.168.1.50", OFFICIAL)
        assert discovered["type"] == "bitaxe"
        assert discovered["mac"] == "AA:BB:CC:DD:EE:FF"
        assert discovered["hashrate_hs"] == OFFICIAL_HS
        assert discovered["model"] == "NerdQaxe++"

    def test_poll_telemetry_reads_official_fields(self):
        with patch.object(agent_mod, "_probe_axeos", return_value=OFFICIAL):
            tel = agent_mod._poll_telemetry({"ip": "192.168.1.50", "type": "bitaxe"})
        assert tel["hashrate_hs"] == OFFICIAL_HS
        assert tel["pool_user"] == "virtual.worker"
        assert tel["uptime_seconds"] == 7200
        assert tel["shares_accepted"] == 42
        assert tel["shares_rejected"] == 1


class TestDetectorOfficialPayload:
    def test_detect_firmware_official_http(self):
        class _Resp:
            status_code = 200

            def json(self):
                return OFFICIAL

        with patch("core.registry.detector.requests.get", return_value=_Resp()):
            result = detect_firmware("192.168.1.50", timeout=0.2)
        assert result["firmware"] == "axeos"
        assert result["reachable"] is True
        assert result["capabilities"].get("telemetry") is True


class TestAgentPollsVirtualHardware:
    def test_probe_and_poll_virtual_nerdqaxe(self):
        with VirtualNerdQaxe() as device:
            host, port = device.address.split(":")
            orig = agent_mod.AXEOS_PORT
            agent_mod.AXEOS_PORT = int(port)
            try:
                info = agent_mod._probe_axeos(host)
                assert info is not None
                assert "hashRate" in info
                tel = agent_mod._poll_telemetry({"ip": host, "type": "bitaxe"})
            finally:
                agent_mod.AXEOS_PORT = orig
        assert tel["hashrate_hs"] == OFFICIAL_HS
        assert tel["shares_accepted"] == 42
        assert tel["pool_user"] == "virtual.worker"


class TestHealthSkipsEmptyHeartbeat:
    def test_latest_telemetry_walks_back_past_heartbeat(self):
        from axe_fleet.routes import _latest_telemetry

        rows = [
            {"payload": {"ts": 9}},
            {"payload": {"hashrate_hs": 1.2e12, "shares_accepted": 10, "ts": 8}},
        ]
        tel = _latest_telemetry(rows)
        assert tel["hashrate_hs"] == 1.2e12
        assert tel["shares_accepted"] == 10


class TestVirtualLabEmitsOfficialSchema:
    def test_virtual_nerdqaxe_serves_hashRate_not_legacy_only(self):
        with VirtualNerdQaxe() as device:
            host, port = device.address.split(":")
            import urllib.request

            raw = urllib.request.urlopen(
                f"http://{host}:{port}/api/system/info", timeout=2
            ).read()
            info = json.loads(raw)
        assert "hashRate" in info
        assert "ASICModel" in info
        assert "uptimeSeconds" in info
        assert "macAddr" in info
        assert "stratumUser" in info
        tel = extract_axeos_telemetry(info)
        assert tel["hashrate_hs"] == OFFICIAL_HS


class TestDhcpMacIdentity:
    def test_upsert_same_mac_new_ip_does_not_duplicate(self, tmp_path, monkeypatch):
        from axe_fleet.registry import DeviceRegistry
        import sqlite3

        db = tmp_path / "t.sqlite"
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE axe_devices (id TEXT PRIMARY KEY, name TEXT, model TEXT, "
            "manufacturer TEXT, firmware TEXT, firmware_version TEXT, api_version TEXT, "
            "ip_address TEXT, hostname TEXT, mac_address TEXT, last_seen INTEGER, "
            "status TEXT, group_id TEXT, capabilities TEXT, added_at INTEGER, "
            "updated_at INTEGER, tenant_id TEXT, agent_managed INTEGER DEFAULT 0, "
            "removed_at INTEGER DEFAULT 0)"
        )
        conn.commit()

        def get_db():
            c = sqlite3.connect(db)
            c.row_factory = sqlite3.Row
            return c

        registry = DeviceRegistry(get_db)
        a = registry.upsert_agent_device(
            "192.168.1.10",
            tenant_id="acme",
            info={"mac": "AA:BB:CC:DD:EE:FF", "model": "NerdQaxe++", "type": "bitaxe"},
        )
        b = registry.upsert_agent_device(
            "192.168.1.84",
            tenant_id="acme",
            info={"mac": "AA:BB:CC:DD:EE:FF", "model": "NerdQaxe++", "type": "bitaxe"},
        )
        assert a["id"] == b["id"]
        assert b["ip_address"] == "192.168.1.84"


class TestCloudNeverDialsPrivateIp:
    def test_diagnose_private_ip_on_cloud_is_400(self, monkeypatch):
        import app as app_mod

        monkeypatch.setenv("RENDER", "true")
        app_mod.app.config["TESTING"] = True
        with patch("axe_fleet.scanner.diagnose_host") as probe:
            with app_mod.app.test_client() as client:
                resp = client.get("/api/axe-fleet/diagnose/192.168.1.50")
        monkeypatch.delenv("RENDER", raising=False)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["is_cloud"] is True
        probe.assert_not_called()


class TestDiagnoseRejectsGenericJson:
    def test_diagnose_host_does_not_label_router_json_bitaxe(self):
        from axe_fleet.scanner import diagnose_host

        class _FakeConn:
            def __init__(self, *a, **k):
                pass

            def fetch_info(self):
                return {"status": "ok", "device": "router"}

        with patch("axe_fleet.connector.AxeOSConnector", _FakeConn), patch(
            "axe_fleet.scanner._probe_cgminer_version", return_value=None
        ), patch(
            "core.registry.detector.detect_firmware", return_value={"reachable": False}
        ):
            result = diagnose_host("192.168.1.1")
        assert result.get("protocol") != "bitaxe"
        assert result.get("reachable") is False
