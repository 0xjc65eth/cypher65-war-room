"""
Unit tests for axe_fleet/routes.py — remote status, power plugs, power-cycle

Tests cover:
  - _get_tuya_credentials() with mocked DB
  - _audit_power_action()
  - _execute_plug_command()
  - Helper functions (_fmt_hr, _fmt_uptime)
  - Flask route integration via test client
"""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════════════════════════════════════
# 1. Helper function tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFmtHr:
    """Tests for _fmt_hr() in axe_fleet/routes.py."""

    def test_hashes(self):
        from axe_fleet.routes import _fmt_hr
        assert _fmt_hr(500) == "500 H/s"

    def test_kilohashes(self):
        from axe_fleet.routes import _fmt_hr
        # NOTE: _fmt_hr doesn't have a KH/s level — jumps from <1e6 to MH/s
        # 1500 H/s < 1e6 → returns "1500 H/s"
        assert _fmt_hr(1500) == "1500 H/s"

    def test_megahashes(self):
        from axe_fleet.routes import _fmt_hr
        assert _fmt_hr(5_000_000) == "5.00 MH/s"

    def test_gigahashes(self):
        from axe_fleet.routes import _fmt_hr
        assert _fmt_hr(10_000_000_000) == "10.00 GH/s"

    def test_terahashes(self):
        from axe_fleet.routes import _fmt_hr
        assert _fmt_hr(5_200_000_000_000) == "5.20 TH/s"

    def test_petahashes(self):
        from axe_fleet.routes import _fmt_hr
        assert _fmt_hr(2_000_000_000_000_000) == "2.00 PH/s"


class TestFmtUptime:
    """Tests for _fmt_uptime() in axe_fleet/routes.py."""

    def test_zero(self):
        from axe_fleet.routes import _fmt_uptime
        assert _fmt_uptime(0) == "\u2014"

    def test_seconds_only(self):
        from axe_fleet.routes import _fmt_uptime
        assert _fmt_uptime(30) == "<1m"

    def test_minutes(self):
        from axe_fleet.routes import _fmt_uptime
        assert _fmt_uptime(300) == "5m"

    def test_hours(self):
        from axe_fleet.routes import _fmt_uptime
        assert _fmt_uptime(3600) == "1h"
        assert _fmt_uptime(7200) == "2h"

    def test_days(self):
        from axe_fleet.routes import _fmt_uptime
        assert _fmt_uptime(86400) == "1d"
        assert _fmt_uptime(172800) == "2d"

    def test_days_hours(self):
        from axe_fleet.routes import _fmt_uptime
        # 90000s = 1 day 1 hour (86400 + 3600)
        assert _fmt_uptime(90000) == "1d 1h"
        # 93784s = 1 day 2 hours (86400 + 7200 + remainder < 3600)
        result = _fmt_uptime(93784)
        assert "1d" in result
        assert "2h" in result


# ═══════════════════════════════════════════════════════════════════════════
# 2. _get_tuya_credentials()
# ═══════════════════════════════════════════════════════════════════════════

class TestGetTuyaCredentials:
    """Tests for _get_tuya_credentials() through tenant settings."""

    def test_reads_default_tenant_settings(self):
        """The self-host tenant reads its own settings before env fallback."""
        values = {
            "tuya_access_id": "tuya_id_123",
            "tuya_access_secret": "tuya_secret_456",
            "tuya_region": "eu",
            "tuya_uid": "uid_789",
        }
        with patch("services.settings.load_settings", return_value=values):
            with patch.dict("axe_fleet.routes.os.environ", {}, clear=True):
                from axe_fleet.routes import _get_tuya_credentials

                creds = _get_tuya_credentials()
        assert creds == {
            "access_id": "tuya_id_123",
            "access_secret": "tuya_secret_456",
            "region": "eu",
            "uid": "uid_789",
        }

    def test_default_tenant_falls_to_env(self):
        """Empty self-host settings may use operator environment values."""
        test_env = {
            "TUYA_ACCESS_ID": "env_id",
            "TUYA_ACCESS_SECRET": "env_secret",
            "TUYA_REGION": "cn",
        }
        with patch("services.settings.load_settings", return_value={}):
            with patch.dict("axe_fleet.routes.os.environ", test_env, clear=True):
                from axe_fleet.routes import _get_tuya_credentials

                creds = _get_tuya_credentials()
        assert creds.get("access_id") == "env_id"
        assert creds.get("access_secret") == "env_secret"
        assert creds.get("region") == "cn"


# ═══════════════════════════════════════════════════════════════════════════
# 3. _audit_power_action()
# ═══════════════════════════════════════════════════════════════════════════

