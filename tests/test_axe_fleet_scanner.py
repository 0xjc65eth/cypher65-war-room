"""
CYPHER65 // AXE FLEET — LAN Miner Discovery unit tests
======================================================
Tests axe_fleet/scanner.py (pure functions: parse_cidr, _probe_cgminer_version,
probe_host, scan_subnet, suggest_subnets) and the /api/axe-fleet/scan routes.
Hermetic: no real network I/O — sockets/HTTP are patched.
"""
import json
import socket
import threading
import time
from unittest.mock import patch

import pytest

from axe_fleet.scanner import (
    parse_cidr,
    probe_host,
    scan_subnet,
    suggest_subnets,
    diagnose_host,
    _probe_cgminer_version,
    MAX_HOSTS_PER_SCAN,
    CGMINER_PORT,
)

import app as _app_module
app = _app_module.app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_scan_store():
    """Clear the in-process scan store before every test so a lingering
    "running" scan from one test can never 409 the next one."""
    import axe_fleet.routes as routes
    with routes._scans_lock:
        routes._scans.clear()
    yield
    with routes._scans_lock:
        routes._scans.clear()


def _wait_scan_done(scan_id, timeout=2.0):
    """Block until the in-process scan store reports done/error for scan_id.
    Prevents daemon threads from leaking real scans or polluting later tests."""
    import axe_fleet.routes as routes
    deadline = time.time() + timeout
    while time.time() < deadline:
        with routes._scans_lock:
            s = routes._scans.get(scan_id)
        if s and s.get("status") in ("done", "error"):
            return s
        time.sleep(0.05)
    with routes._scans_lock:
        return routes._scans.get(scan_id)


# ══════════════════════════════════════════════════════════════════════════
#  parse_cidr
# ══════════════════════════════════════════════════════════════════════════

class TestParseCidr:
    def test_single_ip(self):
        assert parse_cidr("192.168.1.7") == ["192.168.1.7"]

    def test_cidr_24(self):
        hosts = parse_cidr("192.168.1.0/24")
        assert len(hosts) == 254
        assert hosts[0] == "192.168.1.1"
        assert hosts[-1] == "192.168.1.254"
        # network & broadcast addresses excluded
        assert "192.168.1.0" not in hosts
        assert "192.168.1.255" not in hosts

    def test_cidr_30(self):
        hosts = parse_cidr("10.0.0.0/30")
        assert hosts == ["10.0.0.1", "10.0.0.2"]

    def test_cidr_strict_false_accepts_host_bits(self):
        # '192.168.1.5/24' — ip_network(strict=False) normalizes
        hosts = parse_cidr("192.168.1.5/24")
        assert len(hosts) == 254

    def test_range(self):
        assert parse_cidr("192.168.1.10-12") == ["192.168.1.10", "192.168.1.11", "192.168.1.12"]

    def test_range_invalid(self):
        assert parse_cidr("192.168.1.20-5") == []
        assert parse_cidr("192.168.1.abc-5") == []

    def test_single_host_cidr(self):
        # /31 and /32 are point-to-point: .hosts() returns the whole network
        # (both addresses for /31, the single address for /32).
        assert parse_cidr("127.0.0.1/32") == ["127.0.0.1"]
        assert parse_cidr("192.168.1.7/31") == ["192.168.1.6", "192.168.1.7"]

    def test_huge_cidr_capped(self):
        # A /8 would be 16M hosts — must be capped, never explode.
        hosts = parse_cidr("10.0.0.0/8")
        assert len(hosts) == MAX_HOSTS_PER_SCAN

    def test_empty_and_garbage(self):
        assert parse_cidr("") == []
        assert parse_cidr(None) == []
        assert parse_cidr("not-an-ip") == []  # unresolvable hostname
        assert parse_cidr("999.999.1.0/24") == []


# ══════════════════════════════════════════════════════════════════════════
#  _probe_cgminer_version
# ══════════════════════════════════════════════════════════════════════════

class TestProbeCgminerVersion:
    def test_parses_version_json(self):
        payload = json.dumps({"STATUS": [{"STATUS": "S"}], "VERSION": [{"CGMiner": "4.12.0", "Description": "Antminer S19"}]})
        with patch("axe_fleet.scanner.socket.socket") as mock_sock:
            sock = mock_sock.return_value
            sock.recv.side_effect = [payload.encode() + b"\x00", b""]
            result = _probe_cgminer_version("192.168.1.50")
        assert result is not None
        assert result["STATUS"]
        assert result["VERSION"][0]["CGMiner"] == "4.12.0"

    def test_connection_error_returns_none(self):
        with patch("axe_fleet.scanner.socket.socket") as mock_sock:
            mock_sock.return_value.connect.side_effect = OSError("refused")
            assert _probe_cgminer_version("192.168.1.50") is None

    def test_timeout_returns_none(self):
        with patch("axe_fleet.scanner.socket.socket") as mock_sock:
            mock_sock.return_value.connect.side_effect = __import__("socket").timeout
            assert _probe_cgminer_version("192.168.1.50") is None

    def test_garbage_returns_none(self):
        with patch("axe_fleet.scanner.socket.socket") as mock_sock:
            sock = mock_sock.return_value
            sock.recv.side_effect = [b"not json\x00", b""]
            assert _probe_cgminer_version("192.168.1.50") is None


