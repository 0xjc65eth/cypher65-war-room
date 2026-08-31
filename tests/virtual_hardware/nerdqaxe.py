"""Small stateful NerdQaxe/AxeOS HTTP laboratory device.

This is a network service, not a patched adapter. The production
``BitaxeAdapter`` communicates with it over HTTP using the same endpoints used
for physical AxeOS devices.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class VirtualNerdQaxe:
    def __init__(self, *, uptime_seconds: int = 7200):
        self.uptime_seconds = uptime_seconds
        self.restart_count = 0
        self._offline_responses = 0
        self._server = None
        self._thread = None

    @property
    def address(self) -> str:
        if self._server is None:
            raise RuntimeError("virtual NerdQaxe is not running")
        host, port = self._server.server_address
        return f"{host}:{port}"

    def start(self) -> "VirtualNerdQaxe":
        device = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802 - stdlib handler API
                if self.path != "/api/system/restart":
                    self._json(404, {"error": "not found"})
                    return
                device.restart_count += 1
                device._offline_responses = 1
                self._json(200, {"ack": True})

            def do_GET(self):  # noqa: N802 - stdlib handler API
                if self.path != "/api/system/info":
                    self._json(404, {"error": "not found"})
                    return
                if device._offline_responses:
                    device._offline_responses -= 1
                    self._json(503, {"status": "rebooting"})
                    return
                if device.restart_count:
                    device.uptime_seconds = 3
                self._json(
                    200,
                    {
                        "model": "NerdQaxe++",
                        "firmware": "AxeOS 2.4",
                        "hostname": "virtual-nerdqaxe",
                        "hashRate": 4.8e12,
                        "temp": 58.0,
                        "uptimeSeconds": device.uptime_seconds,
                        "sharesAccepted": 42,
                        "sharesRejected": 0,
                    },
                )

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def __enter__(self) -> "VirtualNerdQaxe":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.close()
