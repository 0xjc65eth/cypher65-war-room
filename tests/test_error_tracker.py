"""Hermetic tests for services/error_tracker (Issue #176).

Covers:
  1. record_error: hourly-bucket upsert (same hour → count++, last rid wins),
     different hour → separate row, field truncation caps.
  2. fetch_error_rate: buckets ascending, total, peak per hour, top modules,
     recent rows (newest first, with request_id).
  3. purge_error_metrics: retention window (rows older than 7 days deleted).
  4. ErrorMetricsHandler: records ERROR/CRITICAL, ignores WARNING/INFO,
     swallows DB failures (never breaks logging).
  5. Route /api/admin/error-rate: 403 for remote callers, 200 + telemetry
     payload with the operator X-API-Key (same gate as pool-metrics).
"""

import logging
import sys
import time

import pytest

sys.path.insert(0, ".")

import services.error_tracker as et  # noqa: E402


@pytest.fixture()
def clean_errors():
    from services.db import get_db

    conn = get_db()
    et.ensure_table(conn)
    conn.execute("DELETE FROM error_metrics")
    conn.commit()
    conn.close()
    yield
    conn = get_db()
    conn.execute("DELETE FROM error_metrics")
    conn.commit()
    conn.close()


@pytest.fixture()
def isolated_client():
    """Flask test client against the conftest-owned SCRATCH DB."""
    import app as _app_module

    _app_module.app.config["TESTING"] = True
    return _app_module.app.test_client()


# ── record_error ───────────────────────────────────────────────────────────


def test_record_upserts_same_hour(clean_errors):
    from services.db import get_db

    now = int(time.time())
    et.record_error(
        get_db(),
        module="cypher65.poll",
        func="_do_poll",
        message="fetch boom",
        request_id="poll-abc",
        ts=now,
    )
    et.record_error(
        get_db(),
        module="cypher65.poll",
        func="_do_poll",
        message="fetch boom",
        request_id="poll-def",
        ts=now,
    )
    conn = get_db()
    rows = conn.execute("SELECT count, last_request_id FROM error_metrics").fetchall()
    conn.close()
    assert len(rows) == 1  # deduped by (hour, module, func, message)
    assert rows[0]["count"] == 2
    assert rows[0]["last_request_id"] == "poll-def"  # latest wins


def test_record_different_hour_separate_rows(clean_errors):
    from services.db import get_db

    now = int(time.time())
    et.record_error(get_db(), module="m", func="f", message="a", ts=now)
    et.record_error(get_db(), module="m", func="f", message="a", ts=now - 3600)
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM error_metrics").fetchone()["n"]
    conn.close()
    assert n == 2


def test_record_truncates_fields(clean_errors):
    from services.db import get_db

    et.record_error(get_db(), module="m" * 200, func="f", message="x" * 500)
    conn = get_db()
    row = conn.execute("SELECT module, message FROM error_metrics").fetchone()
    conn.close()
    assert len(row["module"]) == 64
    assert len(row["message"]) == 200


# ── fetch_error_rate ───────────────────────────────────────────────────────


def test_fetch_error_rate_buckets(clean_errors):
    from services.db import get_db

    now = int(time.time())
    hour = now // 3600 * 3600
    et.record_error(
        get_db(), module="cypher65.fetch", func="user", message="timeout", ts=now
    )
    et.record_error(
        get_db(), module="cypher65.fetch", func="user", message="timeout", ts=now
    )
    et.record_error(
        get_db(), module="cypher65.persist", func="snapshot", message="disk", ts=now
    )
    et.record_error(
        get_db(), module="cypher65.fetch", func="user", message="timeout", ts=now - 3600
    )

    data = et.fetch_error_rate(get_db(), hours=24)
    assert data["total"] == 4
    assert data["peak_per_hour"] == 3
    assert len(data["buckets"]) == 2
    # Ascending: first bucket is the older hour (1 error), second the current (3).
    assert data["buckets"][0]["ts"] == hour - 3600
    assert data["buckets"][0]["errors"] == 1
    assert data["buckets"][1]["ts"] == hour
    assert data["buckets"][1]["errors"] == 3
    mods = {m["module"]: m["count"] for m in data["buckets"][1]["modules"]}
    assert mods["cypher65.fetch"] == 2
    assert mods["cypher65.persist"] == 1
    top = {m["module"]: m["count"] for m in data["top_modules"]}
    assert top["cypher65.fetch"] == 3
    assert top["cypher65.persist"] == 1
    # Recent rows: newest first, request_id preserved.
    assert len(data["recent"]) == 3
    assert data["recent"][0]["last_request_id"] == ""


