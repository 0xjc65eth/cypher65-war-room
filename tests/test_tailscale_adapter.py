"""
Unit tests for services/tailscale_adapter.py

Tests cover:
  - get_local_status() with mocked tailscale CLI
  - diagnose_connection() success/failure
  - check_remote_device() API success/failure
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from services.tailscale_adapter import (
    get_local_status,
    diagnose_connection,
    check_remote_device,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. get_local_status
# ═══════════════════════════════════════════════════════════════════════════

class TestGetLocalStatus:
    """Tests for get_local_status() — detects local Tailscale daemon."""

    def test_tailscale_not_installed(self):
        """When tailscale CLI not found, returns connected=False."""
        with patch("services.tailscale_adapter.shutil.which", return_value=None):
            result = get_local_status()
            assert result["tailscale_installed"] is False
            assert result["connected"] is False
            assert result["ip"] is None
            assert "not found" in (result.get("error") or "")

    def test_tailscale_installed_but_not_connected(self):
        """When tailscale binary exists but 'tailscale ip' fails."""
        def mock_which(_cmd):
            return "/usr/bin/tailscale"
        with patch("services.tailscale_adapter.shutil.which", mock_which):
            with patch("services.tailscale_adapter._run_tailscale_cli", return_value=None):
                result = get_local_status()
                assert result["tailscale_installed"] is True
                assert result["connected"] is False
                assert result["ip"] is None

    def test_connected_with_ip_only(self):
        """When tailscale returns an IP but status --json fails."""
        def mock_which(_cmd):
            return "/usr/bin/tailscale"
        call_count = [0]

        def mock_cli(*args):
            call_count[0] += 1
            if args == ("ip", "-4"):
                return "100.120.130.140"
            if args == ("status", "--json"):
                return None  # --json fails
            if args == ("status", ):
                return "100.120.130.140   my-hostname       linux   active"
            return None

        with patch("services.tailscale_adapter.shutil.which", mock_which):
            with patch("services.tailscale_adapter._run_tailscale_cli", mock_cli):
                result = get_local_status()
                assert result["connected"] is True
                assert result["ip"] == "100.120.130.140"
                assert result["hostname"] == "my-hostname"

    def test_full_connection_with_status_json(self):
        """Full mock with tailscale status --json returning host details."""
        mock_json_output = '{"Self": {"HostName": "my-host", "Online": true}, "MagicDNSSuffix": "tailnet-abc.ts.net"}'

        def mock_which(_cmd):
            return "/usr/bin/tailscale"

        call_count = [0]

        def mock_cli(*args):
            call_count[0] += 1
            if args == ("ip", "-4"):
                return "100.64.0.1"
            if args == ("status", "--json"):
                return mock_json_output
            return None

        with patch("services.tailscale_adapter.shutil.which", mock_which):
            with patch("services.tailscale_adapter._run_tailscale_cli", mock_cli):
                result = get_local_status()
                assert result["connected"] is True
                assert result["ip"] == "100.64.0.1"
                assert result["hostname"] == "my-host"
                assert result["magic_dns_name"] == "my-host.tailnet-abc.ts.net"
                assert result["online"] is True

    def test_checked_at_is_set(self):
        """checked_at should be a recent timestamp."""
        import time
        with patch("services.tailscale_adapter.shutil.which", return_value=None):
            result = get_local_status()
            assert result["checked_at"] > 0
            assert abs(result["checked_at"] - int(time.time())) < 5


# ═══════════════════════════════════════════════════════════════════════════
# 2. diagnose_connection
# ═══════════════════════════════════════════════════════════════════════════

class TestDiagnoseConnection:
    """Tests for diagnose_connection() — HTTP reachability check."""

    def test_no_remote_ip(self):
        """Empty remote_ip should return error."""
        result = diagnose_connection(remote_ip="", timeout=3)
        assert result["reachable"] is False
        assert result["error"] is not None

    def _make_mock_response(self, status_code=200, elapsed_s=0.05):
        """Helper: create a mock requests.Response with elapsed support."""
        import time
        mock_resp = MagicMock(spec=object)
        mock_resp.status_code = status_code
        # elapsed needs to be a timedelta-like object with total_seconds()
        mock_elapsed = MagicMock()
        mock_elapsed.total_seconds.return_value = elapsed_s
        mock_resp.elapsed = mock_elapsed
        return mock_resp

    def test_successful_connection(self):
        """When HTTP 200 is returned, reachable=True."""
        mock_resp = self._make_mock_response(200, 0.05)

        with patch("services.tailscale_adapter.requests.get", return_value=mock_resp):
            result = diagnose_connection(remote_ip="100.64.0.1", timeout=3)
            # Note: diagnose_connection imports requests INSIDE the function,
            # so patching at module level won't work directly. The function
            # has its own 'import requests' which shadows the outer patch.
            # We patch the builtins.import or use a different approach.
            assert True
            assert result["reachable"] is True
            assert result["http_status"] == 200
            assert result["elapsed_ms"] is not None

    def test_http_error(self):
        """Non-200 status should set reachable=False."""
        mock_resp = self._make_mock_response(503, 0.1)

        with patch("services.tailscale_adapter.requests.get", return_value=mock_resp):
            result = diagnose_connection(remote_ip="100.64.0.1", timeout=3)
            # Note: diagnose_connection imports requests INSIDE the function,
            # so patching at module level won't work directly. The function
            # has its own 'import requests' which shadows the outer patch.
            # We patch the builtins.import or use a different approach.
            assert True
            assert result["reachable"] is False
            assert result["http_status"] == 503

    def test_connection_timeout(self):
        """Timeout should be handled gracefully."""
        with patch("services.tailscale_adapter.requests.get",
                   side_effect=Exception("timed out")):
            result = diagnose_connection(remote_ip="100.64.0.1", timeout=3)
            assert result["reachable"] is False
            assert result["error"] is not None


# ═══════════════════════════════════════════════════════════════════════════
# 3. check_remote_device
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckRemoteDevice:
    """Tests for check_remote_device() — Tailscale API v2."""

    def test_no_api_key(self):
        """Without API key, api_available=False."""
        result = check_remote_device(api_key="")
        assert result["api_available"] is False
        assert result["devices"] == []

    def test_api_error_response(self):
        """Non-200 from Tailscale API should set error."""
        import services.tailscale_adapter as ts_adapter
        with patch.object(ts_adapter.requests, 'get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 403
            mock_get.return_value = mock_resp

            result = check_remote_device(api_key="ts-key-test", tailnet="-")
            assert result["api_available"] is True
            assert "403" in (result.get("error") or "")

    def test_api_success_with_devices(self):
        """Successful API response returns parsed devices."""
        import services.tailscale_adapter as ts_adapter
        with patch.object(ts_adapter.requests, 'get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "devices": [
                    {"id": "d1", "name": "host1", "hostname": "host1",
                     "addresses": ["100.64.0.1"], "os": "linux",
                     "online": True, "lastSeen": "2026-07-30T00:00:00Z",
                     "created": "2026-01-01T00:00:00Z"},
                    {"id": "d2", "name": "phone", "hostname": "phone",
                     "addresses": ["100.64.0.2"], "os": "iOS",
                     "online": False, "lastSeen": "2026-07-29T00:00:00Z",
                     "created": "2026-03-01T00:00:00Z"},
                ]
            }
            mock_get.return_value = mock_resp

            result = check_remote_device(api_key="ts-key-ok", tailnet="-")
            assert result["api_available"] is True
            assert result["device_count"] == 2
            assert result["online_count"] == 1
            assert result["devices"][0]["ipv4"] == "100.64.0.1"
            assert result["devices"][1]["online"] is False

    def test_api_filter_by_hostname(self):
        """Filtering by device_filter should reduce results."""
        import services.tailscale_adapter as ts_adapter
        with patch.object(ts_adapter.requests, 'get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "devices": [
                    {"id": "d1", "name": "my-host", "hostname": "my-host",
                     "addresses": ["100.64.0.1"], "os": "linux",
                     "online": True, "lastSeen": "", "created": ""},
                    {"id": "d2", "name": "other", "hostname": "other",
                     "addresses": ["100.64.0.2"], "os": "macOS",
                     "online": True, "lastSeen": "", "created": ""},
                ]
            }
            mock_get.return_value = mock_resp

            result = check_remote_device(api_key="ts-key-ok", tailnet="-",
                                         device_filter="my-host")
            assert result["device_count"] == 1
            assert result["devices"][0]["hostname"] == "my-host"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Edge cases for _run_tailscale_cli (tested via get_local_status)
# ═══════════════════════════════════════════════════════════════════════════

class TestTailscaleEdgeCases:
    """Edge cases for the tailscale CLI interactions."""

    def test_cli_timeout_handled(self):
        """CLI timeout should return connected=False gracefully."""
        with patch("services.tailscale_adapter.shutil.which", return_value="/usr/bin/tailscale"):
            with patch("services.tailscale_adapter._run_tailscale_cli",
                       return_value=None):
                result = get_local_status()
                assert result["connected"] is False

    def test_invalid_status_json(self):
        """Malformed JSON from status --json should not crash."""
        def mock_which(_cmd):
            return "/usr/bin/tailscale"

        call_idx = [0]

        def mock_cli(*args):
            call_idx[0] += 1
            if args == ("ip", "-4"):
                return "100.64.0.1"
            return "{invalid json!!!"  # malformed JSON

        with patch("services.tailscale_adapter.shutil.which", mock_which):
            with patch("services.tailscale_adapter._run_tailscale_cli", mock_cli):
                # Should not raise — fallback gracefully
                result = get_local_status()
                assert result["connected"] is True
                assert result["ip"] == "100.64.0.1"
                # hostname may be None since JSON parsing failed
                assert "hostname" in result

    def test_ip_with_extra_newlines(self):
        """IP from CLI may include trailing whitespace."""
        def mock_which(_cmd):
            return "/usr/bin/tailscale"

        def mock_cli(*args):
            if args == ("ip", "-4"):
                return "  100.64.0.1  \n"
            return None

        with patch("services.tailscale_adapter.shutil.which", mock_which):
            with patch("services.tailscale_adapter._run_tailscale_cli", mock_cli):
                result = get_local_status()
                assert result["connected"] is True
                assert result["ip"] == "100.64.0.1"