# ══════════════════════════════════════════════════════════════════════════
#  probe_host
# ══════════════════════════════════════════════════════════════════════════

class TestProbeHost:
    # NOTE: probe_host imports AxeOSConnector INSIDE the function body
    # (`from .connector import ...`), so we patch axe_fleet.connector.

    def test_bitaxe_detected(self):
        info = {
            "model": "Bitaxe Max",
            "hostname": "bitaxe-01",
            "firmware": "AxeOS",
            "version": "2.6.0",
            "hashrate": 3800000000000,
            "mac": "AA:BB:CC",
        }
        with patch("axe_fleet.connector.AxeOSConnector") as mock_conn:
            mock_conn.return_value.fetch_info.return_value = info
            result = probe_host("192.168.1.100")
        assert result is not None
        assert result["type"] == "bitaxe"
        assert result["ip"] == "192.168.1.100"
        assert result["model"] == "Bitaxe Max"
        assert result["hashrate_hs"] == 3800000000000

    def test_cgminer_detected_when_bitaxe_fails(self):
        with patch("axe_fleet.connector.AxeOSConnector") as mock_conn:
            mock_conn.return_value.fetch_info.side_effect = Exception("connection failed")
            with patch("axe_fleet.scanner._probe_cgminer_version") as mock_cg:
                mock_cg.return_value = {"STATUS": [{"STATUS": "S"}], "VERSION": [{"Description": "Antminer S19 Pro"}]}
                result = probe_host("192.168.1.200")
        assert result is not None
        assert result["type"] == "cgminer"
        assert result["port"] == CGMINER_PORT
        assert result["model"] == "Antminer S19 Pro"

    def test_neither_returns_none(self):
        with patch("axe_fleet.connector.AxeOSConnector") as mock_conn:
            mock_conn.return_value.fetch_info.side_effect = Exception("down")
            with patch("axe_fleet.scanner._probe_cgminer_version") as mock_cg:
                mock_cg.return_value = None
                assert probe_host("192.168.1.250") is None

    def test_empty_ip_returns_none(self):
        assert probe_host("") is None
        assert probe_host(None) is None


# ══════════════════════════════════════════════════════════════════════════
#  scan_subnet
# ══════════════════════════════════════════════════════════════════════════

class TestScanSubnet:
    def test_invalid_cidr(self):
        result = scan_subnet("garbage!!")
        assert result["error"]
        assert result["found"] == []

    def test_found_devices_aggregated(self):
        with patch("axe_fleet.scanner.probe_host") as mock_probe:
            def fake_probe(ip, timeout=None):
                if ip.endswith(".2") or ip.endswith(".5"):
                    return {"ip": ip, "type": "bitaxe", "model": "Bitaxe", "hashrate_hs": 1000}
                return None
            mock_probe.side_effect = fake_probe
            result = scan_subnet("192.168.9.0/29")  # 6 hosts (.1-.6)
        assert result["total"] == 6
        assert len(result["found"]) == 2
        assert result["error"] is None

    def test_progress_callback(self):
        calls = []
        with patch("axe_fleet.scanner.probe_host", return_value=None):
            scan_subnet("192.168.9.0/29", progress_cb=lambda s, t: calls.append((s, t)))
        assert calls and calls[-1][0] == 6  # all hosts eventually scanned


# ══════════════════════════════════════════════════════════════════════════
#  suggest_subnets
# ══════════════════════════════════════════════════════════════════════════

class TestSuggestSubnets:
    def test_derives_from_local_ips(self):
        with patch("axe_fleet.scanner._local_ipv4_addresses", return_value=["192.168.1.42", "10.0.0.5"]):
            subnets = suggest_subnets()
        assert "192.168.1.0/24" in subnets
        assert "10.0.0.0/24" in subnets

    def test_excludes_loopback_linklocal(self):
        with patch("axe_fleet.scanner._local_ipv4_addresses",
                   return_value=["127.0.0.1", "169.254.10.5", "192.168.1.42"]):
            subnets = suggest_subnets()
        assert "192.168.1.0/24" in subnets
        assert "127.0.0.0/24" not in subnets
        assert "169.254.0.0/24" not in subnets

    def test_no_ips_returns_empty(self):
        with patch("axe_fleet.scanner._local_ipv4_addresses", return_value=[]):
            assert suggest_subnets() == []


