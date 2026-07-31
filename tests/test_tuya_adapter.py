"""
Unit tests for services/tuya_adapter.py

Tests cover:
  - Token acquisition (success/failure/cache)
  - TuyaCloudAdapter.list_devices()
  - TuyaCloudAdapter.get_status()
  - TuyaCloudAdapter.power_on/power_off/toggle()
  - TuyaCloudAdapter.validate_credentials()
  - _send_command with switch_1/switch fallback
  - Edge cases (empty credentials, API errors, token expiry)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from services.tuya_adapter import TuyaCloudAdapter, _get_token, _token_cache


# ═══════════════════════════════════════════════════════════════════════════
# 1. Token acquisition
# ═══════════════════════════════════════════════════════════════════════════

class TestTokenAcquisition:
    """Tests for _get_token() — OAuth token from Tuya Cloud."""

    def cleanup(self):
        _token_cache.clear()

    def test_token_success(self):
        """Successful token request returns access_token and caches it."""
        self.cleanup()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "result": {
                "access_token": "tuya_token_123",
                "expire_time": 7200,
                "refresh_token": "refresh_123",
                "uid": "user_456",
            }
        }
        with patch("services.tuya_adapter.requests.get", return_value=mock_resp):
            token = _get_token("test_id", "test_secret", "us")
            assert token == "tuya_token_123"
            cache_key = "us:test_id"
            assert cache_key in _token_cache
            assert _token_cache[cache_key]["access_token"] == "tuya_token_123"
            assert _token_cache[cache_key]["uid"] == "user_456"

    def test_token_failure(self):
        """Failed token request returns None."""
        self.cleanup()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": False,
            "msg": "invalid client_id",
        }
        with patch("services.tuya_adapter.requests.get", return_value=mock_resp):
            token = _get_token("bad_id", "bad_secret", "us")
            assert token is None

    def test_token_cached(self):
        """Subsequent calls should use cached token."""
        self.cleanup()
        _token_cache["us:cached_id"] = {
            "access_token": "cached_token",
            "expires_at": 9999999999,  # far future
            "refresh_token": "",
            "uid": "",
        }
        with patch("services.tuya_adapter.requests.get") as mock_get:
            token = _get_token("cached_id", "secret", "us")
            assert token == "cached_token"
            mock_get.assert_not_called()  # No HTTP call — used cache

    def test_token_expired_cache(self):
        """Expired cache should trigger refresh."""
        self.cleanup()
        _token_cache["us:expired_id"] = {
            "access_token": "old_token",
            "expires_at": 100,  # year 1970 — definitely expired
            "refresh_token": "",
            "uid": "",
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "result": {
                "access_token": "fresh_token",
                "expire_time": 7200,
                "refresh_token": "fresh_refresh",
                "uid": "",
            }
        }
        with patch("services.tuya_adapter.requests.get", return_value=mock_resp):
            token = _get_token("expired_id", "secret", "us")
            assert token == "fresh_token"
            assert _token_cache["us:expired_id"]["access_token"] == "fresh_token"


# ═══════════════════════════════════════════════════════════════════════════
# 2. TuyaCloudAdapter.list_devices
# ═══════════════════════════════════════════════════════════════════════════

class TestListDevices:
    """Tests for TuyaCloudAdapter.list_devices()."""

    def test_no_credentials(self):
        """Missing credentials should return error list."""
        adapter = TuyaCloudAdapter()
        devices = adapter.list_devices(access_id="", access_secret="")
        assert len(devices) == 1
        assert "not configured" in devices[0]["name"]

    def test_device_list_with_plugs(self):
        """Valid credentials should return filtered plug devices."""
        adapter = TuyaCloudAdapter()
        mock_json = {
            "success": True,
            "result": [
                {"id": "plug1", "name": "Garage Plug", "online": True,
                 "category": "cz", "status": [{"code": "switch_1", "value": True}]},
                {"id": "plug2", "name": "Office Plug", "online": True,
                 "category": "kg", "status": [{"code": "switch_1", "value": False}]},
                {"id": "sensor1", "name": "Temp Sensor", "online": True,
                 "category": "wsdcg", "status": []},  # not a plug — should be filtered out
            ]
        }
        with patch.object(adapter, '_send_command'):  # prevent real calls
            with patch("services.tuya_adapter._tuya_request", return_value=mock_json):
                devices = adapter.list_devices(access_id="id", access_secret="secret")
                # Only 2 plugs (sensor should be filtered out)
                assert len([d for d in devices if "not configured" not in d["name"]]) == 2
                plug1 = next(d for d in devices if d["id"] == "plug1")
                assert plug1["state"] is True
                assert plug1["vendor"] == "tuya"

    def test_empty_device_list(self):
        """No devices should return empty list."""
        adapter = TuyaCloudAdapter()
        mock_json = {"success": True, "result": []}
        with patch("services.tuya_adapter._tuya_request", return_value=mock_json):
            devices = adapter.list_devices(access_id="id", access_secret="secret")
            assert len([d for d in devices if "not configured" not in d["name"]]) == 0

    def test_api_error_returns_error_list(self):
        """API error should return error list with message."""
        adapter = TuyaCloudAdapter()
        mock_json = {"success": False, "error": "API rate limited"}
        with patch("services.tuya_adapter._tuya_request", return_value=mock_json):
            devices = adapter.list_devices(access_id="id", access_secret="secret")
            assert len(devices) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 3. TuyaCloudAdapter.get_status
# ═══════════════════════════════════════════════════════════════════════════

class TestGetStatus:
    """Tests for TuyaCloudAdapter.get_status()."""

    def test_status_with_power(self):
        """Status should return state and power consumption."""
        adapter = TuyaCloudAdapter()
        mock_json = {
            "success": True,
            "result": [
                {"code": "switch_1", "value": True},
                {"code": "cur_power", "value": 150},  # 15.0W (Tuya returns 10x)
            ]
        }
        with patch("services.tuya_adapter._tuya_request", return_value=mock_json):
            status = adapter.get_status("plug1", access_id="id", access_secret="secret")
            assert status["success"] is True
            assert status["state"] is True
            assert status["power_watts"] == 15.0  # 150 / 10

    def test_status_offline_plug(self):
        """Plug that's off should show state=False."""
        adapter = TuyaCloudAdapter()
        mock_json = {
            "success": True,
            "result": [
                {"code": "switch_1", "value": False},
            ]
        }
        with patch("services.tuya_adapter._tuya_request", return_value=mock_json):
            status = adapter.get_status("plug1", access_id="id", access_secret="secret")
            assert status["state"] is False

    def test_status_no_credentials(self):
        """Missing credentials returns error."""
        adapter = TuyaCloudAdapter()
        status = adapter.get_status("plug1", access_id="", access_secret="")
        assert status["success"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. Power commands (on/off/toggle)
# ═══════════════════════════════════════════════════════════════════════════

class TestPowerCommands:
    """Tests for power_on(), power_off(), toggle()."""

    def test_power_on_success(self):
        """power_on() returns success with new_state=True."""
        adapter = TuyaCloudAdapter()
        with patch.object(adapter, '_send_command', return_value={
            "success": True, "new_state": True
        }):
            result = adapter.power_on("plug1", access_id="id", access_secret="secret")
            assert result["success"] is True
            assert result["new_state"] is True

    def test_power_off_success(self):
        """power_off() returns success with new_state=False."""
        adapter = TuyaCloudAdapter()
        with patch.object(adapter, '_send_command', return_value={
            "success": True, "new_state": False
        }):
            result = adapter.power_off("plug1", access_id="id", access_secret="secret")
            assert result["success"] is True
            assert result["new_state"] is False

    def test_toggle_from_on_to_off(self):
        """toggle() reads status, then flips."""
        adapter = TuyaCloudAdapter()
        with patch.object(adapter, 'get_status', return_value={
            "success": True, "state": True
        }):
            with patch.object(adapter, '_send_command', return_value={
                "success": True, "new_state": False
            }):
                result = adapter.toggle("plug1", access_id="id", access_secret="secret")
                assert result["success"] is True
                assert result["new_state"] is False

    def test_toggle_from_off_to_on(self):
        """toggle() flips off→on."""
        adapter = TuyaCloudAdapter()
        with patch.object(adapter, 'get_status', return_value={
            "success": True, "state": False
        }):
            with patch.object(adapter, '_send_command', return_value={
                "success": True, "new_state": True
            }):
                result = adapter.toggle("plug1", access_id="id", access_secret="secret")
                assert result["success"] is True
                assert result["new_state"] is True

    def test_toggle_fails_if_status_fails(self):
        """toggle() errors if get_status fails."""
        adapter = TuyaCloudAdapter()
        with patch.object(adapter, 'get_status', return_value={
            "success": False, "error": "plug offline"
        }):
            result = adapter.toggle("plug1", access_id="id", access_secret="secret")
            assert result["success"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 5. _send_command with fallback
# ═══════════════════════════════════════════════════════════════════════════

class TestSendCommandFallback:
    """Tests for _send_command() fallback from switch_1 to switch."""

    def test_switch_1_succeeds_first_try(self):
        """Primary code 'switch_1' succeeds."""
        adapter = TuyaCloudAdapter()
        call_count = [0]

        def mock_tuya_request(method, path, access_id, access_secret, region, body):
            call_count[0] += 1
            assert body["commands"][0]["code"] == "switch_1"
            return {"success": True, "result": {}}

        with patch("services.tuya_adapter._tuya_request", mock_tuya_request):
            result = adapter._send_command("plug1", "switch_1", True,
                                           access_id="id", access_secret="secret")
            assert result["success"] is True
            assert call_count[0] == 1  # only one attempt

    def test_switch_1_fails_fallback_to_switch(self):
        """Fallback to 'switch' when 'switch_1' fails."""
        adapter = TuyaCloudAdapter()
        call_count = [0]

        def mock_tuya_request(method, path, access_id, access_secret, region, body):
            call_count[0] += 1
            code = body["commands"][0]["code"]
            if call_count[0] == 1:
                assert code == "switch_1"
                return {"success": False, "error": "code not found"}
            else:
                assert code == "switch"  # fallback
                return {"success": True, "result": {}}

        with patch("services.tuya_adapter._tuya_request", mock_tuya_request):
            result = adapter._send_command("plug1", "switch_1", True,
                                           access_id="id", access_secret="secret")
            assert result["success"] is True
            assert result["code_used"] == "switch"
            assert call_count[0] == 2  # tried both codes

    def test_both_switch_codes_fail(self):
        """Both switch_1 and switch fail — returns error."""
        adapter = TuyaCloudAdapter()
        with patch("services.tuya_adapter._tuya_request",
                   return_value={"success": False, "error": "command failed"}):
            result = adapter._send_command("plug1", "switch_1", True,
                                           access_id="id", access_secret="secret")
            assert result["success"] is False
            assert "command failed" in result.get("error", "")


# ═══════════════════════════════════════════════════════════════════════════
# 6. validate_credentials
# ═══════════════════════════════════════════════════════════════════════════

class TestValidateCredentials:
    """Tests for TuyaCloudAdapter.validate_credentials()."""

    def test_valid_credentials(self):
        """Valid credentials return valid=True with uid."""
        with patch("services.tuya_adapter._get_token", return_value="valid_token"):
            _token_cache["us:test_key"] = {"access_token": "valid_token",
                                            "expires_at": 9999999999,
                                            "refresh_token": "",
                                            "uid": "user_abc"}
            adapter = TuyaCloudAdapter()
            result = adapter.validate_credentials(access_id="test_key",
                                                   access_secret="secret",
                                                   region="us")
            assert result["valid"] is True
            assert result["uid"] == "user_abc"

    def test_invalid_credentials(self):
        """Invalid credentials return valid=False."""
        with patch("services.tuya_adapter._get_token", return_value=None):
            adapter = TuyaCloudAdapter()
            result = adapter.validate_credentials(access_id="bad_key",
                                                   access_secret="bad_secret",
                                                   region="us")
            assert result["valid"] is False

    def test_missing_credentials(self):
        """Missing credentials return valid=False with error."""
        adapter = TuyaCloudAdapter()
        result = adapter.validate_credentials(access_id="", access_secret="")
        assert result["valid"] is False
        assert "missing" in result.get("error", "")
