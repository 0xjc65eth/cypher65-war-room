"""Stateful local Stratum V2 Common-layer simulator used only by tests."""

from contextlib import AbstractContextManager
import socketserver
import threading
import time

MSG_SETUP_CONNECTION = 0x00
MSG_SETUP_CONNECTION_SUCCESS = 0x01
MSG_SETUP_CONNECTION_ERROR = 0x02


def _frame(message_type: int, payload: bytes) -> bytes:
    return (
        (0).to_bytes(2, "little")
        + bytes([message_type])
        + len(payload).to_bytes(3, "little")
        + payload
    )


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        lab = self.server.lab
        header = self.request.recv(6)
        with lab._lock:
            lab.request_count += 1
            lab.last_request = header

        if lab.mode == "silent":
            time.sleep(lab.silent_seconds)
            return
        if lab.mode == "noise":
            self.wfile.write(
                b"\x01\x00" + b"\x00" + (48).to_bytes(3, "little") + b"N" * 48
            )
            return
        if lab.mode == "oversized":
            self.wfile.write(
                (0).to_bytes(2, "little")
                + bytes([MSG_SETUP_CONNECTION_SUCCESS])
                + (lab.oversized_bytes).to_bytes(3, "little")
            )
            return
        if lab.mode == "invalid_frame":
            self.wfile.write(_frame(MSG_SETUP_CONNECTION_SUCCESS, b"\x00\x02"))
            return
        if lab.mode == "wrong_type":
            self.wfile.write(_frame(0x10, b"\x00"))
            return
        if lab.mode == "rejected":
            self.wfile.write(_frame(MSG_SETUP_CONNECTION_ERROR, b"secret-error-detail"))
            return

        if len(header) < 6:
            return
        length = int.from_bytes(header[3:6], "little")
        payload = self.request.recv(length) if length else b""
        with lab._lock:
            lab.last_request = header + payload
        if header[2] != MSG_SETUP_CONNECTION:
            self.wfile.write(_frame(MSG_SETUP_CONNECTION_ERROR, b"unsupported"))
            return
        success = (2).to_bytes(2, "little") + (0).to_bytes(4, "little")
        self.wfile.write(_frame(MSG_SETUP_CONNECTION_SUCCESS, success))


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class StratumV2Lab(AbstractContextManager):
    def __init__(
        self,
        *,
        mode: str = "success",
        silent_seconds: float = 0.2,
        oversized_bytes: int = 8192,
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
