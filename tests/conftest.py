"""
CYPHER65 // Test fixtures
=========================
Shared mock utilities for unit-testing app.py persistence functions.
"""

import logging
import os
import tempfile

import pytest

# Silence noisy loggers during tests
logging.disable(logging.CRITICAL)

# ── C4 // HERMETIC SUITE ────────────────────────────────────────────────────
# Never touch the production data/war_room.sqlite. The recurring index
# corruption (idx_maintenance_records_ts / idx_audit_logs_tenant_ts) was
# caused by TWO WRITERS on the same file: the Docker/Colima app writing via
# its volume mount, and pytest's `import app` — which runs init_db() +
# _core_registry.load_from_db() at module scope in ~20 test files — hitting
# the real DB from the host.
#
# Redirect the env var BEFORE any test module imports `app` (conftest is
# imported first by pytest, so the scratch path is in effect for every
# module-level `import app`). Per-test DB_PATH overrides still win where a
# test needs its own scratch DB via monkeypatch.setenv.
_SCRATCH_DIR = tempfile.mkdtemp(prefix="cypher65_tests_")
os.environ["DB_PATH"] = os.path.join(_SCRATCH_DIR, "war_room.sqlite")


def pytest_configure(config):
    """Register requirement markers used by the test traceability contract."""
    config.addinivalue_line(
        "markers",
        "covers(requirement_id, status='full'): link a test to a strategy ID",
    )


def pytest_collection_finish(session):
    """Expose only real, collected pytest items and their requirement markers."""
    links = {}
    for item in session.items:
        for marker in item.iter_markers("covers"):
            if marker.args:
                requirement_id = marker.args[0]
                status = marker.kwargs.get("status", "full")
                links.setdefault(requirement_id, []).append((item.nodeid, status))

    # Playwright specs are collected by a separate runner; their structured
    # comment is valid only when the spec also declares at least one test.
    import re
    from pathlib import Path

    for spec in Path(__file__).parent.joinpath("e2e").glob("*.spec.js"):
        source = spec.read_text(encoding="utf-8")
        marker_pattern = re.compile(
            r"test-requirement:\s*([A-Z]+-\d{3})\s+status=(full|partial)"
            r"(?:(?!test-requirement:).){0,200}\btest\s*\(",
            re.DOTALL,
        )
        for requirement_id, status in marker_pattern.findall(source):
            links.setdefault(requirement_id, []).append(
                (
                    f"{spec.relative_to(Path(__file__).parent.parent)}::Playwright test",
                    status,
                )
            )
    session.config._requirement_test_links = links


# Issue #477: a SECRET_KEY de teste documentada localmente (22 bytes) dispara
# InsecureKeyLengthWarning do PyJWT (HMAC-SHA256 pede >= 32 bytes, RFC 7518
# §3.2) em cada emit/verify de JWT — 26 warnings por run, todos dessa causa
# raiz única. A env aqui garante >= 32 bytes quando o operador não exportou
# uma própria (o CI já roda com chave de 35 bytes); uma SECRET_KEY exportada
# de 22+ bytes continua vencendo, então o warning permanece como sinal real.
if len(os.environ.get("SECRET_KEY", "")) < 32:
    os.environ["SECRET_KEY"] = "test-secret-0123456789-0123456789-0123456789"

# Behavior tests call mutation POSTs without a caller identity because open
# mode and loopback used to count as admin. The gate now refuses that.
# Present a real API-key principal unless the test already chose headers
# (including an explicit empty set) or the test is the anonymous-gate suite.
_MUTATION_PRINCIPAL_KEY = "fase0-mutation-principal"
_MUTATION_PRINCIPAL_FLAG = "CYPHER65_TEST_PRINCIPAL"


def _header_names(headers) -> set[str]:
    if not headers:
        return set()
    return {str(name).lower() for name in headers}


def _install_mutation_principal_header():
    from flask.testing import FlaskClient

    if getattr(FlaskClient.open, "_cypher65_principal", False):
        return
    original = FlaskClient.open

    def open_with_principal(self, *args, **kwargs):
        if os.environ.get(_MUTATION_PRINCIPAL_FLAG) != "1":
            return original(self, *args, **kwargs)
        if kwargs.get("method", "GET") != "POST":
            return original(self, *args, **kwargs)
        from services.mutation_auth import is_dangerous_mutation

        target = args[0] if args else kwargs.get("path") or ""
        if not is_dangerous_mutation(str(target), "POST"):
            return original(self, *args, **kwargs)
        provided = kwargs.get("headers") if "headers" in kwargs else None
        # headers={} is an explicit anonymous call. Other headers (for example
        # Idempotency-Key) still need a principal merged in.
        if "headers" in kwargs and not provided:
            return original(self, *args, **kwargs)
        names = _header_names(provided)
        if "authorization" in names or "x-api-key" in names:
            return original(self, *args, **kwargs)
        key = os.environ.get("API_KEY", "")
        injected_env = False
        if not key and not os.environ.get("TENANT_API_KEYS"):
            key = _MUTATION_PRINCIPAL_KEY
            os.environ["API_KEY"] = key
            injected_env = True
        if not key:
            return original(self, *args, **kwargs)
        merged = dict(provided or {})
        merged["X-API-Key"] = key
        kwargs["headers"] = merged
        try:
            return original(self, *args, **kwargs)
        finally:
            if injected_env:
                os.environ.pop("API_KEY", None)

    open_with_principal._cypher65_principal = True
    FlaskClient.open = open_with_principal


_install_mutation_principal_header()


@pytest.fixture(autouse=True)
def _present_mutation_principal(request, monkeypatch):
    """Give handler tests a principal. Anonymous coverage lives in its own file."""
    nodeid = request.node.nodeid
    if nodeid.startswith("tests/test_mutation_principal.py"):
        monkeypatch.delenv(_MUTATION_PRINCIPAL_FLAG, raising=False)
        return
    # The header is attached only on dangerous POSTs, and only for that
    # request. Leaving API_KEY unset keeps open-mode assertions intact.
    monkeypatch.setenv(_MUTATION_PRINCIPAL_FLAG, "1")


class MockRow:
    """Mimics sqlite3.Row dict-like access for test mocking.
    The real sqlite3.Row supports r["key"] access — this mock
    replicates only the interface that _restore_btc_address_from_db
    actually uses (__getitem__ with string keys).
    """

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __bool__(self):
        return bool(self._data)


class MockCursor:
    """Mimics sqlite3.Cursor with a configurable fetchone return value."""

    def __init__(self, fetchone_result=None):
        self._result = fetchone_result
        self.executed_sql = None

    def execute(self, sql, params=None):
        self.executed_sql = sql
        return self

    def fetchone(self):
        return self._result


class MockConn:
    """Mimics sqlite3.Connection, returning a given cursor on cursor()."""

    def __init__(self, cursor: MockCursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True