# ══════════════════════════════════════════════════════════════════════════
#  Routes — /api/axe-fleet/scan*
# ══════════════════════════════════════════════════════════════════════════

class TestScanRoutes:
    # NOTE: the routes import scan_subnet/suggest_subnets INSIDE the function
    # body (`from .scanner import ...`), so we patch the scanner module, not
    # axe_fleet.routes.

    def test_start_scan_returns_scan_id(self, client):
        with patch("axe_fleet.scanner.scan_subnet") as mock_scan:
            mock_scan.return_value = {"total": 10, "found": [], "error": None}
            resp = client.post("/api/axe-fleet/scan", json={"cidr": "192.168.1.0/24"})
            scan_id = resp.get_json().get("scan_id")
            # Wait INSIDE the patch context (patched scan_subnet, never a real
            # LAN scan) until the daemon thread reports done.
            s = _wait_scan_done(scan_id) if scan_id else None
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["success"] is True
        assert data["scan_id"]
        assert s is not None and s["status"] == "done"

    def test_scan_missing_cidr_uses_suggestion(self, client):
        with patch("axe_fleet.scanner.suggest_subnets", return_value=["10.0.0.0/24"]):
            with patch("axe_fleet.scanner.scan_subnet") as mock_scan:
                mock_scan.return_value = {"total": 1, "found": [], "error": None}
                resp = client.post("/api/axe-fleet/scan", json={})
                scan_id = resp.get_json().get("scan_id")
                _wait_scan_done(scan_id) if scan_id else None
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["cidr"] == "10.0.0.0/24"

    def test_scan_requires_cidr_or_suggestion(self, client):
        with patch("axe_fleet.scanner.suggest_subnets", return_value=[]):
            resp = client.post("/api/axe-fleet/scan", json={})
        assert resp.status_code == 400
        assert "cidr" in resp.get_json()["error"]

    def test_scan_status_tenant_scoped(self, client):
        with patch("axe_fleet.scanner.scan_subnet") as mock_scan:
            mock_scan.return_value = {"total": 2, "found": [{"ip": "192.168.1.10", "type": "bitaxe"}], "error": None}
            started = client.post("/api/axe-fleet/scan", json={"cidr": "192.168.1.0/24"})
            scan_id = started.get_json()["scan_id"]
            _wait_scan_done(scan_id)  # let daemon thread complete (patched)
            ok = client.get(f"/api/axe-fleet/scan/{scan_id}")
        assert ok.status_code == 200
        s = ok.get_json()["scan"]
        assert s["status"] == "done"
        assert s["found"][0]["ip"] == "192.168.1.10"

    def test_scan_rejects_concurrent_same_tenant(self, client):
        """A second scan for the same tenant while one is running → 409."""
        # Block inside scan_subnet so the first daemon thread is still marked
        # "running" when the second request arrives.
        started = threading.Event()
        release = threading.Event()

        def slow_scan(cidr, progress_cb=None, **kw):
            started.set()
            release.wait(3)
            return {"total": 1, "found": [], "error": None}

        with patch("axe_fleet.scanner.scan_subnet", side_effect=slow_scan):
            first = client.post("/api/axe-fleet/scan", json={"cidr": "192.168.1.0/24"})
            assert first.status_code == 202
            first_id = first.get_json()["scan_id"]
            assert started.wait(2), "first scan never started"
            second = client.post("/api/axe-fleet/scan", json={"cidr": "192.168.2.0/24"})
            assert second.status_code == 409
            # Release the first scan, wait for it to finish, then a new scan
            # for the same tenant must be accepted again.
            release.set()
            _wait_scan_done(first_id)
            third = client.post("/api/axe-fleet/scan", json={"cidr": "192.168.2.0/24"})
            assert third.status_code == 202
            _wait_scan_done(third.get_json()["scan_id"])

    def test_scan_status_unknown_returns_404(self, client):
        resp = client.get("/api/axe-fleet/scan/doesnotexist")
        assert resp.status_code == 404

    def test_scan_subnets_endpoint(self, client):
        with patch("axe_fleet.scanner.suggest_subnets", return_value=["192.168.1.0/24"]):
            resp = client.get("/api/axe-fleet/scan/subnets")
        assert resp.status_code == 200
        assert resp.get_json()["subnets"] == ["192.168.1.0/24"]


# ═══════════════════════════════════════════════════════════════════════
#  diagnose_host() — onboarding wizard connectivity test
# ═══════════════════════════════════════════════════════════════════════

