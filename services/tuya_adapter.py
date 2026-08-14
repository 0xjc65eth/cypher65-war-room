"""
CYPHER65 // TUYA CLOUD ADAPTER
==============================
Smart plug control via Tuya IoT Cloud API (OpenAPI).

Credentials are read from settings DB at call time (not hardcoded).
Uses the Tuya IoT Core REST API with Bearer token auth.

Docs: https://developer.tuya.com/en/docs/cloud/
"""

import hashlib
import hmac
import json
import logging
import time
import requests
from typing import Optional

from .power_outlet import PowerOutletAdapter

log = logging.getLogger("cypher65.tuya")

# ── Constants ──────────────────────────────────────────────────────────────
TUYA_BASE_URLS = {
    "us": "https://openapi.tuyaus.com",
    "eu": "https://openapi.tuyaeu.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}
TUYA_GRANT_TYPE = 1  # OAuth 2.0 client credentials
TUYA_TOKEN_TTL_BUFFER = 120  # refresh token 2min before expiry
TUYA_DEFAULT_TIMEOUT = 10  # seconds

# ── In-memory token cache (per credential set) ────────────────────────────
# Keyed by access_id so multiple accounts can coexist.
_token_cache: dict[str, dict] = {}


def _tuya_sign(method: str, path: str, headers: dict, body: str, secret: str) -> str:
    """Generate HMAC-SHA256 signature for Tuya API request."""
    # Build string-to-sign: method + \\n + Content-SHA256 + \\n + headers + \\n + path
    content_hash = (
        hashlib.sha256(body.encode("utf-8")).hexdigest()
        if body
        else hashlib.sha256(b"").hexdigest()
    )
    header_str = "\n".join(
        f"{k}:{v}" for k, v in sorted(headers.items()) if k.startswith("tuya-")
    )
    str_to_sign = f"{method}\n{content_hash}\n{header_str}\n{path}"
    return hmac.new(
        secret.encode("utf-8"),
        str_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _get_token(access_id: str, access_secret: str, region: str = "us") -> Optional[str]:
    """Obtain or refresh a Tuya access token.
    Returns the access_token string or None on failure.
    """
    global _token_cache
    cache_key = f"{region}:{access_id}"

    # Check cache freshness
    cached = _token_cache.get(cache_key)
    if cached:
        expires_at = cached.get("expires_at", 0)
        if time.time() < expires_at - TUYA_TOKEN_TTL_BUFFER:
            return cached["access_token"]

    base_url = TUYA_BASE_URLS.get(region, TUYA_BASE_URLS["us"])
    path = "/v1.0/token?grant_type=1"
    t = int(time.time() * 1000)

    headers = {
        "client_id": access_id,
        "sign": hashlib.sha256(
            f"{access_id}{access_secret}{t}".encode("utf-8")
        ).hexdigest(),
        "t": str(t),
        "sign_method": "HMAC-SHA256",
        # Issue #150 — NÃO aplicar nonce monotônico aqui: a Tuya valida a
        # recência do `t` (janela de tolerância), não a unicidade; o nonce
        # vazio é o esperado e não entra na string assinada (_tuya_sign só
        # inclui headers `tuya-*`).
        "nonce": "",
        "stringToSign": "",
    }

    try:
        r = requests.get(
            f"{base_url}{path}", headers=headers, timeout=TUYA_DEFAULT_TIMEOUT
        )
        data = r.json()
        if data.get("success") and data.get("result"):
            token_data = data["result"]
            token = token_data.get("access_token")
            expire_secs = token_data.get("expire_time", 7200)
            _token_cache[cache_key] = {
                "access_token": token,
                "expires_at": time.time() + expire_secs,
                "refresh_token": token_data.get("refresh_token", ""),
                "uid": token_data.get("uid", ""),
            }
            return token
        else:
            log.error("[tuya] token error: %s", data.get("msg", "unknown"))
            return None
    except Exception as e:
        log.error("[tuya] token request failed: %s", e)
        return None


def _tuya_request(
    method: str,
    path: str,
    access_id: str,
    access_secret: str,
    region: str = "us",
    body: dict = None,
) -> dict:
    """Make an authenticated Tuya API request.
    Handles token acquisition, signing, and error handling.
    Returns the result dict (or error dict).
    """
    token = _get_token(access_id, access_secret, region)
    if not token:
        return {"success": False, "error": "failed to authenticate with Tuya Cloud"}

    base_url = TUYA_BASE_URLS.get(region, TUYA_BASE_URLS["us"])
    t = int(time.time() * 1000)
    body_str = json.dumps(body) if body else ""
    url = f"{base_url}{path}"

    # Headers for signing
    headers = {
        "client_id": access_id,
        "access_token": token,
        "t": str(t),
        "sign_method": "HMAC-SHA256",
        # Issue #150 — mesmo veredito do token: nonce vazio é o esperado da
        # Tuya (valida recência do `t`); monotonicidade NÃO se aplica aqui.
        "nonce": "",
    }

    # Sign the request
    headers["sign"] = _tuya_sign(method, path, headers, body_str, access_secret)

    try:
        r = requests.request(
            method,
            url,
            headers=headers,
            json=body if body else None,
            timeout=TUYA_DEFAULT_TIMEOUT,
        )
        data = r.json()
        if data.get("success"):
            return {"success": True, "result": data.get("result", {})}
        else:
            code = data.get("code", 0)
            msg = data.get("msg", "unknown error")
            # Token expired — clear cache and retry once
            if code in (1010, 1011, 1106):  # token expired/invalid
                global _token_cache
                cache_key = f"{region}:{access_id}"
                _token_cache.pop(cache_key, None)
                return _tuya_request(
                    method, path, access_id, access_secret, region, body
                )
            log.error("[tuya] API error %s: %s (path=%s)", code, msg, path)
            return {"success": False, "error": f"Tuya API error {code}: {msg}"}
    except Exception as e:
        log.error("[tuya] request failed: %s", e)
        return {"success": False, "error": str(e)}


class TuyaCloudAdapter(PowerOutletAdapter):
    """Adapter for Tuya smart plugs controlled via Tuya IoT Cloud API.

    Credentials are read from kwargs passed to each method, allowing
    the caller (route handler) to pull them from settings DB per-request.
    """

    def list_devices(self, **kwargs) -> list[dict]:
        """List all devices linked to the Tuya account.

        Expects kwargs:
          access_id, access_secret, region (optional, default 'us'),
          uid (optional) — if not provided, uses the account-level device list.

        Returns filtered list of smart plug devices only.
        """
        access_id = kwargs.get("access_id", "")
        access_secret = kwargs.get("access_secret", "")
        region = kwargs.get("region", "us")
        uid = kwargs.get("uid", "")

        if not access_id or not access_secret:
            return self._error_list("Tuya credentials not configured")

        if uid:
            path = f"/v1.0/users/{uid}/devices"
        else:
            path = "/v1.0/iot-03/associated-users/devices"

        result = _tuya_request("GET", path, access_id, access_secret, region)
        if not result.get("success"):
            return self._error_list(result.get("error", "failed to list devices"))

        raw_devices = result.get("result", [])
        if isinstance(raw_devices, dict):
            raw_devices = raw_devices.get("devices", raw_devices.get("list", []))

        plugs = []
        for d in raw_devices:
            # Only include smart plugs (category 'cz' or 'kg' or name hints)
            cat = (d.get("category") or d.get("device_type") or "").lower()
            name = (d.get("name") or "").lower()
            if (
                "plug" in cat
                or "cz" in cat
                or "kg" in cat
                or "socket" in cat
                or "switch" in cat
                or "plug" in name
            ):
                plugs.append(
                    {
                        "id": d.get("id", ""),
                        "name": d.get("name", "Unknown Plug"),
                        "online": d.get("online", False),
                        "state": self._parse_state(d),
                        "vendor": "tuya",
                        "category": cat,
                        "product_id": d.get("product_id", ""),
                        "model": d.get("model", ""),
                    }
                )

        return plugs

    def get_status(self, device_id: str, **kwargs) -> dict:
        """Get current status of a Tuya smart plug.

        Returns power state, consumption, and metadata.
        """
        access_id = kwargs.get("access_id", "")
        access_secret = kwargs.get("access_secret", "")
        region = kwargs.get("region", "us")

        if not access_id or not access_secret:
            return {"success": False, "error": "Tuya credentials not configured"}

        path = f"/v1.0/devices/{device_id}/status"
        result = _tuya_request("GET", path, access_id, access_secret, region)
        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "status check failed"),
            }

        status_list = result.get("result", [])
        if isinstance(status_list, dict):
            status_list = status_list.get("status", status_list)

        state = False
        power_w = None
        for s in status_list or []:
            code = s.get("code", "")
            val = s.get("value")
            if code in ("switch_1", "switch_usb1", "switch"):
                state = bool(val)
            elif code in ("cur_power", "power"):
                power_w = (
                    float(val) / 10.0 if val else None
                )  # Tuya returns decimilliwatts
            elif code == "cur_current":
                pass  # mA — not surfaced for now

        return {
            "success": True,
            "device_id": device_id,
            "state": state,
            "online": True,
            "power_watts": power_w,
        }

    def power_on(self, device_id: str, **kwargs) -> dict:
        return self._send_command(device_id, "switch_1", True, **kwargs)

    def power_off(self, device_id: str, **kwargs) -> dict:
        return self._send_command(device_id, "switch_1", False, **kwargs)

    def toggle(self, device_id: str, **kwargs) -> dict:
        """Toggle: read current state first, then flip it."""
        status = self.get_status(device_id, **kwargs)
        if not status.get("success"):
            return {
                "success": False,
                "error": status.get("error", "cannot read state for toggle"),
            }

        new_state = not status.get("state", False)
        return self._send_command(device_id, "switch_1", new_state, **kwargs)

    def validate_credentials(self, **kwargs) -> dict:
        """Validate Tuya credentials by attempting to get a token (lightweight)."""
        access_id = kwargs.get("access_id", "")
        access_secret = kwargs.get("access_secret", "")
        region = kwargs.get("region", "us")

        if not access_id or not access_secret:
            return {"valid": False, "error": "missing credentials"}

        token = _get_token(access_id, access_secret, region)
        if token:
            uid = _token_cache.get(f"{region}:{access_id}", {}).get("uid", "")
            return {"valid": True, "uid": uid, "region": region}
        return {"valid": False, "error": "invalid credentials or region"}

    # ── Internals ─────────────────────────────────────────────────────

    def _send_command(self, device_id: str, code: str, value, **kwargs) -> dict:
        """Send a command to a Tuya device.
        Falls back from 'switch_1' to 'switch' if the first attempt fails
        (some plugs use different DP codes).
        """
        access_id = kwargs.get("access_id", "")
        access_secret = kwargs.get("access_secret", "")
        region = kwargs.get("region", "us")

        if not access_id or not access_secret:
            return {"success": False, "error": "Tuya credentials not configured"}

        # Try primary code, then fallback
        codes_to_try = [code]
        if code == "switch_1":
            codes_to_try.append("switch")
        elif code == "switch":
            codes_to_try.append("switch_1")

        last_error = None
        for try_code in codes_to_try:
            path = f"/v1.0/devices/{device_id}/commands"
            body = {"commands": [{"code": try_code, "value": value}]}
            result = _tuya_request("POST", path, access_id, access_secret, region, body)

            if result.get("success"):
                if try_code != code:
                    log.info(
                        "[tuya] device %s used fallback code '%s' instead of '%s'",
                        device_id[:8],
                        try_code,
                        code,
                    )
                return {
                    "success": True,
                    "new_state": bool(value),
                    "code_used": try_code,
                }
            last_error = result.get("error", "command failed")

        return {"success": False, "error": last_error}

    @staticmethod
    def _parse_state(device_dict: dict) -> Optional[bool]:
        """Extract power state from a device dict returned by list_devices."""
        status_list = device_dict.get("status", device_dict.get("data", []))
        if isinstance(status_list, dict):
            status_list = status_list.get("status", status_list)

        for s in status_list or []:
            if isinstance(s, dict):
                code = s.get("code", "")
                if code in ("switch_1", "switch_usb1", "switch"):
                    return bool(s.get("value", False))
        return None

    @staticmethod
    def _error_list(msg: str) -> list:
        log.warning("[tuya] %s", msg)
        return [
            {
                "id": "",
                "name": f"⚠ {msg}",
                "online": False,
                "state": None,
                "vendor": "tuya",
            }
        ]
