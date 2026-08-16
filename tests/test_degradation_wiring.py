"""Wiring tests for Issue #202 — converted hot-path `except: pass` sites.

Before #202 a provider/DB hiccup in these sites died SILENT (no log, no
telemetry, no trace) — exactly the "silent failure" class that made missing
data look like bugs. Now each site logs a WARNING, the root-logger
DegradationMetricsHandler (installed at boot by app.py) buckets it into
degradation_metrics with request_id, and the admin panel surfaces a
spike/sustained badge.

These tests prove the WIRING end-to-end without touching the network or the
real boot: a real converted function is forced to fail, and we assert the
WARNING actually reached the degradation table through the logging path.

Sites covered (all converted in #202):
  - services.hashrate_market._purge_glitch_history  → glitch-history purge
  - services.proximity._nearest_history_before      → nearest history lookup
"""

import logging
import sys
import time

import pytest

sys.path.insert(0, ".")

import services.error_tracker as et  # noqa: E402
import services.hashrate_market as hm  # noqa: E402
import services.proximity as prox  # noqa: E402


@pytest.fixture()
def clean_degradation():
    from services.db import get_db

    conn = get_db()
    et.ensure_degradation_table(conn)
    conn.execute("DELETE FROM degradation_metrics")
    conn.commit()
    conn.close()
    yield
    conn = get_db()
    conn.execute("DELETE FROM degradation_metrics")
    conn.commit()
    conn.close()


@pytest.fixture()
def root_degradation_handler():
    """Attach a scratch DegradationMetricsHandler to the ROOT logger (the
    same path app.py uses at boot, minus the singleton), lift the conftest
    logging mute, and always detach + restore in teardown."""
    from services.db import get_db

    _prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    handler = et.DegradationMetricsHandler(get_db)
    logging.getLogger().addHandler(handler)
    yield handler
    logging.getLogger().removeHandler(handler)
    handler.close()
    logging.disable(_prev_disable)


def _degradation_rows_like(pattern):
    from services.db import get_db

    conn = get_db()
    rows = conn.execute(
        "SELECT module, func, message, level FROM degradation_metrics "
        "WHERE message LIKE ?",
        (pattern,),
    ).fetchall()
    conn.close()
    return rows


def test_hashrate_market_purge_failure_warns(clean_degradation, root_degradation_handler):
    """A broken conn inside _purge_glitch_history (the old silent `pass`)
    now logs a WARNING that lands in degradation_metrics."""

    class _BrokenConn:
        def cursor(self):
            raise RuntimeError("db down")

    hm._purged_glitch_history = False  # re-arm the one-time guard

    hm._purge_glitch_history(_BrokenConn())  # must NOT raise

    rows = _degradation_rows_like("%glitch-history purge failed%")
    assert len(rows) == 1
    assert rows[0]["module"] == "cypher65"
    assert rows[0]["level"] == "WARNING"


def test_proximity_lookup_failure_warns(clean_degradation, root_degradation_handler):
    """_nearest_history_before with a broken DB factory (old silent `pass`)
    now logs a WARNING that lands in degradation_metrics, and still returns
    None (graceful degradation preserved)."""

    def _broken():
        raise RuntimeError("db down")

    old_get_db = prox._get_db
    prox._get_db = _broken
    try:
        result = prox._nearest_history_before(int(time.time()))
        assert result is None  # contract preserved: None on failure
    finally:
        prox._get_db = old_get_db

    rows = _degradation_rows_like("%nearest history lookup failed%")
    assert len(rows) == 1
    assert rows[0]["module"] == "cypher65"
    assert rows[0]["level"] == "WARNING"
    assert rows[0]["func"] == "_nearest_history_before"


def test_warnings_carry_request_id(clean_degradation, root_degradation_handler):
    """The active request_id rides along on degradation records (correlation
    with JSON logs / Sentry), same discipline as the error bucket."""

    class _BrokenConn:
        def cursor(self):
            raise RuntimeError("db down")

    hm._purged_glitch_history = False
    # The handler's emit() imports get_request_id fresh from services.observability
    # on every record — patch the module attribute so the correlation id flows.
    from services import observability

    orig = observability.get_request_id
    observability.get_request_id = lambda: "req-wiring-xyz"
    try:
        hm._purge_glitch_history(_BrokenConn())
    finally:
        observability.get_request_id = orig

    from services.db import get_db

    conn = get_db()
    row = conn.execute(
        "SELECT last_request_id FROM degradation_metrics "
        "WHERE message LIKE '%glitch-history purge failed%'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["last_request_id"] == "req-wiring-xyz"
