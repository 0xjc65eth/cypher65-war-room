#!/usr/bin/env python3
"""Fail fast when the E2E Flask port is already occupied (Issue #437).

The Playwright runner starts app.py on PORT (default 8765) and then waits
for /api/healthz. If an older process is already answering 200 on that
port, the suite silently tests the wrong server and the wrong SQLite file.

This helper only diagnoses. It never kills the occupying process — the
operator chooses PORT=... or stops the other listener.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from typing import Iterable, Sequence

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def is_listening(host: str, port: int, timeout: float = 0.3) -> bool:
    """True when *host:port* accepts a TCP connection."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except OSError:
            return False
    return True


def describe_listeners(port: int) -> str:
    """Best-effort PID/command for listeners on *port* (lsof when present)."""
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return "PID unknown (install lsof for process details)"
    text = (result.stdout or "").strip()
    if result.returncode == 0 and text:
        return text
    return "PID unknown (install lsof for process details)"


class OccupiedPortError(RuntimeError):
    """Raised when the E2E port already has a TCP listener."""


def occupied_message(port: int, host: str, listeners: str) -> str:
    return (
        f"ERROR: E2E port {port} on {host} is already in use.\n"
        f"The runner refuses to start Flask so the suite cannot attach to "
        f"another process or database.\n"
        f"Listener:\n{listeners}\n"
        f"Recovery: stop that process yourself, or re-run with an explicit "
        f"free port (example: PORT=8766 bash run-e2e.sh). "
        f"The runner never kills a third-party process."
    )


def assert_port_free(port: int, host: str = DEFAULT_HOST) -> None:
    """Raise OccupiedPortError when *host:port* is already serving."""
    if not is_listening(host, port):
        return
    raise OccupiedPortError(occupied_message(port, host, describe_listeners(port)))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exit 1 if the E2E Flask port is already occupied."
    )
    parser.add_argument(
        "port",
        nargs="?",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port to check (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to probe (default: {DEFAULT_HOST})",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(None if argv is None else list(argv))
    if args.port <= 0 or args.port > 65535:
        print(f"ERROR: invalid E2E port {args.port}", file=sys.stderr)
        return 2
    try:
        assert_port_free(args.port, host=args.host)
    except OccupiedPortError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