def test_fetch_error_rate_empty_is_honest(clean_errors):
    from services.db import get_db

    data = et.fetch_error_rate(get_db(), hours=24)
    assert data["total"] == 0
    assert data["peak_per_hour"] == 0
    assert data["buckets"] == []
    assert data["top_modules"] == []
    assert data["recent"] == []


def test_purge_retention(clean_errors):
    from services.db import get_db

    conn = get_db()
    now = int(time.time())
    hour = now // 3600 * 3600
    old_hour = hour - 8 * 86400  # 8 days ago → outside the 7-day window
    conn.execute(
        "INSERT INTO error_metrics "
        "(hour_ts, module, func, message, level, count, last_ts, last_request_id) "
        "VALUES (?, ?, ?, ?, 'ERROR', 1, ?, '')",
        (old_hour, "m", "f", "old", now),
    )
    conn.execute(
        "INSERT INTO error_metrics "
        "(hour_ts, module, func, message, level, count, last_ts, last_request_id) "
        "VALUES (?, ?, ?, ?, 'ERROR', 1, ?, '')",
        (hour, "m", "f", "new", now),
    )
    conn.commit()
    deleted = et.purge_error_metrics(conn)
    conn.close()
    assert deleted == 1
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM error_metrics").fetchone()["n"]
    conn.close()
    assert n == 1


# ── ErrorMetricsHandler ────────────────────────────────────────────────────


def _make_test_logger(name, handler):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # hermetic: only THIS handler sees the records
    logger.addHandler(handler)
    return logger


def test_handler_records_errors_only(clean_errors):
    from services.db import get_db

    # conftest silences ALL logging (logging.disable(CRITICAL)) — lift it for
    # the emit so records really flow through the logger → handler path.
    _prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    handler = et.ErrorMetricsHandler(get_db)
    logger = _make_test_logger("test.err.tracker", handler)
    try:
        logger.error("boom detail")
        logger.warning("warn ignored")
        logger.info("info ignored")
        logger.critical("critical detail")
    finally:
        logging.disable(_prev_disable)
        logger.removeHandler(handler)
        handler.close()
    conn = get_db()
    rows = conn.execute(
        "SELECT message, level, module FROM error_metrics ORDER BY last_ts"
    ).fetchall()
    conn.close()
    msgs = [(r["message"], r["level"]) for r in rows]
    assert ("boom detail", "ERROR") in msgs
    assert ("critical detail", "CRITICAL") in msgs
    assert all("warn ignored" not in m for m, _ in msgs)
    assert all("info ignored" not in m for m, _ in msgs)
    assert rows[0]["module"] == "test.err.tracker"


def test_handler_swallows_db_failures():
    def _broken():
        raise RuntimeError("db down")

    _prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)  # lift the conftest mute so emit runs
    handler = et.ErrorMetricsHandler(_broken)
    logger = _make_test_logger("test.err.broken", handler)
    try:
        # emit() must never raise — logging can't be broken by telemetry.
        logger.error("should not raise")
    finally:
        logging.disable(_prev_disable)
        logger.removeHandler(handler)
        handler.close()


# ── Route /api/admin/error-rate ────────────────────────────────────────────


def test_admin_error_rate_requires_admin(isolated_client, clean_errors):
    resp = isolated_client.get(
        "/api/admin/error-rate", environ_base={"REMOTE_ADDR": "203.0.113.5"}
    )
    assert resp.status_code == 403


def test_admin_error_rate_returns_telemetry(isolated_client, clean_errors, monkeypatch):
    monkeypatch.setenv("API_KEY", "operator-key-123")
    from services.db import get_db

    et.record_error(
        get_db(),
        module="cypher65.fetch",
        func="user",
        message="timeout",
        request_id="poll-abc",
    )
    resp = isolated_client.get(
        "/api/admin/error-rate", headers={"X-API-Key": "operator-key-123"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["buckets"][0]["errors"] == 1
    assert data["recent"][0]["last_request_id"] == "poll-abc"
    # Honest flags: no DSN in the test env → disabled, but release never empty.
    assert data["sentry_enabled"] is False
    assert data["sentry_release"]
    assert data["sentry_environment"] in ("cloud", "self-hosted")