class TestAuditPowerAction:
    """Tests for _audit_power_action() with mocked DB."""

    def test_success_logs_info(self):
        """Successful power action logs with INFO severity."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("axe_fleet.routes._get_db_internal", return_value=mock_conn):
            from axe_fleet.routes import _audit_power_action
            _audit_power_action("device_1", "power_on", True, "plug test")
            call_args = mock_cursor.execute.call_args
            sql = call_args[0][0]
            params = call_args[0][1]
            assert "INSERT INTO alert_history" in sql
            assert params[1] == "power_action"
            assert params[2] == "device_1"
            assert params[3] == "INFO"

    def test_failure_logs_warning(self):
        """Failed power action logs with WARN severity."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("axe_fleet.routes._get_db_internal", return_value=mock_conn):
            from axe_fleet.routes import _audit_power_action
            _audit_power_action("device_2", "power_off", False, "plug offline")
            call_args = mock_cursor.execute.call_args
            params = call_args[0][1]
            assert params[3] == "WARN"

    def test_db_error_does_not_crash(self):
        """DB error in audit should be caught silently."""
        with patch("axe_fleet.routes._get_db_internal",
                   side_effect=RuntimeError("DB down")):
            from axe_fleet.routes import _audit_power_action
            _audit_power_action("device_1", "toggle", True, "")  # no raise


# ═══════════════════════════════════════════════════════════════════════════
# 4. _execute_plug_command()
# ═══════════════════════════════════════════════════════════════════════════

class TestExecutePlugCommand:
    """Tests for _execute_plug_command() dispatch.
    These tests need a Flask app context for jsonify().
    """

    def _setup(self):
        """Create a minimal Flask app for jsonify context."""
        from flask import Flask
        app = Flask(__name__)
        return app.app_context()

    def test_power_on_dispatched(self):
        """power_on method should be called on adapter."""
        mock_adapter = MagicMock()
        mock_adapter.power_on.return_value = {"success": True, "new_state": True}

        with patch("services.tuya_adapter.TuyaCloudAdapter", return_value=mock_adapter):
            with patch("axe_fleet.routes._get_tuya_credentials",
                       return_value={"access_id": "id", "access_secret": "secret"}):
                with patch("axe_fleet.routes._audit_power_action"):
                    from axe_fleet.routes import _execute_plug_command
                    with self._setup():
                        resp = _execute_plug_command("plug1", "power_on")
                    assert resp.get_json()["success"] is True
                    mock_adapter.power_on.assert_called_once()

    def test_power_off_dispatched(self):
        """power_off method should be called on adapter."""
        mock_adapter = MagicMock()
        mock_adapter.power_off.return_value = {"success": True, "new_state": False}

        with patch("services.tuya_adapter.TuyaCloudAdapter", return_value=mock_adapter):
            with patch("axe_fleet.routes._get_tuya_credentials",
                       return_value={"access_id": "id", "access_secret": "secret"}):
                with patch("axe_fleet.routes._audit_power_action"):
                    from axe_fleet.routes import _execute_plug_command
                    with self._setup():
                        resp = _execute_plug_command("plug1", "power_off")
                    assert resp.get_json()["success"] is True
                    mock_adapter.power_off.assert_called_once()

    def test_unknown_method_returns_400(self):
        """Unknown method should return 400 error."""
        with patch("axe_fleet.routes._get_tuya_credentials",
                   return_value={"access_id": "id", "access_secret": "secret"}):
            from axe_fleet.routes import _execute_plug_command
            with self._setup():
                result, status = _execute_plug_command("plug1", "unknown_method")
            assert result.json["success"] is False
            assert status == 400

    def test_no_credentials_returns_200_with_error(self):
        """Missing credentials should not crash."""
        with patch("axe_fleet.routes._get_tuya_credentials",
                   return_value={"access_id": "", "access_secret": ""}):
            from axe_fleet.routes import _execute_plug_command
            with self._setup():
                result, status = _execute_plug_command("plug1", "power_on")
            assert result.json["success"] is False
            assert "not configured" in result.json["error"]


# ═══════════════════════════════════════════════════════════════════════════
# 5. parse_diff_to_float
# ═══════════════════════════════════════════════════════════════════════════

class TestParseDiffToFloat:
    """Tests for parse_diff_to_float() in axe_fleet/routes.py."""

    def test_tera_suffix(self):
        from axe_fleet.routes import parse_diff_to_float
        assert parse_diff_to_float("42.8T") == pytest.approx(42.8e12, rel=1e-3)

    def test_giga_suffix(self):
        from axe_fleet.routes import parse_diff_to_float
        assert parse_diff_to_float("5.5G") == pytest.approx(5.5e9, rel=1e-3)

    def test_no_suffix(self):
        from axe_fleet.routes import parse_diff_to_float
        assert parse_diff_to_float("5000") == 5000.0

    def test_number_input(self):
        from axe_fleet.routes import parse_diff_to_float
        assert parse_diff_to_float(50e12) == pytest.approx(50e12, rel=1e-3)

    def test_empty_string(self):
        from axe_fleet.routes import parse_diff_to_float
        assert parse_diff_to_float("") == 0.0