class TestDiagnoseHost:
    """diagnose_host(): unified single-host connectivity report (AxeOS :80
    + cgminer :4028) used by the onboarding wizard's TEST CONNECTIVITY."""

    def test_empty_host(self):
        r = diagnose_host("")
        assert r["reachable"] is False
        assert r["error_detail"] == "empty host"
        assert r["dns_resolution"] is False

    def test_invalid_hostname_dns_failure(self):
        # gaierror is the real DNS-failure type raised by socket.getaddrinfo
        with patch("axe_fleet.scanner.socket.getaddrinfo", side_effect=socket.gaierror("no such host")):
            r = diagnose_host("not-a-real-host.invalid")
        assert r["reachable"] is False
        assert r["dns_resolution"] is False
        assert r["protocol"] is None

    def test_ip_resolves_without_dns_lookup(self):
        # A numeric IP short-circuits DNS in OUR code path. fetch_info is
        # mocked so no real socket connect (and no internal getaddrinfo)
        # happens; if the code wrongly consulted DNS we'd see a call.
        with patch("axe_fleet.scanner.socket.getaddrinfo", side_effect=AssertionError("must not hit DNS")) \
                as ga, \
                patch("axe_fleet.connector.AxeOSConnector.fetch_info", side_effect=Exception("no http")), \
                patch("axe_fleet.scanner._probe_cgminer_version", return_value=None):
            r = diagnose_host("10.0.0.5")
            ga.assert_not_called()
        assert r["dns_resolution"] is True
        assert r["reachable"] is False

    def test_bitaxe_http_win(self):
        info = {"model": "Bitaxe Gamma", "hostname": "gamma1", "firmware": "v2.1", "hashrate": 1200000000}
        with patch("axe_fleet.connector.AxeOSConnector.fetch_info", return_value=info):
            r = diagnose_host("192.168.1.50")
        assert r["bitaxe_http"] is True
        assert r["reachable"] is True
        assert r["protocol"] == "bitaxe"
        assert r["device_info"]["model"] == "Bitaxe Gamma"
        assert r["device_info"]["hashrate_hs"] == 1200000000
        # cgminer probe must NOT run once bitaxe answered
        assert r["cgminer_tcp"] is False

    def test_cgminer_tcp_fallback(self):
        ver = {"STATUS": [{"STATUS": "S"}], "VERSION": [{"CGMiner": "4.12.0", "Description": "Antminer S19 Pro"}]}
        with patch("axe_fleet.connector.AxeOSConnector.fetch_info", side_effect=Exception("no HTTP")), \
                patch("axe_fleet.scanner._probe_cgminer_version", return_value=ver):
            r = diagnose_host("192.168.1.77")
        assert r["bitaxe_http"] is False
        assert r["cgminer_tcp"] is True
        assert r["reachable"] is True
        assert r["protocol"] == "cgminer"
        assert r["device_info"]["model"] == "Antminer S19 Pro"
        assert r["device_info"]["version"] == "4.12.0"

    def test_nothing_reachable(self):
        with patch("axe_fleet.connector.AxeOSConnector.fetch_info", side_effect=Exception("refused")), \
                patch("axe_fleet.scanner._probe_cgminer_version", return_value=None):
            r = diagnose_host("192.168.1.99")
        assert r["reachable"] is False
        assert r["protocol"] is None
        assert r["device_info"] is None
        assert "no miner protocol" in r["error_detail"]

    def test_elapsed_ms_set(self):
        with patch("axe_fleet.connector.AxeOSConnector.fetch_info", side_effect=Exception("x")), \
                patch("axe_fleet.scanner._probe_cgminer_version", return_value=None):
            r = diagnose_host("192.168.1.9")
        assert r["elapsed_ms"] >= 0

    def test_diagnose_route_bitaxe(self, client):
        info = {"model": "Bitaxe Gamma", "hostname": "gamma", "firmware": "v2", "hashrate": 500000000}
        with patch("axe_fleet.connector.AxeOSConnector.fetch_info", return_value=info):
            resp = client.get("/api/axe-fleet/diagnose/192.168.1.50")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["reachable"] is True
        assert data["protocol"] == "bitaxe"
        assert data["device_info"]["model"] == "Bitaxe Gamma"

    def test_diagnose_route_unreachable(self, client):
        with patch("axe_fleet.connector.AxeOSConnector.fetch_info", side_effect=Exception("refused")), \
                patch("axe_fleet.scanner._probe_cgminer_version", return_value=None):
            resp = client.get("/api/axe-fleet/diagnose/192.168.1.99")
        assert resp.status_code == 200
        assert resp.get_json()["reachable"] is False

    def test_diagnose_route_exception_safety(self, client):
        """Even if the scanner itself blows up, the route returns JSON 200."""
        with patch("axe_fleet.scanner.diagnose_host", side_effect=RuntimeError("boom")):
            resp = client.get("/api/axe-fleet/diagnose/192.168.1.1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["reachable"] is False
        assert data["error_detail"] == "boom"
