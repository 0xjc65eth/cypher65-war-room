"""Regression guards for the Playwright runner (Issues #430 and #437)."""

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "e2e_port_guard.py"
_SPEC = importlib.util.spec_from_file_location("e2e_port_guard", GUARD)
e2e_port_guard = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(e2e_port_guard)


def _load_playwright_ci_policy(ci_value: str) -> dict:
    script = (
        "import('./tests/e2e/support/ci-policy.js').then(({isCiEnabled}) => "
        "console.log(JSON.stringify({enabled: isCiEnabled()})))"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        env={**os.environ, "CI": ci_value},
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_ci_false_is_not_treated_as_enabled():
    assert _load_playwright_ci_policy("false") == {
        "enabled": False,
    }


def test_ci_true_enables_ci_policy():
    assert _load_playwright_ci_policy("true") == {
        "enabled": True,
    }


def test_playwright_config_wires_explicit_ci_policy():
    config = (ROOT / "playwright.config.js").read_text(encoding="utf-8")
    assert "const isCI = isCiEnabled();" in config
    assert "forbidOnly: isCI" in config
    assert "retries: isCI ? 1 : 0" in config


def test_runner_default_rate_limit_matches_ci_capacity():
    runner = (ROOT / "run-e2e.sh").read_text(encoding="utf-8")
    assert 'RATE_LIMIT_PER_MINUTE="${RATE_LIMIT_PER_MINUTE:-10000}"' in runner


def test_boot_specs_report_http_status_before_waiting_for_app_shell():
    for relative_path in (
        "tests/e2e/dashboard.spec.js",
        "tests/e2e/modals.spec.js",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "returned HTTP ${response.status()}" in source


def test_runner_invokes_port_guard_before_starting_flask():
    runner = (ROOT / "run-e2e.sh").read_text(encoding="utf-8")
    guard_at = runner.index('python3 "$PORT_GUARD_PY" "$PORT"')
    flask_at = runner.index("$VENV_PYTHON app.py")
    playwright_at = runner.index("npx playwright test")
    install_at = runner.index("npx playwright install")
    assert guard_at < flask_at
    assert guard_at < playwright_at
    assert guard_at < install_at
    assert "never kills" in runner


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — stdlib signature
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):  # noqa: A003
        return


def _serve_once():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_port_guard_allows_a_free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    result = subprocess.run(
        [sys.executable, str(GUARD), str(port), "--host", "127.0.0.1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_port_guard_fails_fast_on_occupied_port_without_killing_listener():
    server = _serve_once()
    port = server.server_address[1]
    try:
        result = subprocess.run(
            [sys.executable, str(GUARD), str(port), "--host", "127.0.0.1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert f"port {port}" in result.stderr
        assert "never kills a third-party process" in result.stderr
        assert str(port) in result.stderr
        with socket.create_connection(("127.0.0.1", port), timeout=1) as sock:
            sock.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            assert sock.recv(16)
    finally:
        server.shutdown()
        server.server_close()


def test_port_guard_honors_explicit_port_override():
    server = _serve_once()
    occupied = server.server_address[1]
    try:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
        probe.close()
        busy = subprocess.run(
            [sys.executable, str(GUARD), str(occupied), "--host", "127.0.0.1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        free = subprocess.run(
            [sys.executable, str(GUARD), str(free_port), "--host", "127.0.0.1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert busy.returncode == 1
        assert free.returncode == 0
        assert str(occupied) in busy.stderr
        assert str(free_port) not in busy.stderr
    finally:
        server.shutdown()
        server.server_close()


def test_assert_port_free_is_idempotent_on_a_closed_socket():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    time.sleep(0.05)
    e2e_port_guard.assert_port_free(port, host="127.0.0.1")
