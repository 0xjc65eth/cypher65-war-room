"""Cloud egress: refresh, diagnose, add and the connector must not dial RFC1918."""

import socket
from unittest.mock import patch

import pytest

import app as app_module
from axe_fleet.connector import AxeOSConnector, CloudEgressBlocked
from axe_fleet.scanner import diagnose_host
from core.registry.detector import detect_firmware

app = app_module.app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def _private_dns(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]


def _assert_no_miner_socket(requests_get, sock, connect):
    requests_get.assert_not_called()
    sock.assert_not_called()
    connect.assert_not_called()


class TestCloudEgress:
    def test_connector_refuses_literal_and_resolved_private(self, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        with patch("requests.get") as requests_get, patch(
            "socket.socket"
        ) as sock, patch("socket.create_connection") as connect:
            with pytest.raises(CloudEgressBlocked):
                AxeOSConnector("10.1.2.3")
            with patch("socket.getaddrinfo", side_effect=_private_dns):
                with pytest.raises(CloudEgressBlocked):
                    AxeOSConnector("miner.lan")
        _assert_no_miner_socket(requests_get, sock, connect)

    def test_self_host_connector_allows_lan_ip(self, monkeypatch):
        monkeypatch.delenv("RENDER", raising=False)
        monkeypatch.delenv("CLOUD_MODE", raising=False)
        conn = AxeOSConnector("192.168.1.50")
        assert conn.ip == "192.168.1.50"

    def test_refresh_refuses_private_ip_and_hostname(self, client, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        import axe_fleet.routes as routes

        class _Registry:
            def __init__(self, ip):
                self.ip = ip

            def get_device(self, device_id, tenant_id=""):
                return {"id": device_id, "ip_address": self.ip}

        monkeypatch.setattr(routes, "_registry", _Registry("192.168.4.4"))
        with patch("requests.get") as requests_get, patch(
            "socket.socket"
        ) as sock, patch("socket.create_connection") as connect:
            literal = client.post("/api/axe-fleet/devices/dev1/refresh")
            monkeypatch.setattr(routes, "_registry", _Registry("miner.lan"))
            with patch("socket.getaddrinfo", side_effect=_private_dns):
                named = client.post("/api/axe-fleet/devices/dev1/refresh")
        assert literal.status_code == 400
        assert literal.get_json()["code"] == "CLOUD_PRIVATE_TARGET"
        assert named.status_code == 400
        assert named.get_json()["code"] == "CLOUD_PRIVATE_TARGET"
        _assert_no_miner_socket(requests_get, sock, connect)

    def test_diagnose_refuses_private_ip_and_hostname(self, client, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        with patch("requests.get") as requests_get, patch(
            "socket.socket"
        ) as sock, patch("socket.create_connection") as connect, patch(
            "axe_fleet.scanner.diagnose_host"
        ) as probe:
            literal = client.get("/api/axe-fleet/diagnose/192.168.1.50")
            with patch("socket.getaddrinfo", side_effect=_private_dns):
                named = client.get("/api/axe-fleet/diagnose/miner.lan")
        assert literal.status_code == 400
        assert named.status_code == 400
        probe.assert_not_called()
        _assert_no_miner_socket(requests_get, sock, connect)

    def test_add_refuses_hostname_and_keeps_literal_queue(self, client, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        import axe_fleet.routes as routes

        class _Registry:
            def get_device_by_ip(self, ip, tenant_id=""):
                return {}

            def get_removed_by_ip(self, ip, tenant_id=""):
                return {}

            def enqueue_agent_command(self, *args, **kwargs):
                return {"id": "probe-1"}

        monkeypatch.setattr(routes, "_registry", _Registry())
        with patch("requests.get") as requests_get, patch(
            "socket.socket"
        ) as sock, patch("socket.create_connection") as connect, patch(
            "core.registry.detector.detect_firmware"
        ) as detect:
            with patch("socket.getaddrinfo", side_effect=_private_dns):
                named = client.post(
                    "/api/axe-fleet/devices", json={"ip_address": "miner.lan"}
                )
            literal = client.post(
                "/api/axe-fleet/devices", json={"ip_address": "10.9.0.8"}
            )
        assert named.status_code == 400
        assert named.get_json()["code"] == "CLOUD_PRIVATE_TARGET"
        assert literal.status_code == 202
        assert literal.get_json()["queued"] is True
        detect.assert_not_called()
        _assert_no_miner_socket(requests_get, sock, connect)

    def test_direct_probes_refuse_without_socket(self, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        with patch("requests.get") as requests_get, patch(
            "socket.socket"
        ) as sock, patch("socket.create_connection") as connect:
            diagnosed = diagnose_host("172.16.0.4")
            detected = detect_firmware("172.16.0.4")
        assert diagnosed["reachable"] is False
        assert diagnosed["error_detail"].startswith("CLOUD_PRIVATE_TARGET")
        assert detected["reachable"] is False
        _assert_no_miner_socket(requests_get, sock, connect)

    def test_scan_still_refuses(self, client, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        with patch("axe_fleet.scanner.scan_subnet") as scan, patch(
            "requests.get"
        ) as requests_get, patch("socket.socket") as sock, patch(
            "socket.create_connection"
        ) as connect:
            resp = client.post("/api/axe-fleet/scan", json={"cidr": "192.168.1.0/24"})
        assert resp.status_code == 400
        assert resp.get_json()["is_cloud"] is True
        scan.assert_not_called()
        _assert_no_miner_socket(requests_get, sock, connect)
