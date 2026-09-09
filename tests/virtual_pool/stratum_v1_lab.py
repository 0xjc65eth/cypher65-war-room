"""Stateful local Stratum V1 simulator used only by automated tests."""

from contextlib import AbstractContextManager
import json
import socketserver
import threading
import time


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        lab = self.server.lab
        raw_request = self.rfile.readline(4097)
        with lab._lock:
            lab.request_count += 1
            request_number = lab.request_count
            lab.last_request = raw_request

        if lab.mode == "silent":
            time.sleep(lab.silent_seconds)
            return
        if lab.mode == "invalid_json":
            self.wfile.write(b"not-json\n")
            return
        if lab.mode == "oversized":
            self.wfile.write(b"{" + b"x" * lab.oversized_bytes + b"\n")
            return
        if lab.mode == "rejected":
            response = {
                "id": 1,
                "result": None,
                "error": [20, "remote-secret-detail", None],
            }
            self.wfile.write(
                json.dumps(response, separators=(",", ":")).encode("ascii")
            )
            self.wfile.write(b"\n")
            return

        try:
            request = json.loads(raw_request.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = {"id": None, "result": None, "error": [20, "invalid", None]}
        else:
            if (
                not isinstance(request, dict)
                or request.get("method") != "mining.subscribe"
            ):
                response = {
                    "id": request.get("id") if isinstance(request, dict) else None,
                    "result": None,
                    "error": [20, "unsupported", None],
                }
            else:
                response = {
                    "id": request.get("id"),
                    "result": [
                        [["mining.notify", f"session-{request_number}"]],
                        f"{request_number:08x}",
                        4,
                    ],
                    "error": None,
                }
        self.wfile.write(json.dumps(response, separators=(",", ":")).encode("ascii"))
        self.wfile.write(b"\n")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class StratumV1Lab(AbstractContextManager):
    def __init__(
        self,
        *,
        mode: str = "success",
        silent_seconds: float = 0.2,
        oversized_bytes: int = 4096,
    ) -> None:
        self.mode = mode
        self.silent_seconds = silent_seconds
        self.oversized_bytes = oversized_bytes
        self.request_count = 0
        self.last_request = b""
        self._lock = threading.Lock()
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.lab = self
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)
