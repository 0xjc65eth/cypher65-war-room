"""AxeOS POST/PATCH must fail closed on HTTP errors (Issue #422)."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from axe_fleet.connector import AxeOSConnector, AxeOSConnectorError


def _response(status, text="", json_data=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    if json_data is not None:
        r.json.return_value = json_data
    else:
        r.json.side_effect = json.JSONDecodeError("x", text or "x", 0)

    def _raise():
        if status >= 400:
            err = requests.exceptions.HTTPError(response=r)
            raise err

    r.raise_for_status.side_effect = _raise
    return r


def test_post_http_500_is_connector_error():
    conn = AxeOSConnector("192.168.1.50")
    with patch(
        "axe_fleet.connector.requests.post", return_value=_response(500, "fail")
    ):
        with pytest.raises(AxeOSConnectorError) as ei:
            conn._post("/api/system/restart")
    assert "status=500" in str(ei.value)


def test_patch_http_400_is_connector_error():
    conn = AxeOSConnector("192.168.1.50")
    with patch(
        "axe_fleet.connector.requests.patch", return_value=_response(400, "bad")
    ):
        with pytest.raises(AxeOSConnectorError) as ei:
            conn._patch("/api/system", {"frequency": 500})
    assert "status=400" in str(ei.value)


def test_post_plain_text_2xx_is_success():
    conn = AxeOSConnector("192.168.1.50")
    with patch("axe_fleet.connector.requests.post", return_value=_response(200, "OK")):
        assert conn._post("/api/system/restart") == {"success": True}


def test_post_json_2xx_is_parsed():
    conn = AxeOSConnector("192.168.1.50")
    with patch(
        "axe_fleet.connector.requests.post",
        return_value=_response(200, '{"success": true}', {"success": True}),
    ):
        assert conn._post("/api/system/identify") == {"success": True}
